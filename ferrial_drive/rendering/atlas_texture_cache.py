"""Pico2D/OpenGL 아틀라스 텍스처 적재와 페이지 공유."""

from contextlib import contextmanager
import ctypes as ct
from pathlib import Path
from threading import get_ident

from ferrial_drive.diagnostics import TimingRecorder
from ferrial_drive.diagnostics.texture_metrics import bind_gl

from .texture_codecs import bc7_size, texture_payload_size
from .texture_page_work import TexturePageWork


class TextureUploadBinding:
    """텍스처 적재에 필요한 SDL 큐와 GL 바인딩 상태만 다룬다."""

    def __init__(self, pico):
        self.pico = pico
        self.get_integer = bind_gl(pico, "glGetIntegerv", None, [ct.c_uint, ct.c_void_p])
        self.active_texture = bind_gl(pico, "glActiveTexture", None, [ct.c_uint])
        self.bind_texture = bind_gl(pico, "glBindTexture", None, [ct.c_uint, ct.c_uint])

    def integer(self, name):
        value = ct.c_int()
        self.get_integer(name, ct.byref(value))
        return value.value

    @contextmanager
    def bound(self):
        self.pico.SDL_RenderFlush(self.pico.renderer)
        active = self.integer(0x84E0)
        self.active_texture(0x84C0)
        previous = self.integer(0x8069)
        try:
            yield
        finally:
            self.bind_texture(0x0DE1, previous)
            self.active_texture(active)


COMPACT_TEXTURE_FORMATS = {"a8_zlib": (0x8229, 0x1903), "rg8_zlib": (0x822B, 0x8227),
                           "rgb8_zlib": (0x8051, 0x1907)}
MAX_POOLED_STORAGE_BYTES = 8 * 1024**2
MAX_POOLED_TEXTURES = 32


class AtlasTextureCache:
    """명시적인 렌더러 수명의 캐시. 같은 파일은 후보·클립·인스턴스가 함께 사용한다."""

    def __init__(self, pico, *, timings=None, ktx_library=None, synchronize_upload=True):
        self.pico = pico
        self.binding = TextureUploadBinding(pico)
        self.timings = timings or TimingRecorder(enabled=False)
        self.ktx_library = ktx_library
        self.owner_thread_id = get_ident()
        self.entries, self.hits = {}, 0
        self.gpu_storage_bytes = 0
        self.peak_gpu_storage_bytes = self.uploads = self.uploaded_bytes = self.read_bytes = 0
        self.pool = []
        self.pool_enabled = False
        self.storage_budget_bytes = None
        self.pooled_bytes = self.pool_hits = self.texture_allocations = self.peak_allocated_bytes = 0
        self.synchronize_upload = synchronize_upload
        self.finish = bind_gl(pico, "glFinish", None, [])
        self.compressed_upload = bind_gl(pico, "glCompressedTexImage2D", None,
                                         [ct.c_uint, ct.c_int, ct.c_uint, ct.c_int, ct.c_int,
                                          ct.c_int, ct.c_int, ct.c_void_p])
        self.compressed_update = bind_gl(pico, "glCompressedTexSubImage2D", None,
                                         [ct.c_uint, ct.c_int, ct.c_int, ct.c_int, ct.c_int, ct.c_int,
                                          ct.c_uint, ct.c_int, ct.c_void_p])
        self.query_level = bind_gl(pico, "glGetTexLevelParameteriv", None,
                                   [ct.c_uint, ct.c_int, ct.c_uint, ct.c_void_p])
        self.get_error = bind_gl(pico, "glGetError", ct.c_uint, [])
        self.upload_raw = bind_gl(pico, "glTexImage2D", None,
            [ct.c_uint,ct.c_int,ct.c_int,ct.c_int,ct.c_int,ct.c_int,ct.c_uint,ct.c_uint,ct.c_void_p])
        self.update_raw = bind_gl(pico, "glTexSubImage2D", None,
            [ct.c_uint, ct.c_int, ct.c_int, ct.c_int, ct.c_int, ct.c_int, ct.c_uint, ct.c_uint, ct.c_void_p])
        self.parameter = bind_gl(pico, "glTexParameteri", None, [ct.c_uint,ct.c_uint,ct.c_int])
        self.pixel_store = bind_gl(pico, "glPixelStorei", None, [ct.c_uint,ct.c_int])
        self.bind_buffer = bind_gl(pico, "glBindBuffer", None, [ct.c_uint,ct.c_uint])

        self.gen_texture = bind_gl(pico, "glGenTextures", None, [ct.c_int, ct.c_void_p])
        self.delete_texture = bind_gl(pico, "glDeleteTextures", None, [ct.c_int, ct.c_void_p])
    @contextmanager
    def _unpack(self):
        keys = (0x0CF5,0x0CF2,0x0CF3,0x0CF4)
        old_unpack = tuple(self.binding.integer(key) for key in keys)
        old_buffer = self.binding.integer(0x88EF)
        try:
            self.bind_buffer(0x88EC,0)
            for key,value in zip(keys,(1,0,0,0)):
                self.pixel_store(key,value)
            yield
        finally:
            for key,value in zip(keys,old_unpack):
                self.pixel_store(key,value)
            self.bind_buffer(0x88EC,old_buffer)

    def _upload_gl(self, page, buffer, size, *, compressed, subimage):
        width, height = page["width"], page["height"]
        with self._unpack():
            if compressed:
                if subimage:
                    block_width, block_height = ((n + 3) // 4 * 4 for n in (width, height))
                    self.compressed_update(0x0DE1, 0, 0, 0, block_width, block_height, 0x8E8C, size, buffer)
                else:
                    self.compressed_upload(0x0DE1, 0, 0x8E8C, width, height, 0, size, buffer)
            else:
                internal, pixel = COMPACT_TEXTURE_FORMATS.get(page["codec"], (0x8058, 0x1908))
                if subimage:
                    self.update_raw(0x0DE1, 0, 0, 0, width, height, pixel, 0x1401, buffer)
                else:
                    self.upload_raw(0x0DE1, 0, internal, width, height, 0, pixel, 0x1401, buffer)
                    self._set_alpha_swizzle(page["codec"])
            error = self.get_error()
            if error:
                raise RuntimeError(f"아틀라스 업로드 실패 ({page['codec']}): GL {error:#x}")

    def _set_alpha_swizzle(self, codec):
        if codec == "a8_zlib":
            for channel in (0x8E42, 0x8E43, 0x8E44):
                self.parameter(0x0DE1, channel, 0)
            self.parameter(0x0DE1, 0x8E45, 0x1903)

    @staticmethod
    def page_key(page, directory):
        return ((Path(directory) / page["file"]).resolve(), page["sha256"])

    def _assert_owner(self):
        if get_ident() != self.owner_thread_id:
            raise RuntimeError("GPU 텍스처는 렌더러를 생성한 스레드에서만 적재·해제한다.")

    def configure_pool(self, storage_budget_bytes):
        self._assert_owner()
        if not self.pool_enabled:
            self.allocate_storage = bind_gl(self.pico, "glTexStorage2D", None,
                                            [ct.c_uint, ct.c_int, ct.c_uint, ct.c_int, ct.c_int])
        self.pool_enabled = True
        self.storage_budget_bytes = storage_budget_bytes
        self._trim_pool()

    def _delete_pooled(self, index):
        entry = self.pool.pop(index)
        self.pooled_bytes -= entry["gpu"]["storage_bytes"]
        self.delete_texture(1, ct.byref(ct.c_uint(entry["gl_texture"])))

    def _trim_pool(self, incoming_bytes=0):
        limit = MAX_POOLED_STORAGE_BYTES
        if self.storage_budget_bytes is not None:
            limit = min(limit, max(0, self.storage_budget_bytes - self.gpu_storage_bytes - incoming_bytes))
        while self.pool and (self.pooled_bytes > limit or len(self.pool) > MAX_POOLED_TEXTURES):
            self._delete_pooled(0)

    def purge_pool(self):
        self._assert_owner()
        while self.pool:
            self._delete_pooled(-1)

    def _storage_size(self, page):
        size = page["width"], page["height"]
        if self.pool_enabled and page["codec"] in ("bc7_zlib", "ktx2_uastc"):
            size = tuple((value + 3) // 4 * 4 for value in size)
        return size

    def storage_bytes_for(self, page):
        return texture_payload_size(page["codec"], *self._storage_size(page))

    def _take_pooled(self, codec, size, storage):
        # 작은 페이지로 큰 저장소를 붙잡아 두거나 활성 페이지 예산을 넘기지 않는다.
        limit = storage + storage // 8
        if self.storage_budget_bytes is not None:
            limit = min(limit, self.storage_budget_bytes - self.gpu_storage_bytes)
        best = None
        for index in range(len(self.pool) - 1, -1, -1):
            entry = self.pool[index]
            width, height = entry["storage_size"]
            cost = entry["gpu"]["storage_bytes"]
            if entry["codec"] == codec and width >= size[0] and height >= size[1] and cost <= limit:
                best, limit = index, cost - 1
                if cost == storage:
                    break
        if best is None:
            return None
        entry = self.pool.pop(best)
        self.pooled_bytes -= entry["gpu"]["storage_bytes"]
        return entry

    def _upload_pooled(self, page, payload, compressed):
        codec, size = page["codec"], self._storage_size(page)
        storage = self.storage_bytes_for(page)
        reused = self._take_pooled(codec, size, storage)
        if reused:
            size, storage = reused["storage_size"], reused["gpu"]["storage_bytes"]
        texture = ct.c_uint(reused["gl_texture"] if reused else 0)
        try:
            self._trim_pool(storage)
            with self.binding.bound():
                if not reused:
                    self.gen_texture(1, ct.byref(texture))
                    if not texture.value:
                        raise RuntimeError("아틀라스 풀 텍스처 이름 생성 실패")
                self.binding.bind_texture(0x0DE1, texture.value)
                if not reused:
                    internal = 0x8E8C if compressed else COMPACT_TEXTURE_FORMATS.get(codec, (0x8058, 0))[0]
                    self.allocate_storage(0x0DE1, 1, internal, *size)
                    for param, value in ((0x2801, 0x2601), (0x2800, 0x2601), (0x2802, 0x812F), (0x2803, 0x812F)):
                        self.parameter(0x0DE1, param, value)
                    self._set_alpha_swizzle(codec)
                self._upload_gl(page, ct.c_char_p(payload), len(payload), compressed=compressed, subimage=True)
                gpu = reused["gpu"] if reused else self._texture_info(dict(page, width=size[0], height=size[1]), compressed)
            return {"gl_texture": texture.value, "storage_size": size, "gpu": gpu}, reused is not None
        except BaseException:
            if texture.value:
                self.delete_texture(1, ct.byref(texture))
            raise

    def _upload_sdl(self, page, payload, compressed):
        p = self.pico
        width, height = page["width"], page["height"]
        texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32,
                                     p.SDL_TEXTUREACCESS_STATIC, width, height)
        if not texture:
            raise RuntimeError("아틀라스 텍스처 생성 실패")
        try:
            buffer = ct.c_char_p(payload)
            compact = page["codec"] in COMPACT_TEXTURE_FORMATS
            if not compressed and not compact and p.SDL_UpdateTexture(texture, None, buffer, width * 4):
                raise RuntimeError("RGBA 아틀라스 전송 실패")
            p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear)
            p.SDL_SetTextureBlendMode(texture, p.SDL_BLENDMODE_NONE)
            with self.binding.bound():
                self._bind(texture)
                if compressed or compact:
                    self._upload_gl(page, buffer, len(payload), compressed=compressed, subimage=False)
                gpu = self._texture_info(page, compressed)
                gl_name = self.binding.integer(0x8069)
            return {"texture": texture, "gl_name": gl_name, "gpu": gpu}, False
        except BaseException:
            p.SDL_DestroyTexture(texture)
            raise

    def acquire(self, page, directory, *, prepared=None):
        self._assert_owner()
        path = (Path(directory) / page["file"]).resolve()
        key = (path, page["sha256"])
        if key in self.entries:
            self.hits += 1
            self.entries[key]["references"] += 1
            return key, self.entries[key]
        width, height = page["width"], page["height"]
        if min(width, height) < 1 or max(width, height) > self.binding.integer(0x0D33):
            raise ValueError("GPU 페이지 크기 제한을 초과했다.")
        if prepared is None:
            work = TexturePageWork(page, directory, timings=self.timings, ktx_library=self.ktx_library)
            work.run()
            prepared = work.take_result()
        if prepared.key != key or prepared.size != (width, height) or prepared.codec != page["codec"]:
            raise ValueError("준비된 페이지와 GPU 적재 요청이 다르다.")
        # 같은 컨텍스트에서는 업로드 뒤에 드로우를 제출한다.
        if self.synchronize_upload:
            self.finish()
        scope = "load.upload_complete" if self.synchronize_upload else "load.upload_submit"
        with self.timings.scope(scope):
            upload = self._upload_pooled if self.pool_enabled else self._upload_sdl
            entry, reused = upload(page, prepared.pixels, prepared.compressed)
            if self.synchronize_upload:
                self.finish()
        entry.update(size=(width, height), references=1, disk_bytes=prepared.disk_bytes, codec=page["codec"])
        self.entries[key] = entry
        self.gpu_storage_bytes += entry["gpu"]["storage_bytes"]
        self.peak_gpu_storage_bytes = max(self.peak_gpu_storage_bytes, self.gpu_storage_bytes)
        self.peak_allocated_bytes = max(self.peak_allocated_bytes, self.gpu_storage_bytes + self.pooled_bytes)
        self.pool_hits += int(reused)
        self.texture_allocations += int(not reused)
        self.uploads += 1
        self.uploaded_bytes += len(prepared.pixels)
        self.read_bytes += prepared.disk_bytes
        return key, entry

    def _texture_info(self, page, compressed):
        values = {}
        for name, enum in (("internal_format", 0x1003), ("compressed", 0x86A1),
                            ("width", 0x1000), ("height", 0x1001)):
            value = ct.c_int()
            self.query_level(0x0DE1, 0, enum, ct.byref(value))
            values[name] = value.value
        if compressed:
            storage = ct.c_int()
            self.query_level(0x0DE1, 0, 0x86A0, ct.byref(storage))
            if not values["compressed"] or values["internal_format"] != 0x8E8C or storage.value != bc7_size(page["width"], page["height"]):
                raise RuntimeError("실제 GPU 저장 형식이 예상 BC7과 다르다.")
            values["storage_bytes"] = storage.value
        else:
            compact_format = COMPACT_TEXTURE_FORMATS.get(page["codec"])
            if compact_format and values["internal_format"] != compact_format[0]:
                raise RuntimeError("단축 채널 텍스처의 실제 GL 저장 형식이 다르다.")
            values["storage_bytes"] = texture_payload_size(page["codec"], page["width"], page["height"])
            values["storage_semantics"] = "GL 저장 형식의 논리 페이로드. 드라이버 정렬·물리 할당량과 다르다."
        return values

    def _bind(self, texture):
        w, h = ct.c_float(), ct.c_float()
        if self.pico.SDL_GL_BindTexture(texture, ct.byref(w), ct.byref(h)):
            raise RuntimeError("SDL/OpenGL 아틀라스 연결 실패")

    def release(self, key):
        self._assert_owner()
        entry = self.entries[key]
        entry["references"] -= 1
        if not entry["references"]:
            del self.entries[key]
            self.gpu_storage_bytes -= entry["gpu"]["storage_bytes"]
            if "gl_texture" in entry:
                self.pool.append(entry)
                self.pooled_bytes += entry["gpu"]["storage_bytes"]
                self._trim_pool()
            else:
                self.pico.SDL_DestroyTexture(entry["texture"])

    def report(self):
        return {"unique_textures": len(self.entries), "cache_hits": self.hits,
                "gpu_storage_bytes": self.gpu_storage_bytes,
                "peak_gpu_storage_bytes": self.peak_gpu_storage_bytes, "cache_misses": self.uploads,
                "cache_scope": "아틀라스 리소스 acquire 호출",
                "uploaded_bytes": self.uploaded_bytes, "read_bytes_on_upload": self.read_bytes,
                "pooled_textures": len(self.pool), "pooled_gpu_bytes": self.pooled_bytes,
                "gpu_allocated_bytes": self.gpu_storage_bytes + self.pooled_bytes,
                "peak_gpu_allocated_bytes": self.peak_allocated_bytes,
                "pool_hits": self.pool_hits, "texture_allocations": self.texture_allocations,
                "textures": [dict(path=str(key[0]), codec=row["codec"], **row["gpu"]) for key, row in self.entries.items()]}


class AtlasTextureBindings:
    """활성 유닛 0에서 시작하는 같은 GL 패스 안의 2D/버퍼 바인딩을 추적한다."""

    def __init__(self, sampler):
        self.sampler = sampler
        self.previous = {}
        self.current = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.restore()

    def apply(self, entries, names):
        s = self.sampler
        active = 0
        try:
            for unit, (entry, name) in enumerate(zip(entries, names, strict=True)):
                target = entry.get("gl_target", 0x0DE1)
                key = unit, target
                if key in self.current and self.current[key] == name:
                    continue
                if unit != active:
                    s.glActiveTexture(0x84C0 + unit)
                    active = unit
                if key not in self.previous:
                    self.previous[key] = s.integer(entry.get("gl_binding", 0x8069))
                if self.current.get(key, self.previous[key]) != name:
                    s.glBindTexture(target, name)
                self.current[key] = name
        finally:
            if active:
                s.glActiveTexture(0x84C0)

    def restore(self):
        s = self.sampler
        active = 0
        for (unit, target), name in self.previous.items():
            if self.current.get((unit, target)) == name:
                continue
            if unit != active:
                s.glActiveTexture(0x84C0 + unit)
                active = unit
            s.glBindTexture(target, name)
        if active:
            s.glActiveTexture(0x84C0)
        self.previous.clear()
        self.current.clear()


@contextmanager
def bind_atlas_textures(sampler, cache, entries, bindings=None):
    if bindings is not None:
        names = [entry.get("gl_texture", entry.get("gl_name")) for entry in entries]
        if None not in names:
            bindings.apply(entries, names)
            yield
            return
        bindings.restore()
    s, previous = sampler, []
    try:
        for unit, entry in enumerate(entries):
            s.glActiveTexture(0x84C0 + unit)
            target = entry.get("gl_target", 0x0DE1)
            previous.append((target, s.integer(entry.get("gl_binding", 0x8069))))
            if "gl_texture" in entry:
                s.glBindTexture(target, entry["gl_texture"])
            else:
                cache._bind(entry["texture"])
        s.glActiveTexture(0x84C0)
        yield
    finally:
        for unit, (target, texture) in enumerate(previous):
            s.glActiveTexture(0x84C0 + unit)
            s.glBindTexture(target, texture)
        s.glActiveTexture(0x84C0)
