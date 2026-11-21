"""파츠 페이지를 렌더 스레드의 채널별 텍스처 풀에 적재한다."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import ctypes as ct
from math import isqrt

from ferrial_drive.diagnostics.texture_metrics import bind_gl
from .atlas_texture_cache import TextureUploadBinding
from .part_atlas_pages import PAGE_CODECS, PAGE_SIDES
from .texture_codecs import texture_payload_size
from .texture_page_work import TexturePageArchive, TexturePageWork


TEXTURE_2D = 0x0DE1
FORMATS = {"color": (0x8E8C, None), "depth": (0x8058, 0x1908),
           "energy": (0x8229, 0x1903), "vector": (0x822B, 0x8227)}


class TexturePool:
    def __init__(self, kind, side, capacity, max_side):
        self.kind, self.side = kind, side
        self.columns = min(max_side // side, max(1, isqrt(capacity)))
        self.rows = min(max_side // side, capacity // self.columns)
        self.capacity = self.columns * self.rows
        self.size = self.columns * side, self.rows * side
        self.free = list(range(self.capacity - 1, -1, -1))
        self.slots = OrderedDict()
        self.texture = ct.c_uint()
        self.bytes = texture_payload_size(PAGE_CODECS[kind], *self.size)

    def position(self, index):
        return index % self.columns * self.side, index // self.columns * self.side


class PartPageCache:
    def __init__(self, pico, directory, timings, budget):
        self.pico, self.directory, self.timings = pico, directory, timings
        self.binding = TextureUploadBinding(pico)
        combined_slot_bytes = sum(texture_payload_size(PAGE_CODECS[kind], side, side)
                                  for kind, side in PAGE_SIDES.items())
        capacity = min(128, (budget if budget is not None else 256 * 2**20) // combined_slot_bytes)
        if capacity < 1 or self.binding.integer(0x0D33) < max(PAGE_SIDES.values()):
            raise RuntimeError("파츠 페이지 풀을 만들 GPU 텍스처 예산이 부족하다.")
        max_side = self.binding.integer(0x0D33)
        self.pools = {kind: TexturePool(kind, side, capacity, max_side) for kind, side in PAGE_SIDES.items()}
        self.entries, self.jobs = {}, {}
        self.page_handles, self.resident = {}, []
        self.draw_serial = 0
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fdrive-part-page")
        self.archive = TexturePageArchive()
        self.hits = self.misses = self.uploads = self.uploaded_bytes = self.read_bytes = 0
        self.gpu_storage_bytes = self.peak_gpu_storage_bytes = self.peak_resident_bytes = self.resident_bytes = 0
        self.draws_with_miss = self.prefetch_uploads = self.prefetch_hits = self.evictions = 0
        self.prefetched = set()
        u, i, p = ct.c_uint, ct.c_int, ct.c_void_p
        for name, result, args in (
            ("glGenTextures", None, (i, p)), ("glDeleteTextures", None, (i, p)),
            ("glTexStorage2D", None, (u, i, u, i, i)), ("glTexParameteri", None, (u, u, i)),
            ("glTexSubImage2D", None, (u, i, i, i, i, i, u, u, p)),
            ("glCompressedTexSubImage2D", None, (u, i, i, i, i, i, u, i, p)),
            ("glPixelStorei", None, (u, i)), ("glBindBuffer", None, (u, u)), ("glGetError", u, ())):
            setattr(self, name, bind_gl(pico, name, result, args))

    def _check_gl(self, stage):
        error = self.glGetError()
        if error:
            raise RuntimeError(f"파츠 페이지 {stage} 실패: GL {error:#x}")

    def _allocate(self):
        with self.timings.scope("parts.page_pool_allocate"):
            for kind, pool in self.pools.items():
                self.glGenTextures(1, ct.byref(pool.texture))
                self.binding.bind_texture(TEXTURE_2D, pool.texture.value)
                self.glTexStorage2D(TEXTURE_2D, 1, FORMATS[kind][0], *pool.size)
                for param, value in ((0x2801, 0x2601), (0x2800, 0x2601), (0x2802, 0x812F), (0x2803, 0x812F)):
                    self.glTexParameteri(TEXTURE_2D, param, value)
                if kind == "energy":
                    for channel in (0x8E42, 0x8E43, 0x8E44):
                        self.glTexParameteri(TEXTURE_2D, channel, 0)
                    self.glTexParameteri(TEXTURE_2D, 0x8E45, 0x1903)
                self._check_gl(f"{kind} 풀 할당")
                self.gpu_storage_bytes += pool.bytes
            self.peak_gpu_storage_bytes = max(self.peak_gpu_storage_bytes, self.gpu_storage_bytes)

    @contextmanager
    def _upload_state(self):
        with self.binding.bound():
            unpack = (0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4)
            previous = tuple(self.binding.integer(key) for key in unpack)
            old_buffer = self.binding.integer(0x88EF)
            try:
                self.glBindBuffer(0x88EC, 0)
                for key, value in zip(unpack, (1, 0, 0, 0)):
                    self.glPixelStorei(key, value)
                yield
            finally:
                for key, value in zip(unpack, previous):
                    self.glPixelStorei(key, value)
                self.glBindBuffer(0x88EC, old_buffer)

    def page_handle(self, key):
        """카탈로그가 교체되거나 슬롯에서 빠져도 같은 페이지의 번호를 보존한다."""
        handle = self.page_handles.get(key)
        if handle is None:
            handle = len(self.resident)
            self.page_handles[key] = handle
            self.resident.append(None)
        return handle

    def _schedule(self, key, spec):
        work = TexturePageWork(spec, self.directory, timings=self.timings, archive=self.archive)
        self.jobs[key] = work, self.executor.submit(work.run), self.draw_serial

    def _upload(self, key, protected, *, speculative=False):
        kind = key[0]
        pool = self.pools[kind]
        if speculative and not pool.free:
            return False
        work, future, _ = self.jobs.pop(key)
        with self.timings.scope("parts.page_wait"):
            future.result()
            prepared = work.take_result()
        if prepared.codec != PAGE_CODECS[kind] or max(prepared.size) > pool.side:
            raise ValueError(f"파츠 페이지 형식 또는 크기 불일치: {prepared.key[0]}")
        if pool.free:
            index = pool.free.pop()
        else:
            old = next((candidate for candidate in pool.slots if candidate not in protected), None)
            if old is None:
                raise RuntimeError(f"동시에 필요한 {kind} 페이지가 풀의 슬롯 수를 초과한다.")
            index = pool.slots.pop(old)
            old_handle = self.entries.pop(old)
            self.resident_bytes -= self.resident[old_handle][2]
            self.resident[old_handle] = None
            self.prefetched.discard(old)
            self.evictions += 1
        try:
            with self.timings.scope("load.upload_submit"):
                self.binding.bind_texture(TEXTURE_2D, pool.texture.value)
                x, y = pool.position(index)
                pixel_bytes = ct.c_char_p(prepared.pixels)
                if prepared.compressed:
                    self.glCompressedTexSubImage2D(TEXTURE_2D, 0, x, y, *prepared.size, FORMATS[kind][0],
                                                   len(prepared.pixels), pixel_bytes)
                else:
                    self.glTexSubImage2D(TEXTURE_2D, 0, x, y, *prepared.size, FORMATS[kind][1], 0x1401, pixel_bytes)
                self._check_gl(f"{kind} 업로드")
        except BaseException:
            pool.free.append(index)
            raise
        size = len(prepared.pixels)
        pool.slots[key] = index
        handle = self.page_handles[key]
        self.entries[key] = handle
        self.resident[handle] = x, y, size
        self.resident_bytes += size
        self.peak_resident_bytes = max(self.peak_resident_bytes, self.resident_bytes)
        self.uploaded_bytes += size
        self.read_bytes += prepared.disk_bytes
        self.uploads += 1
        if speculative:
            self.prefetched.add(key)
            self.prefetch_uploads += 1
        return True

    def ensure(self, required, lookahead):
        self.draw_serial += 1
        missing = required.keys() - self.entries.keys()
        self.misses += len(missing)
        self.hits += len(required) - len(missing)
        self.draws_with_miss += bool(missing)
        for key in required.keys() & self.entries.keys():
            self.pools[key[0]].slots.move_to_end(key)
            if key in self.prefetched:
                self.prefetched.remove(key)
                self.prefetch_hits += 1
        for key, (work, future, last_use) in tuple(self.jobs.items()):
            if key in required or key in lookahead:
                self.jobs[key] = work, future, self.draw_serial
            elif self.draw_serial - last_use > 6 and (future.done() or future.cancel()):
                del self.jobs[key]
        for key in sorted(missing):
            if key not in self.jobs:
                self._schedule(key, required[key])
        ready = [key for key, (_, future, _) in self.jobs.items()
                 if key in lookahead and key not in required and self.pools[key[0]].free and future.done()][:2]
        if missing or ready or not self.gpu_storage_bytes:
            with self._upload_state():
                if not self.gpu_storage_bytes:
                    self._allocate()
                for key in sorted(missing):
                    self._upload(key, required)
                for key in ready:
                    self._upload(key, required, speculative=True)
        for key, spec in lookahead.items():
            if len(self.jobs) >= 24:
                break
            if key not in self.entries and key not in self.jobs:
                self._schedule(key, spec)

    def rect(self, resource, kind, frame):
        x, y, w, h = frame["rect"]
        page = frame["page"]
        if page < 0:
            return 0, 0, 0, 0
        handle, _, _ = resource["pages"][kind][page]
        slot = self.resident[handle]
        return (x + slot[0], y + slot[1], w, h) if slot is not None else (0, 0, 0, 0)

    def bindings(self, kinds):
        return [{"gl_texture": self.pools[kind].texture.value, "size": self.pools[kind].size} for kind in kinds]

    def report(self):
        return {"unique_textures": sum(bool(pool.texture.value) for pool in self.pools.values()),
                "resident_pages": len(self.entries), "cache_hits": self.hits, "cache_misses": self.misses,
                "cache_scope": "렌더 호출별 고유 필수 페이지 조회", "draws_with_page_miss": self.draws_with_miss,
                "gpu_storage_bytes": self.gpu_storage_bytes, "peak_gpu_storage_bytes": self.peak_gpu_storage_bytes,
                "resident_payload_bytes": self.resident_bytes, "peak_resident_payload_bytes": self.peak_resident_bytes,
                "uploaded_bytes": self.uploaded_bytes, "read_bytes_on_upload": self.read_bytes,
                "page_uploads": self.uploads, "page_evictions": self.evictions,
                "page_prefetch_uploads": self.prefetch_uploads, "page_prefetch_hits": self.prefetch_hits,
                "pool_slots": {kind: pool.capacity for kind, pool in self.pools.items()}}

    def clear(self):
        for _, future, _ in self.jobs.values():
            future.cancel()
        self.jobs.clear()
        for pool in self.pools.values():
            if pool.texture.value:
                self.glDeleteTextures(1, ct.byref(pool.texture))
                pool.texture.value = 0
            pool.slots.clear()
            pool.free[:] = range(pool.capacity - 1, -1, -1)
        for handle in self.entries.values():
            self.resident[handle] = None
        self.entries.clear()
        self.prefetched.clear()
        self.gpu_storage_bytes = self.resident_bytes = 0

    def close(self):
        self.clear()
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.archive.close()
        self.page_handles.clear()
        self.resident.clear()
