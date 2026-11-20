"""같은 포즈 텍스처를 여러 위치에 놓을 때 정수 픽셀 사각형을 묶어 제출한다."""

import ctypes as ct

try:
    import numpy as np
    from numba import config, njit
except ModuleNotFoundError as error:
    if error.name not in {"numpy", "numba"}:
        raise
    njit = None


MIN_POSE_COPIES = 4


def _fill_positions(points, dx, dy, width, height, positions):
    for i in range(len(points)):
        x = round(points[i, 0] + dx)
        y = round(points[i, 1] + dy)
        positions[i, 0, 0], positions[i, 0, 1] = x, y
        positions[i, 1, 0], positions[i, 1, 1] = x + width, y
        positions[i, 2, 0], positions[i, 2, 1] = x + width, y + height
        positions[i, 3, 0], positions[i, 3, 1] = x, y + height


_compiled_positions = njit(cache=True)(_fill_positions) if njit and not config.DISABLE_JIT else None


class PoseCopyBatch:
    def __init__(self, pico):
        self.pico = pico
        self.capacity = self.submits = 0
        self.vertices = self.indices = self.positions = None
        self._reserve(MIN_POSE_COPIES)
        # 첫 표시 전에 실제 SDL 버퍼와 동일한 배열 서명으로 컴파일한다.
        _compiled_positions(np.empty((0, 2), dtype=np.float64), 0., 0., 1, 1, self.positions)

    def _reserve(self, count):
        self.capacity = max(count, self.capacity * 2)
        p = self.pico
        self.vertices = (p.SDL_Vertex * (self.capacity * 4))()
        self.indices = (ct.c_int * (self.capacity * 6))()
        stride = ct.sizeof(p.SDL_Vertex)
        self.positions = np.ndarray((self.capacity, 4, 2), dtype=np.float32, buffer=self.vertices,
                                    offset=p.SDL_Vertex.position.offset, strides=(4 * stride, stride, 4))
        for i in range(self.capacity):
            base = i * 4
            for j, (u, v) in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
                vertex = self.vertices[base + j]
                vertex.color = p.SDL_Color(255, 255, 255, 255)
                vertex.tex_coord.x, vertex.tex_coord.y = u, v
            self.indices[6 * i:6 * i + 6] = base, base + 1, base + 2, base, base + 2, base + 3

    def draw(self, texture, placements, dx, dy, width, height):
        count = len(placements)
        if count > self.capacity:
            self._reserve(count)
        _compiled_positions(np.asarray(placements, dtype=np.float64), float(dx), float(dy), width, height,
                            self.positions)
        p = self.pico
        if p.SDL_RenderGeometry(p.renderer, texture, self.vertices, count * 4, self.indices, count * 6):
            return False
        self.submits += 1
        return True


def create_pose_copy_batch(pico):
    if _compiled_positions is not None:
        return PoseCopyBatch(pico)
