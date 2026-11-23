"""선적재하는 PBR 모션의 방향 페이지 배열과 저장 예산."""

from collections import defaultdict
import ctypes as ct
from dataclasses import dataclass

from ferrial_drive.diagnostics.texture_metrics import bind_gl

from .texture_codecs import texture_payload_size


TEXTURE_ARRAY = 0x8C1A
TEXTURE_BINDING_ARRAY = 0x8C1D
TEXTURE_2D = 0x0DE1
FILTER_PARAMETERS = ((0x2801, 0x2601), (0x2800, 0x2601), (0x2802, 0x812F), (0x2803, 0x812F))


class DirectionArrayUploadError(RuntimeError):
    pass


@dataclass
class DirectionArray:
    size: tuple
    layers: int
    layer_bytes: int
    group: object
    binding: dict | None = None
    live_pages: int = 0

    @property
    def storage_bytes(self):
        return self.layers * self.layer_bytes


def plan_direction_arrays(resources, pending, headroom_bytes, max_layers, max_size):
    """한 모션의 모든 채널을 함께 선택하고 배열 패딩을 예산에 포함한다."""
    by_motion = defaultdict(list)
    for (motion, _), resource in resources.items():
        by_motion[motion].append(resource["pages"])
    plan = {}
    for banks in by_motion.values():
        if len(banks) < 2 or len(banks) > max_layers:
            continue
        group, candidate, padding = object(), {}, 0
        for kind in banks[0]:
            keys = tuple(dict.fromkeys(bank[kind] for bank in banks))
            if any(key not in pending or key in plan or key in candidate for key in keys):
                break
            pages = [pending[key] for key in keys]
            codec = pages[0]["codec"]
            if any(page["codec"] != codec for page in pages):
                break
            size = tuple(max(page[axis] for page in pages) for axis in ("width", "height"))
            if codec in ("bc7_zlib", "ktx2_uastc"):
                size = tuple((value + 3) // 4 * 4 for value in size)
            if max(size) > max_size:
                break
            array = DirectionArray(size, len(pages), texture_payload_size(codec, *size), group)
            padding += array.storage_bytes - sum(texture_payload_size(codec, page["width"], page["height"])
                                                  for page in pages)
            candidate.update((key, (array, layer)) for layer, key in enumerate(keys))
        else:
            if padding <= headroom_bytes:
                plan.update(candidate)
                headroom_bytes -= padding
    return plan


class DirectionArrayStorage:
    def __init__(self, cache):
        p = cache.pico
        u, i = ct.c_uint, ct.c_int
        version = bind_gl(p, "glGetString", ct.c_char_p, [u])(0x1F02)
        if not version or tuple(map(int, version.split()[0].split(b".")[:2])) < (4, 3):
            raise RuntimeError("방향 배열의 2D 뷰에는 OpenGL 4.3이 필요하다.")
        self.cache = cache
        self.max_layers = cache.binding.integer(0x88FF)
        self.max_size = cache.binding.integer(0x0D33)
        self.storage = bind_gl(p, "glTexStorage3D", None, [u, i, u, i, i, i])
        self.view = bind_gl(p, "glTextureView", None, [u] * 8)

    def _allocate(self, array, internal, codec):
        cache = self.cache
        binding = cache.binding
        previous = binding.integer(TEXTURE_BINDING_ARRAY)
        texture = ct.c_uint()
        cache.gen_texture(1, ct.byref(texture))
        try:
            if not texture.value:
                raise RuntimeError("방향 배열 텍스처를 만들 수 없다.")
            binding.bind_texture(TEXTURE_ARRAY, texture.value)
            self.storage(TEXTURE_ARRAY, 1, internal, *array.size, array.layers)
            self._parameters(TEXTURE_ARRAY, codec)
            if error := cache.get_error():
                raise RuntimeError(f"방향 배열 저장소 할당 실패: GL {error:#x}")
        except BaseException:
            cache.delete_texture(1, ct.byref(texture))
            raise
        finally:
            binding.bind_texture(TEXTURE_ARRAY, previous)
        array.binding = {"gl_texture": texture.value, "gl_target": TEXTURE_ARRAY,
                         "gl_binding": TEXTURE_BINDING_ARRAY, "size": array.size}

    def _parameters(self, target, codec):
        for parameter, value in FILTER_PARAMETERS:
            self.cache.parameter(target, parameter, value)
        if codec == "a8_zlib":
            for parameter, value in ((0x8E42, 0), (0x8E43, 0), (0x8E44, 0), (0x8E45, 0x1903)):
                self.cache.parameter(target, parameter, value)

    def upload(self, array, layer, page, payload, compressed, internal):
        cache = self.cache
        texture = ct.c_uint()
        new = array.binding is None
        try:
            if new:
                cache._trim_pool(array.storage_bytes)
            with cache.binding.bound():
                if new:
                    self._allocate(array, internal, page["codec"])
                cache.gen_texture(1, ct.byref(texture))
                if not texture.value:
                    raise RuntimeError("방향 배열의 2D 뷰를 만들 수 없다.")
                self.view(texture.value, TEXTURE_2D, array.binding["gl_texture"], internal, 0, 1, layer, 1)
                cache.binding.bind_texture(TEXTURE_2D, texture.value)
                self._parameters(TEXTURE_2D, page["codec"])
                cache._upload_gl(page, ct.c_char_p(payload), len(payload), compressed=compressed, subimage=True)
                gpu = cache._texture_info(dict(page, width=array.size[0], height=array.size[1]), compressed)
        except BaseException:
            cache.delete_texture(1, ct.byref(texture))
            if new:
                self.delete(array)
            raise
        return {"gl_texture": texture.value, "gpu": gpu, "storage_size": array.size,
                "direction_array": array, "array_layer": layer}, new

    def delete(self, array):
        if array.binding is not None:
            self.cache.delete_texture(1, ct.byref(ct.c_uint(array.binding["gl_texture"])))
            array.binding = None
