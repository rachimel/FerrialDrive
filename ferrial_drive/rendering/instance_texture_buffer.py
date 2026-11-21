"""인스턴스 레코드를 한 번 전송하고 버텍스 셰이더에서 재사용한다."""

import ctypes as ct

from ferrial_drive.diagnostics.gpu_profile import bind_gl


TEXTURE_BUFFER = 0x8C2A
TEXTURE_BINDING_BUFFER = 0x8C2C
ARRAY_BUFFER = 0x8892
ARRAY_BUFFER_BINDING = 0x8894


class InstanceTextureBuffer:
    def __init__(self, pico):
        self.buffer, self.texture = ct.c_uint(), ct.c_uint()
        self.storage_bytes = 0
        u, i, p = ct.c_uint, ct.c_int, ct.c_void_p
        for name, args in (
            ("glGenBuffers", [i, p]), ("glDeleteBuffers", [i, p]),
            ("glGenTextures", [i, p]), ("glDeleteTextures", [i, p]),
            ("glBindBuffer", [u, u]), ("glBufferData", [u, ct.c_ssize_t, p, u]), ("glTexBuffer", [u, u, u]),
        ):
            setattr(self, name, bind_gl(pico, name, None, args))

    def upload(self, sampler, values):
        data = (ct.c_float * len(values))(*values)
        size = ct.sizeof(data)
        previous = sampler.integer(ARRAY_BUFFER_BINDING)
        create = not self.buffer.value
        if create:
            self.glGenBuffers(1, ct.byref(self.buffer))
        try:
            self.glBindBuffer(ARRAY_BUFFER, self.buffer.value)
            self.glBufferData(ARRAY_BUFFER, size, data, 0x88E0)  # GL_STREAM_DRAW
            if create:
                texture = sampler.integer(TEXTURE_BINDING_BUFFER)
                try:
                    self.glGenTextures(1, ct.byref(self.texture))
                    sampler.glBindTexture(TEXTURE_BUFFER, self.texture.value)
                    self.glTexBuffer(TEXTURE_BUFFER, 0x8814, self.buffer.value)  # GL_RGBA32F
                finally:
                    sampler.glBindTexture(TEXTURE_BUFFER, texture)
        finally:
            self.glBindBuffer(ARRAY_BUFFER, previous)
        self.storage_bytes = size

    def close(self):
        if self.texture.value:
            self.glDeleteTextures(1, ct.byref(self.texture))
            self.texture.value = 0
        if self.buffer.value:
            self.glDeleteBuffers(1, ct.byref(self.buffer))
            self.buffer.value = 0
        self.storage_bytes = 0
