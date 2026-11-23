"""프레임에서 사용할 파츠 방향과 GPU 페이지의 수명."""

from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, field
import os

from .direction_texture_arrays import DirectionArrayUploadError
from .texture_codecs import texture_payload_size
from .texture_page_work import DEFAULT_DECODE_WORKERS, TexturePageWork, decoded_pages


DIRECTION_LOOKAHEAD_FRAMES = 8
FRAME_UPLOAD_BYTES = 6 * 1024**2
FRAME_UPLOADS = 4


class AtlasFrameBudget:
    def __init__(self):
        self.reset()

    def reset(self):
        self.uploads = self.upload_bytes = 0

    def can_upload(self, size):
        return self.uploads < FRAME_UPLOADS and (not self.uploads or self.upload_bytes + size <= FRAME_UPLOAD_BYTES)

    def consume_upload(self, size):
        self.uploads += 1
        self.upload_bytes += size


@dataclass
class DirectionPrefetch:
    key: tuple
    resource: dict = field(default_factory=dict)
    requests: dict = field(default_factory=dict)
    jobs: dict = field(default_factory=dict)
    retained: list = field(default_factory=list)
    sizes: dict = field(default_factory=dict)
    metadata: Future | None = None
    streamed: bool = False


class PartAtlasResidency:
    def __init__(self, catalog, cache, timings, *, max_directions, budget_bytes):
        self.catalog, self.cache, self.timings = catalog, cache, timings
        self.source, self.paged = catalog.source, catalog.paged
        self.resources = OrderedDict()
        self.max_directions = max(2, max_directions)
        self.cache_budget_bytes = budget_bytes
        self.loads = self.prefetch_uploads = self.prefetch_completed = 0
        self.threaded_pages = 0
        self.prefetch = self.executor = self.last_yaw_pose = None
        self.metadata_jobs = {}

    def _worker_pool(self):
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=DEFAULT_DECODE_WORKERS, thread_name_prefix="fdrive-direction")
        return self.executor

    def get(self, motion, direction):
        key = motion, str(direction)
        if key not in self.resources:
            self.require((key,))
        self.resources.move_to_end(key)
        return self.resources[key]

    def _page_storage_bytes(self, page):
        size = getattr(self.cache, "storage_bytes_for", None)
        return size(page) if size else texture_payload_size(page["codec"], page["width"], page["height"])

    def _describe_direction(self, key, *, prepared=None):
        motion, direction = key
        path, data = self.catalog.direction(motion, direction, prepared=prepared)
        fields, requests = {}, {}
        if self.paged:
            for kind, pages in data["pages"].items():
                fields[kind] = []
                for page in pages:
                    file = os.path.abspath(path.parent / page["file"])
                    key = kind, file, page["sha256"], page.get("offset", 0)
                    fields[kind].append((self.cache.page_handle(key), key, dict(page, file=file)))
            return {"data": data, "pages": fields}, requests
        for kind, pages in data["pages"].items():
            page, = pages
            page_key = self.cache.page_key(page, path.parent)
            fields[kind] = page_key
            requests.setdefault(page_key, dict(page, file=page_key[0]))
        return {"data": data, "pages": fields, "keys": tuple(fields.values()), "pose_identity": object()}, requests

    def require(self, keys, *, preload_limit_bytes=None, direction_arrays=False):
        """선적재 때는 방향 정보를 읽되 남은 예산에 맞는 텍스처만 올린다."""
        if self.prefetch is not None and self.prefetch.key in keys:
            self._advance_prefetch(set(keys), required=True)
        resources, requests = {}, {}
        remaining = None if preload_limit_bytes is None else preload_limit_bytes - self.cache.gpu_storage_bytes
        for key in keys:
            if key in self.resources or key in resources:
                continue
            metadata = self.metadata_jobs.pop(key, None)
            prepared = metadata.result() if metadata is not None else None
            resource, pages = self._describe_direction(key, prepared=prepared)
            if remaining is not None:
                cost = sum(self._page_storage_bytes(page) for page_key, page in pages.items()
                           if page_key not in requests and page_key not in self.cache.entries)
                if cost > remaining or len(self.resources) + len(resources) >= self.max_directions:
                    continue
                remaining -= cost
            resources[key] = resource
            requests.update(pages)
        if not resources:
            return
        if self.paged:
            self.resources.update(resources)
            self.loads += len(resources)
            return
        pending = {key: spec for key, spec in requests.items() if key not in self.cache.entries}
        if self.cache_budget_bytes is not None:
            incoming = sum(map(self._page_storage_bytes, pending.values()))
            self.evict(set(keys), incoming, requests.keys())
        array_slots = self.cache.plan_arrays(resources, pending, preload_limit_bytes) if direction_arrays else {}
        acquired = []
        try:
            with closing(decoded_pages(tuple(pending.values()), self.source.parent, timings=self.timings,
                                       ktx_library=self.cache.ktx_library,
                                       executor=self._worker_pool() if pending else None)) as decoded:
                for resource in resources.values():
                    for kind, page_key in resource["pages"].items():
                        prepared = next(decoded) if pending.pop(page_key, None) is not None else None
                        options = (dict(array_slot=array_slots.get(page_key), exact=True) if array_slots else {})
                        _, entry = self.cache.acquire(requests[page_key], self.source.parent, prepared=prepared, **options)
                        acquired.append(page_key)
                        resource["pages"][kind] = entry
                    if array_slots and (array := resource["pages"]["color"].get("direction_array")):
                        resource["array_group"] = array.group
        except BaseException as exc:
            for key in reversed(acquired):
                self.cache.release(key)
            if isinstance(exc, DirectionArrayUploadError):
                self.cache.use_direction_arrays = False
                self.require(keys, preload_limit_bytes=preload_limit_bytes)
                return
            raise
        self.resources.update(resources)
        self.loads += len(resources)

    def cancel_prefetch(self):
        stage, self.prefetch = self.prefetch, None
        if stage is None:
            return
        if stage.metadata is not None:
            stage.metadata.cancel()
        for _, future in stage.jobs.values():
            future.cancel()
        for page_key in stage.retained:
            self.cache.release(page_key)

    def _start_prefetch(self, key, needed, *, streamed=False):
        stage = self.prefetch = DirectionPrefetch(key, streamed=streamed)
        planned = self.metadata_jobs.pop(key, None)
        if self.catalog.has_direction(*key):
            if planned is not None:
                planned.cancel()
            self._prepare_prefetch(stage, needed)
        else:
            stage.metadata = planned if planned is not None else self._worker_pool().submit(self.catalog.read_direction, *key)

    def _queue_metadata(self, keys, lookahead):
        requested = dict.fromkeys((*keys, lookahead) if lookahead is not None else keys)
        for key, future in tuple(self.metadata_jobs.items()):
            if key not in requested and (future.done() or future.cancel()):
                del self.metadata_jobs[key]
        active = self.prefetch.key if self.prefetch is not None else None
        for key in requested:
            if len(self.metadata_jobs) >= DEFAULT_DECODE_WORKERS - 1:
                break
            if (key != active and key not in self.resources and key not in self.metadata_jobs
                    and not self.catalog.has_direction(*key)):
                self.metadata_jobs[key] = self._worker_pool().submit(self.catalog.read_direction, *key)

    def _ready_prefetch(self, needed, *, required=False):
        stage = self.prefetch
        if stage is None or stage.metadata is None:
            return stage
        if not required and not stage.metadata.done():
            return None
        prepared = stage.metadata.result()
        stage.metadata = None
        self._prepare_prefetch(stage, needed, prepared=prepared)
        return self.prefetch

    def _prepare_prefetch(self, stage, needed, *, prepared=None):
        resource, requests = self._describe_direction(stage.key, prepared=prepared)
        sizes = {page_key: texture_payload_size(page["codec"], page["width"], page["height"])
                 for page_key, page in requests.items()}
        if self.cache_budget_bytes is not None:
            protected = {page_key for direction in needed for page_key in self.resources[direction]["keys"]}
            required_bytes = sum(map(self._page_storage_bytes, requests.values())) + sum(
                self.cache.entries[page_key]["gpu"]["storage_bytes"] for page_key in protected - requests.keys())
            if required_bytes > self.cache_budget_bytes:
                self.cancel_prefetch()
                return
        stage.resource, stage.requests, stage.sizes = resource, requests, sizes
        for page_key in sorted(requests, key=sizes.__getitem__, reverse=True):
            page = requests[page_key]
            if page_key in self.cache.entries:
                self.cache.acquire(page, self.source.parent)
                stage.retained.append(page_key)
            else:
                work = TexturePageWork(page, self.source.parent, timings=self.timings, ktx_library=self.cache.ktx_library)
                stage.jobs[page_key] = work, self._worker_pool().submit(work.run)
                if stage.streamed:
                    self.threaded_pages += 1

    def _advance_prefetch(self, needed, *, required=False):
        try:
            stage = self._ready_prefetch(needed, required=required)
            if stage is None:
                return
            for page_key, (work, future) in tuple(stage.jobs.items()):
                new_texture = page_key not in self.cache.entries
                if new_texture and not required and not future.done():
                    continue
                page = stage.requests[page_key]
                prepared = None
                if new_texture:
                    future.result()
                    if self.cache_budget_bytes is not None:
                        incoming = self._page_storage_bytes(page)
                        self.evict(needed, incoming, stage.requests.keys())
                        if not required and self.cache.gpu_storage_bytes + incoming > self.cache_budget_bytes:
                            self.cancel_prefetch()
                            return
                    prepared = work.take_result()
                else:
                    future.cancel()
                self.cache.acquire(page, self.source.parent, prepared=prepared)
                stage.retained.append(page_key)
                del stage.jobs[page_key]
                if not required and new_texture:
                    self.prefetch_uploads += 1
                    break
        except (OSError, ValueError, RuntimeError):
            self.cancel_prefetch()
            if required:
                raise
            return
        self._publish_prefetch(stage, required=required)

    def _publish_prefetch(self, stage, *, required=False):
        if stage.metadata is not None or stage.jobs:
            return
        resource = stage.resource
        resource["keys"] = tuple(stage.retained)
        resource["pages"] = {kind: self.cache.entries[key] for kind, key in resource["pages"].items()}
        self.resources[stage.key] = resource
        self.prefetch = None
        if required:
            self.loads += 1
        else:
            self.prefetch_completed += 1

    def stream(self, keys, pinned, budget, *, lookahead=None):
        """전투 중 요청한 방향을 준비한다. 완료되지 않은 워커에 대기하지 않는다."""
        protected = set(keys).union(pinned).intersection(self.resources)
        for key in keys:
            if key in self.resources:
                self.resources.move_to_end(key)
        try:
            if self.prefetch is None:
                missing = next((key for key in keys if key not in self.resources), lookahead)
                if missing is not None:
                    self._start_prefetch(missing, protected, streamed=True)
            stage = self._ready_prefetch(protected)
            self._queue_metadata(keys, lookahead)
            if stage is None:
                return
            self._upload_stream_pages(stage, protected, budget)
        except BaseException:
            self.cancel_prefetch()
            raise
        self._publish_prefetch(stage)
        self.evict(protected | (set(keys) & self.resources.keys()))

    def _upload_stream_pages(self, stage, protected, budget):
        for page_key, (work, task) in tuple(stage.jobs.items()):
            page = stage.requests[page_key]
            prepared = None
            if page_key in self.cache.entries:
                task.cancel()
            else:
                size = stage.sizes[page_key]
                if not task.done() or not budget.can_upload(size):
                    continue
                task.result()
                storage = self._page_storage_bytes(page)
                self.evict(protected, storage, stage.requests.keys())
                if self.cache_budget_bytes is not None and self.cache.gpu_storage_bytes + storage > self.cache_budget_bytes:
                    continue
                budget.consume_upload(size)
                prepared = work.take_result()
                self.prefetch_uploads += 1
            self.cache.acquire(page, self.source.parent, prepared=prepared)
            stage.retained.append(page_key)
            del stage.jobs[page_key]

    def adjacent_candidates(self, motion, angles):
        previous = self.last_yaw_pose
        self.last_yaw_pose = motion, angles
        candidates = []
        if previous is not None and previous[0] == motion:
            for old, yaw in zip(previous[1], angles, strict=True):
                step = (yaw - old + 180) % 360 - 180
                if abs(step) < 0.01:
                    continue
                bank, phase = divmod(yaw % 360, 45)
                if step > 0:
                    neighbor = int(bank) + (2 if phase else 1)
                    distance = 45 - phase if phase else 0
                else:
                    neighbor, distance = int(bank) - 1, phase
                key = motion, str(neighbor % 8)
                frames_left = distance / abs(step)
                if (frames_left <= DIRECTION_LOOKAHEAD_FRAMES and key not in self.resources
                        and key[1] in self.catalog.data["motions"][motion]):
                    candidates.append((frames_left, key))
        return candidates

    def prepare_adjacent(self, motion, angles, needed, *, allow_upload):
        candidates = self.adjacent_candidates(motion, angles)
        if candidates and (self.prefetch is None or all(key != self.prefetch.key for _, key in candidates)):
            _, key = min(candidates)
            if self.prefetch is not None:
                self.cancel_prefetch()
            if self.prefetch is None:
                self._start_prefetch(key, needed)
        if self.prefetch is not None and allow_upload:
            self._advance_prefetch(needed)

    def evict(self, needed, incoming_bytes=0, shared_pages=()):
        limit = max(self.max_directions, len(needed))
        for key in tuple(self.resources):
            over_budget = (self.cache_budget_bytes is not None and
                           self.cache.gpu_storage_bytes + incoming_bytes > self.cache_budget_bytes)
            if len(self.resources) <= limit and not over_budget:
                break
            if key in needed or any(page in shared_pages for page in self.resources[key]["keys"]):
                continue
            for page in self.resources.pop(key)["keys"]:
                self.cache.release(page)

    def close(self):
        if self.paged:
            self.cache.close()
            self.resources.clear()
        else:
            self.clear()
        if self.executor is not None:
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.executor = None

    def clear(self):
        if self.paged:
            self.cache.clear()
            self.resources.clear()
            self.last_yaw_pose = None
            return
        self.cancel_prefetch()
        for future in self.metadata_jobs.values():
            future.cancel()
        self.metadata_jobs.clear()
        self.last_yaw_pose = None
        for resource in self.resources.values():
            for key in resource["keys"]:
                self.cache.release(key)
        self.resources.clear()
