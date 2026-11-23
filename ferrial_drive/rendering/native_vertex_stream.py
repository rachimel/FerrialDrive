"""직접 OpenGL의 연속 제출 구간을 한 버퍼 범위에 올린다."""

import ctypes as ct

from ferrial_drive.diagnostics.gpu_profile import bind_gl


ARRAY_BUFFER = 0x8892
ELEMENT_BUFFER = 0x8893
STAGING_BYTES = 512 * 1024
BUFFER_BYTES = 2 * 1024**2
STREAM_DRAW = 0x88E0
PRIMITIVE_VERTICES = {0x0000: 1, 0x0001: 2, 0x0004: 3, 0x0007: 4}


class NativeVertexStream:
    def __init__(self, renderer, stride):
        self.renderer = renderer
        self.stride = stride
        self.buffer = ct.c_uint()
        self.staging = (ct.c_ubyte * STAGING_BYTES)()
        self.start = ct.addressof(self.staging)
        self.commands = []
        self.used = 0
        self.next_offset = BUFFER_BYTES
        u, i, size, ptr = ct.c_uint, ct.c_int, ct.c_ssize_t, ct.c_void_p
        for method, parameters in {
            "GenBuffers": [i, ptr], "DeleteBuffers": [i, ptr], "BufferData": [u, size, ptr, u],
            "BufferSubData": [u, size, size, ptr], "DrawElementsBaseVertex": [u, i, u, ptr, i],
        }.items():
            setattr(self, method, bind_gl(renderer.pico, "gl" + method, None, parameters))

    def append(self, vertices, count, mode, blend, texture, indices, index_count):
        stride = self.stride
        vertex_bytes = count * stride
        index_bytes = index_count * ct.sizeof(ct.c_uint) if indices else 0
        size = vertex_bytes + index_bytes
        if size > STAGING_BYTES:
            self.submit()
            return False
        start = (self.used + stride - 1) // stride * stride
        if start + size > STAGING_BYTES:
            self.submit()
            start = 0
        ct.memmove(self.start + start, vertices, vertex_bytes)
        index_offset = start + vertex_bytes
        if index_bytes:
            ct.memmove(self.start + index_offset, indices, index_bytes)
        self.used = start + size
        first = start // stride
        primitive = PRIMITIVE_VERTICES.get(mode)
        if not index_bytes and primitive and count % primitive == 0 and self.commands:
            previous_mode, previous_blend, previous_texture, base, previous_count, _, previous_indices = self.commands[-1]
            if (not previous_indices and previous_count % primitive == 0 and base + previous_count == first
                    and (previous_mode, previous_blend, previous_texture) == (mode, blend, texture)):
                self.commands[-1] = mode, blend, texture, base, previous_count + count, 0, 0
                return True
        self.commands.append((mode, blend, texture, first, count, index_offset, index_count if index_bytes else 0))
        return True

    def submit(self):
        if not self.commands:
            return
        renderer = self.renderer
        renderer._prepare_draw()
        if not self.buffer.value:
            self.GenBuffers(1, ct.byref(self.buffer))
        renderer.BindBuffer(ARRAY_BUFFER, self.buffer.value)
        renderer.BindBuffer(ELEMENT_BUFFER, self.buffer.value)
        try:
            offset = self.next_offset
            if offset + self.used > BUFFER_BYTES:
                # GPU가 참조 중인 저장소는 드라이버가 보유하고 다음 그룹은 새 저장소에 쓴다.
                self.BufferData(ARRAY_BUFFER, BUFFER_BYTES, None, STREAM_DRAW)
                offset = 0
            self.BufferSubData(ARRAY_BUFFER, offset, self.used, self.staging)
            self.next_offset = (offset + self.used + 3) & ~3
            renderer.VertexPointer(2, 0x1406, self.stride, offset)
            renderer.ColorPointer(4, 0x1401, self.stride, offset + 8)
            renderer.TexCoordPointer(2, 0x1406, self.stride, offset + 12)
            for mode, blend, texture, first, count, index_offset, index_count in self.commands:
                renderer._draw_material(blend, texture)
                if index_count:
                    self.DrawElementsBaseVertex(mode, index_count, 0x1405, offset + index_offset, first)
                else:
                    renderer.DrawArrays(mode, first, count)
        finally:
            renderer.BindBuffer(ELEMENT_BUFFER, 0)
            renderer.BindBuffer(ARRAY_BUFFER, 0)
            self.commands.clear()
            self.used = 0

    def close(self):
        if self.buffer.value:
            self.DeleteBuffers(1, ct.byref(self.buffer))
            self.buffer.value = 0
