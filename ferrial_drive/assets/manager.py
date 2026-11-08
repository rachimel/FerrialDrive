"""동일 ID 자원 공유·참조 수명·디버그 전용 트랜잭션 핫 로드."""

from dataclasses import dataclass
from math import isfinite
from time import monotonic

from .catalog import AssetCatalog, read_document


def fingerprint(paths):
    result = []
    for path in paths:
        try:
            stat = path.stat()
            result.append((str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino))
        except OSError:
            result.append((str(path), None))
    return tuple(result)


@dataclass
class _Entry:
    definition: object
    resource: object
    paths: tuple
    stamp: tuple
    references: int = 0
    generation: int = 1
    error: str = ""


@dataclass(frozen=True)
class ReloadEvent:
    asset_id: str
    success: bool
    message: str


class AssetHandle:
    def __init__(self, manager, asset_id):
        self._manager = manager
        self.asset_id = asset_id
        self.closed = False

    @property
    def resource(self):
        if self.closed or self._manager.closed:
            raise RuntimeError("이미 해제한 에셋 핸들이다.")
        return self._manager._entries[self.asset_id].resource

    @property
    def generation(self):
        self.resource
        return self._manager._entries[self.asset_id].generation

    def close(self):
        if not self.closed:
            self.closed = True
            self._manager._release(self.asset_id)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class AssetManager:
    """열린 렌더러의 소유 스레드에서 호출하며 백엔드는 외부에서 주입한다."""

    def __init__(self, catalog, backend, *, debug=False, poll_interval=0.4, timings=None):
        if not isinstance(debug, bool) or not isfinite(poll_interval) or poll_interval <= 0:
            raise ValueError("debug는 bool, 조회 간격은 양수 초 단위여야 한다.")
        self.catalog = catalog
        self.backend = backend
        self.debug = debug
        self.poll_interval = poll_interval
        self.closed = False
        self._entries = {}
        self._next_poll = 0.0
        self._catalog_stamp = fingerprint((catalog.path,)) if catalog.path is not None else ()
        self._catalog_error = ""
        self._read = read_document
        self._load = backend.load
        if timings is not None:
            self._read = timings.wrap(self._read, name="assets.metadata")
            self._load = timings.wrap(self._load, name="assets.texture_load")

    def _prepare(self, definition):
        document = self._read(definition)
        before = fingerprint(document.dependencies)
        resource = self._load(document)
        if before != fingerprint(document.dependencies):
            resource.close()
            raise RuntimeError("로딩 중 원본이 변경되었다. 파일 저장 완료 후 다시 시도한다.")
        return resource, document.dependencies, before

    def acquire(self, asset_id):
        if self.closed:
            raise RuntimeError("닫힌 에셋 관리자다.")
        definition = self.catalog.definitions[asset_id]
        if asset_id not in self._entries:
            resource, paths, stamp = self._prepare(definition)
            self._entries[asset_id] = _Entry(definition, resource, paths, stamp)
        self._entries[asset_id].references += 1
        return AssetHandle(self, asset_id)

    def _release(self, asset_id):
        if self.closed:
            return
        entry = self._entries[asset_id]
        entry.references -= 1
        if entry.references == 0:
            self._entries.pop(asset_id).resource.close()

    def poll_reload(self, *, now=None, force=False):
        # 배포 실행에서는 파일 조회·자동 재로딩을 하지 않는다.
        if self.closed or not self.debug:
            return []
        now = monotonic() if now is None else now
        if not force and now < self._next_poll:
            return []
        self._next_poll = now + self.poll_interval
        events = []
        if self.catalog.path is not None:
            stamp = fingerprint((self.catalog.path,))
            if force or stamp != self._catalog_stamp:
                self._catalog_stamp = stamp
                try:
                    candidate = AssetCatalog.load(self.catalog.path)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    message = str(error)
                    if message != self._catalog_error or force:
                        events.append(ReloadEvent("catalog", False, message))
                    self._catalog_error = message
                else:
                    self.catalog = candidate
                    self._catalog_error = ""
        for asset_id, entry in tuple(self._entries.items()):
            # 삭제된 등록은 기존 핸들이 닫힐 때까지 살아 있다. 신규 획득은 거절한다.
            definition = self.catalog.definitions.get(asset_id)
            if definition is None:
                continue
            if not (force or entry.error or definition != entry.definition or fingerprint(entry.paths) != entry.stamp):
                continue
            try:
                resource, paths, stamp = self._prepare(definition)
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
                message = str(error)
                if message != entry.error or force:
                    events.append(ReloadEvent(asset_id, False, message))
                entry.error = message
                continue
            previous = entry.resource
            entry.resource, entry.paths, entry.stamp = resource, paths, stamp
            entry.definition, entry.error = definition, ""
            entry.generation += 1
            previous.close()
            events.append(ReloadEvent(asset_id, True, "다시 불러오기 완료"))
        return events

    def snapshot(self):
        return {asset_id: {"references": entry.references, "generation": entry.generation,
                           "rgba8_estimated_bytes": entry.resource.estimated_bytes, "error": entry.error}
                for asset_id, entry in self._entries.items()}

    def close(self):
        if not self.closed:
            self.closed = True
            entries, self._entries = self._entries, {}
            for entry in entries.values():
                entry.resource.close()
