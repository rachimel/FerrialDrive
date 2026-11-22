"""크기와 형식이 같은 SMAA 중간 타깃을 하나의 배열에 보관한다."""

import ctypes as ct

from ferrial_drive.diagnostics.gpu_profile import bind_gl


TEXTURE_2D = 0x0DE1
TEXTURE_2D_ARRAY = 0x8C1A
RGBA8 = 0x8058


class SmaaSheetLayers:
    def __init__(self, pico):
        version = bind_gl(pico, "glGetString", ct.c_char_p, [ct.c_uint])(0x1F02)
        if not version or tuple(map(int, version.split()[0].split(b".")[:2])) < (4, 3):
            raise RuntimeError("SMAA 시트 배열에는 OpenGL 4.3이 필요하다.")
        self.size = (0, 0)
        self.keys = ()
        self.names = (ct.c_uint * 4)()
        u, i, ptr = ct.c_uint, ct.c_int, ct.c_void_p
        self.generate = bind_gl(pico, "glGenTextures", None, [i, ptr])
        self.delete = bind_gl(pico, "glDeleteTextures", None, [i, ptr])
        self.storage = bind_gl(pico, "glTexStorage3D", None, [u, i, u, i, i, i])
        self.view = bind_gl(pico, "glTextureView", None, [u] * 8)
        self.parameter = bind_gl(pico, "glTexParameteri", None, [u, u, i])

    def reserve(self, sampler, size):
        size = tuple(max(a, b) for a, b in zip(self.size, size))
        if size == self.size:
            return
        previous_2d = sampler.integer(0x8069)
        previous_array = sampler.integer(0x8C1D)
        names = (ct.c_uint * 4)()
        self.generate(len(names), names)
        try:
            if not all(names):
                raise RuntimeError("SMAA 타깃 텍스처 배열을 만들 수 없다.")
            sampler.glBindTexture(TEXTURE_2D_ARRAY, names[0])
            self.storage(TEXTURE_2D_ARRAY, 1, RGBA8, *size, 3)
            for layer, name in enumerate(names[1:]):
                self.view(name, TEXTURE_2D, names[0], RGBA8, 0, 1, layer, 1)
                sampler.glBindTexture(TEXTURE_2D, name)
                for attribute, value in ((0x2801, 0x2601), (0x2800, 0x2601), (0x2802, 0x812F), (0x2803, 0x812F)):
                    self.parameter(TEXTURE_2D, attribute, value)
        except BaseException:
            self.delete(len(names), names)
            raise
        finally:
            sampler.glBindTexture(TEXTURE_2D, previous_2d)
            sampler.glBindTexture(TEXTURE_2D_ARRAY, previous_array)
        self.close()
        self.size, self.names = size, names
        self.keys = tuple(object() for _ in range(3))

    def close(self):
        if self.names[0]:
            self.delete(len(self.names), self.names)
            self.names = (ct.c_uint * 4)()
        self.size = (0, 0)
        self.keys = ()
