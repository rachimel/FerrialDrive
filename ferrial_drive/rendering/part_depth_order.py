"""파츠 깊이 순서와 CPU 계산 대조 경로."""

from contextlib import contextmanager
import ctypes as ct
from functools import lru_cache
from math import ceil, floor

from ferrial_drive.diagnostics.gpu_profile import bind_gl

from .gl_pass import QUAD_VERTEX_SHADER, TexturedQuadPass


INSERTION_SORT_LIMIT = 16
BUFFER_BINDING = 6
BUFFER_TARGET = 0x90D2
BUFFER_BINDING_QUERY = 0x90D3
MAX_CAPTURE_BYTES = 16 * 1024**2

INSERTION_ORDER = b"""
    for(int i=1;i<PARTS;++i) {
        int part=order[i], cursor=i;
        float depth=depths[part];
        while(cursor>0) {
            int previous=order[cursor-1];
            if(!(depths[previous]>depth)) break;
            order[cursor]=previous;
            --cursor;
        }
        order[cursor]=part;
    }
"""

QUICK_ORDER = b"""
    ivec2 ranges[PARTS];
    int pending=1;
    ranges[0]=ivec2(0,PARTS-1);
    while(pending>0) {
        --pending;
        int low=ranges[pending].x, high=ranges[pending].y;
        int pivot=order[(low+high)/2];
        float pivotDepth=depths[pivot];
        int left=low, right=high;
        while(left<=right) {
            while(left<=high) {
                int part=order[left];
                float depth=depths[part];
                if(!(depth<pivotDepth || (depth==pivotDepth && part<pivot))) break;
                ++left;
            }
            while(right>=low) {
                int part=order[right];
                float depth=depths[part];
                if(!(depth>pivotDepth || (depth==pivotDepth && part>pivot))) break;
                --right;
            }
            if(left<=right) {
                int part=order[left];
                order[left]=order[right];
                order[right]=part;
                ++left;
                --right;
            }
        }
        if(low<right) { ranges[pending]=ivec2(low,right); ++pending; }
        if(left<high) { ranges[pending]=ivec2(left,high); ++pending; }
    }
"""

CPU_ORDER_DECLARATION = f"""
uniform int depthOrderMode;
uniform vec4 depthOrderBounds;
layout(std430, binding={BUFFER_BINDING}) buffer PartDepthOrder {{ uint depthOrderData[]; }};
""".encode()

CPU_ORDER_READ = b"""
    ivec2 pixel=ivec2(gl_FragCoord.xy)-ivec2(depthOrderBounds.xy);
    bool inOrderBounds=all(greaterThanEqual(pixel,ivec2(0))) &&
                       all(lessThan(pixel,ivec2(depthOrderBounds.zw)));
    int cell=pixel.y*int(depthOrderBounds.z)+pixel.x;
    if(depthOrderMode==1) {
        if(inOrderBounds) {
            for(int i=0;i<PARTS;++i) depthOrderData[cell*PARTS+i]=floatBitsToUint(depths[i]);
        }
        discard;
    }
    if(depthOrderMode==2 && inOrderBounds) {
        const int words=(PARTS+3)/4;
        for(int i=0;i<PARTS;++i) {
            uint packedOrder=depthOrderData[cell*words+i/4];
            order[i]=int((packedOrder>>uint((i%4)*8))&255u);
        }
    } else {
"""


def depth_order_shader(part_count, *, cpu=False):
    sort = INSERTION_ORDER if part_count <= INSERTION_SORT_LIMIT else QUICK_ORDER
    return CPU_ORDER_READ + sort + b"    }\n" if cpu else sort


def _insertion_words(depths, order, words):
    for pixel in range(depths.shape[0]):
        for part in range(depths.shape[1]):
            cursor = part
            depth = depths[pixel, part]
            while cursor and depths[pixel, order[cursor - 1]] > depth:
                order[cursor] = order[cursor - 1]
                cursor -= 1
            order[cursor] = part
        for rank in range(depths.shape[1]):
            words[pixel, rank // 4] |= order[rank] << (8 * (rank % 4))


@lru_cache(maxsize=1)
def _insertion_kernel():
    try:
        from numba import njit
    except ImportError:
        return None
    return njit(cache=True)(_insertion_words)


def packed_depth_order(depths):
    """프래그먼트별 파츠 번호를 깊이 순서로 정렬해 네 개씩 uint32에 담는다."""
    import numpy as np

    pixels, parts = depths.shape
    if not 1 <= parts <= 256:
        raise ValueError("깊이 순서 버퍼는 최대 256개 파츠를 담는다.")
    words = np.zeros((pixels, (parts + 3) // 4), dtype=np.uint32)
    if parts <= INSERTION_SORT_LIMIT:
        insertion = _insertion_kernel()
        if insertion is not None:
            insertion(depths, np.empty(parts, dtype=np.int32), words)
            return words
        order = np.argsort(depths, axis=-1, kind="stable")
    else:
        # 깊이가 같을 때 원래 파츠 번호를 비교하도록 키의 하위 비트에 넣는다.
        normalized = np.where(depths == 0, np.float32(0), depths)
        raw = normalized.view(np.uint32)
        keys = raw ^ np.where(raw >> 31, np.uint32(0xffffffff), np.uint32(0x80000000))
        keys = (keys.astype(np.uint64) << 8) | np.arange(parts, dtype=np.uint64)
        order = np.argsort(keys, axis=-1, kind="quicksort")
    for offset in range(4):
        indices = order[:, offset::4]
        words[:, :indices.shape[1]] |= indices.astype(np.uint32) << (8 * offset)
    return words


class CpuDepthOrderQuadPass(TexturedQuadPass):
    """실제 깊이 샘플을 읽어 CPU에서 정렬하고 동일 사각형에 순서를 적용한다."""

    def __init__(self, pico, *, part_count, fragment_shader, extra_uniforms):
        self.part_count = part_count
        self.use_cpu_order = True
        self.buffer = ct.c_uint()
        self.capacity = 0
        self.readback = None
        super().__init__(pico, fragment_shader=fragment_shader,
                         vertex_shader=QUAD_VERTEX_SHADER.replace(b"#version 120", b"#version 430 compatibility", 1),
                         extra_uniforms=(*extra_uniforms, "depthOrderMode", "depthOrderBounds"))

    def _bind_functions(self):
        super()._bind_functions()
        u, i, ptr, size = ct.c_uint, ct.c_int, ct.c_void_p, ct.c_ssize_t
        for name, arguments in {
            "glGenBuffers": [i, ptr], "glDeleteBuffers": [i, ptr],
            "glBindBuffer": [u, u], "glBindBufferBase": [u, u, u],
            "glGetIntegeri_v": [u, u, ptr], "glBufferData": [u, size, ptr, u],
            "glGetBufferSubData": [u, size, size, ptr], "glBufferSubData": [u, size, size, ptr],
            "glMemoryBarrier": [u],
        }.items():
            setattr(self, name, bind_gl(self.pico, name, None, arguments))

    @contextmanager
    def _bound(self, count):
        if not self.buffer.value:
            self.glGenBuffers(1, ct.byref(self.buffer))
        previous = self.integer(BUFFER_BINDING_QUERY)
        indexed = ct.c_int()
        self.glGetIntegeri_v(BUFFER_BINDING_QUERY, BUFFER_BINDING, ct.byref(indexed))
        self.glBindBufferBase(BUFFER_TARGET, BUFFER_BINDING, self.buffer.value)
        try:
            size = count * self.part_count * 4
            if size > self.capacity:
                self.glBufferData(BUFFER_TARGET, size, None, 0x88EA)
                self.readback = (ct.c_float * (count * self.part_count))()
                self.capacity = size
            yield size
        finally:
            self.glBindBufferBase(BUFFER_TARGET, BUFFER_BINDING, indexed.value)
            self.glBindBuffer(BUFFER_TARGET, previous)

    def submit_quad(self, vertices, clip):
        if not self.use_cpu_order:
            return super().submit_quad(vertices, clip)
        left, top = vertices[0][:2]
        right, bottom = vertices[-1][:2]
        if self.target_flip > 0:
            top, bottom = self.output_size[1] - bottom, self.output_size[1] - top
        cx, cy, cw, ch = clip
        x, y = max(cx, floor(left)), max(cy, floor(top))
        width, height = min(cx + cw, ceil(right)) - x, min(cy + ch, ceil(bottom)) - y
        if width <= 0 or height <= 0 or width * height * self.part_count * 4 > MAX_CAPTURE_BYTES:
            return super().submit_quad(vertices, clip)

        import numpy as np

        count = width * height
        mode = self.uniforms["depthOrderMode"]
        with self._bound(count) as size:
            self.glUniform4f(self.uniforms["depthOrderBounds"], x, y, width, height)
            try:
                self.glUniform1i(mode, 1)
                super().submit_quad(vertices, clip)
                self.glMemoryBarrier(0x0200)  # GL_BUFFER_UPDATE_BARRIER_BIT
                self.glGetBufferSubData(BUFFER_TARGET, 0, size, self.readback)
                depths = np.ctypeslib.as_array(self.readback)[:count * self.part_count].reshape(count, self.part_count)
                order = packed_depth_order(depths)
                self.glBufferSubData(BUFFER_TARGET, 0, order.nbytes, order.ctypes.data)
                self.glUniform1i(mode, 2)
                super().submit_quad(vertices, clip)
            finally:
                self.glUniform1i(mode, 0)

    def close(self):
        if self.buffer.value:
            self.glDeleteBuffers(1, ct.byref(self.buffer))
            self.buffer.value = 0
        self.readback = None
        super().close()
