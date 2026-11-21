"""깊이 패스의 양쪽 키 샘플 좌표를 GPU에서 재질 패스로 전달한다."""

from contextlib import contextmanager
import ctypes as ct

from ferrial_drive.diagnostics.gpu_profile import bind_gl


SHADER_STORAGE_BUFFER = 0x90D2
SHADER_STORAGE_BUFFER_BINDING = 0x90D3
KEYPOSE_SAMPLE_BINDING = 7
SAMPLE_BYTES = 16
ALLOCATION_PAGE_BYTES = 256 * 1024


class KeyposeSampleBuffer:
    def __init__(self, pico):
        self.buffer = ct.c_uint()
        self.storage_bytes = 0
        u, i, p, size = ct.c_uint, ct.c_int, ct.c_void_p, ct.c_ssize_t
        for name, args in (
            ("glGenBuffers", [i, p]), ("glDeleteBuffers", [i, p]),
            ("glBindBuffer", [u, u]), ("glBindBufferBase", [u, u, u]),
            ("glBindBufferRange", [u, u, u, size, size]), ("glBufferData", [u, size, p, u]),
            ("glGetIntegeri_v", [u, u, p]), ("glGetInteger64i_v", [u, u, p]),
            ("glGetInteger64v", [u, p]), ("glMemoryBarrier", [u]),
        ):
            setattr(self, name, bind_gl(pico, name, None, args))
        limit = ct.c_int64()
        self.glGetInteger64v(0x90DE, ct.byref(limit))  # GL_MAX_SHADER_STORAGE_BLOCK_SIZE
        self.limit_bytes = limit.value
        # 인스턴스의 float 슬롯에 저장하는 시작 인덱스에는 정확한 정수가 필요하다.
        self.sample_limit = min(self.limit_bytes // SAMPLE_BYTES, (1 << 24) - 2)

    @contextmanager
    def bind(self, sampler, sample_count):
        target, slot = SHADER_STORAGE_BUFFER, KEYPOSE_SAMPLE_BINDING
        generic = sampler.integer(SHADER_STORAGE_BUFFER_BINDING)
        indexed, offset, size = ct.c_int(), ct.c_int64(), ct.c_int64()
        self.glGetIntegeri_v(SHADER_STORAGE_BUFFER_BINDING, slot, ct.byref(indexed))
        if indexed.value:
            self.glGetInteger64i_v(0x90D4, slot, ct.byref(offset))  # GL_SHADER_STORAGE_BUFFER_START
            self.glGetInteger64i_v(0x90D5, slot, ct.byref(size))  # GL_SHADER_STORAGE_BUFFER_SIZE
        try:
            if not self.buffer.value:
                self.glGenBuffers(1, ct.byref(self.buffer))
            requested = max(SAMPLE_BYTES, sample_count * SAMPLE_BYTES)
            if requested > self.storage_bytes:
                capacity = min(self.limit_bytes, (requested + ALLOCATION_PAGE_BYTES - 1)
                               // ALLOCATION_PAGE_BYTES * ALLOCATION_PAGE_BYTES) if sample_count else requested
                self.glBindBuffer(target, self.buffer.value)
                self.glBufferData(target, capacity, None, 0x88EA)  # GL_DYNAMIC_COPY
                self.storage_bytes = capacity
            self.glBindBufferBase(target, slot, self.buffer.value)
            yield
        finally:
            if indexed.value and size.value:
                self.glBindBufferRange(target, slot, indexed.value, offset.value, size.value)
            else:
                self.glBindBufferBase(target, slot, indexed.value)
            self.glBindBuffer(target, generic)

    def sync(self):
        self.glMemoryBarrier(0x2000)  # GL_SHADER_STORAGE_BARRIER_BIT

    def close(self):
        if self.buffer.value:
            self.glDeleteBuffers(1, ct.byref(self.buffer))
            self.buffer.value = 0
        self.storage_bytes = 0
