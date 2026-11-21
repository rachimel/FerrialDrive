"""입력 순서를 유지하는 HUD 도형 큐와 재사용 SDL 전송 버퍼."""

from contextlib import contextmanager
from ctypes import byref, c_float, c_int
from functools import wraps
from struct import Struct


VERTEX = Struct("=ff4Bff")


def batch_barrier(function):
    """즉시 그리기·텍스처 수명 변경 전에 대기 도형을 제출한다."""
    @wraps(function)
    def guarded(self, *args, **kwargs):
        self.flush_batch()
        return function(self, *args, **kwargs)
    return guarded


class HudBatchQueue:
    """같은 상태의 연속 도형만 합친다. 창·렌더러의 수명은 호출자가 소유한다."""

    def __init__(self, pico, *, vertex_capacity=2048, rect_capacity=1024):
        if any(type(value) is not int or value < 1 for value in (vertex_capacity, rect_capacity)):
            raise ValueError('HUD 버퍼 용량은 양의 정수여야 한다.')
        self.pico = pico
        self.enabled = True
        self.depth = 0
        self.kind = None
        self.texture = None
        self.rgba = None
        self.contains_text = False
        self.vertex_count = self.index_count = self.rect_count = 0
        self.vertices = self.indices = self.rects = None
        self.vertex_views, self.rect_views = [], []
        self.vertex_capacity = self.index_capacity = self.rect_capacity = 0
        self.initial_vertex_capacity = vertex_capacity
        self.initial_rect_capacity = rect_capacity
        self.scale_x, self.scale_y = c_float(), c_float()
        self.stats = {}
        self.reset_stats()

    def reset_stats(self):
        self.stats = dict(geometry_requests=0, rectangle_requests=0, geometry_submits=0,
                          rectangle_submits=0, vertices=0, rectangles=0, buffer_allocations=0,
                          text_requests=0, text_submits=0)

    @property
    def active(self):
        return self.enabled and self.depth > 0

    @contextmanager
    def frame(self):
        if not self.enabled:
            yield
            return
        outer = self.depth == 0
        if outer:
            self.reset_stats()
        self.depth += 1
        try:
            yield
        except BaseException:
            self.discard()
            raise
        else:
            if outer:
                self.flush()
        finally:
            self.depth -= 1

    def discard(self):
        self.kind = self.texture = self.rgba = None
        self.vertex_count = self.index_count = self.rect_count = 0
        self.contains_text = False

    def unit_scale(self):
        self.pico.SDL_RenderGetScale(self.pico.renderer, byref(self.scale_x), byref(self.scale_y))
        return self.scale_x.value == 1 and self.scale_y.value == 1

    def _geometry_buffer(self, vertices, indices):
        if vertices <= self.vertex_capacity and indices <= self.index_capacity:
            return
        self.flush()
        self.vertex_capacity = max(self.initial_vertex_capacity, vertices, self.vertex_capacity * 2)
        self.index_capacity = max(self.vertex_capacity * 3, indices)
        self.vertices = (self.pico.SDL_Vertex * self.vertex_capacity)()
        self.indices = (c_int * self.index_capacity)()
        self.vertex_views = [(v.position, v.color, v.tex_coord) for v in self.vertices]
        self.stats['buffer_allocations'] += 1

    def _begin_geometry(self, count, indices, texture):
        if self.kind != 'geometry' or self.texture is not texture:
            self.flush()
        self._geometry_buffer(count, indices)
        if self.vertex_count + count > self.vertex_capacity or self.index_count + indices > self.index_capacity:
            self.flush()
        self.kind, self.texture = 'geometry', texture
        return self.vertex_count

    def text_quad(self, points, rgba, texture, uv):
        start = self._begin_geometry(4, 6, texture)
        for index, ((x, y), (u, v)) in enumerate(zip(points, uv)):
            VERTEX.pack_into(self.vertices, (start + index) * VERTEX.size, x, y, *rgba, u, v)
        self.indices[self.index_count:self.index_count + 6] = (start, start + 1, start + 2,
                                                              start, start + 2, start + 3)
        self.vertex_count += 4
        self.index_count += 6
        self.stats['geometry_requests'] += 1
        self.stats['vertices'] += 4
        self.stats['text_requests'] += 1
        self.contains_text = True
        if not self.active:
            self.flush()

    def polygon(self, points, rgba, *, texture=None, uv=None, colors=None, separate_triangles=False):
        """볼록 다각형을 입력 순서의 triangle fan으로 쌓는다."""
        point_count = len(points)
        if point_count < 3:
            return
        indices = (point_count - 2) * 3
        order = (tuple(value for index in range(1, point_count - 1) for value in (0, index, index + 1))
                 if separate_triangles else range(point_count))
        count = len(order)
        start = self._begin_geometry(count, indices, texture)
        for offset, source in enumerate(order):
            x, y = points[source]
            position, color, tex_coord = self.vertex_views[start + offset]
            position.x, position.y = x, y
            color.r, color.g, color.b, color.a = rgba if colors is None else colors[source]
            tex_coord.x, tex_coord.y = (0, 0) if uv is None else uv[source]
        faces = range(count) if separate_triangles else (
            value for offset in range(1, count - 1) for value in (0, offset, offset + 1))
        # 명시적 독립 인덱스는 SDL software의 삼각형→사각형 재해석을 막는다.
        for value in faces:
            index = self.index_count
            self.indices[index] = start + value
            self.index_count += 1
        self.vertex_count += count
        self.stats['geometry_requests'] += 1
        self.stats['vertices'] += count
        if not self.active:
            self.flush()

    def colored_mesh(self, vertices, faces):
        """하나의 색상 정점 메시를 분할 없이 큐에 추가한다."""
        count, index_count = len(vertices), len(faces)
        start = self._begin_geometry(count, index_count, None)
        for offset, (x, y, rgba) in enumerate(vertices, start):
            VERTEX.pack_into(self.vertices, offset * VERTEX.size, x, y, *rgba, 0, 0)
        end = self.index_count + index_count
        self.indices[self.index_count:end] = [start + index for index in faces] if start else faces
        self.index_count = end
        self.vertex_count += count
        self.stats['geometry_requests'] += 1
        self.stats['vertices'] += count
        if not self.active:
            self.flush()

    def rectangles(self, rectangles, rgba):
        """같은 색의 연속 사각형을 SDL_RenderFillRects로 묶어 전달한다."""
        if self.kind != 'rectangles' or self.rgba != rgba:
            self.flush()
        if self.rects is None:
            self.rect_capacity = self.initial_rect_capacity
            self.rects = (self.pico.SDL_Rect * self.rect_capacity)()
            self.rect_views = list(self.rects)
            self.stats['buffer_allocations'] += 1
        self.stats['rectangle_requests'] += 1
        for x, y, width, height in rectangles:
            if self.rect_count == self.rect_capacity:
                self.flush()
            self.kind, self.rgba = 'rectangles', rgba
            rect = self.rect_views[self.rect_count]
            rect.x, rect.y, rect.w, rect.h = x, y, width, height
            self.rect_count += 1
            self.stats['rectangles'] += 1
        if not self.active:
            self.flush()

    def flush(self):
        if self.kind is None:
            return
        p = self.pico
        try:
            if self.kind == 'geometry':
                result = p.SDL_RenderGeometry(p.renderer, self.texture, self.vertices, self.vertex_count,
                                              self.indices, self.index_count)
                self.stats['geometry_submits'] += 1
                self.stats['text_submits'] += int(self.contains_text)
            else:
                result = p.SDL_SetRenderDrawColor(p.renderer, *self.rgba)
                if not result:
                    result = p.SDL_RenderFillRects(p.renderer, self.rects, self.rect_count)
                self.stats['rectangle_submits'] += 1
            if result:
                raise RuntimeError('HUD 배치 제출 실패: ' + p.SDL_GetError().decode('utf-8', errors='replace'))
        finally:
            # 실패한 명령은 다음 프레임이나 정리 시 재실행하지 않는다.
            self.discard()

    def close(self):
        self.discard()
        self.vertices = self.indices = self.rects = None
        self.vertex_views.clear()
        self.rect_views.clear()
        self.vertex_capacity = self.index_capacity = self.rect_capacity = 0
