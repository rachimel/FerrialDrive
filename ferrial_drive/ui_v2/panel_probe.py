"""그리기 없이 같은 UI 경로에서 패널의 실제 화면 범위만 수집한다."""

from contextlib import contextmanager
from ctypes import c_float
from math import ceil, floor

from .panels import visible_panel_y_range


class PanelProbeRenderer:
    def __init__(self, renderer):
        self.source = renderer
        self.scale, self.viewport, self.output_size, self.clipping = renderer.draw_transform()
        self.ranges = []

    def __getattr__(self, name):
        if name in ("text_size", "text_ascent", "digit_ink_bottom", "rgba"):
            return getattr(self.source, name)
        if name in ("clear", "text", "rich_text", "neon_text", "line", "rect", "ring", "filled_triangle",
                    "warped_text", "filtered_polygons", "scanline_layer", "film_grain",
                    "weapon_silhouette", "image", "metallic_rect", "particle_quads"):
            return lambda *args, **kwargs: None
        raise AttributeError(name)

    def draw_transform(self):
        return self.scale, self.viewport, self.output_size, self.clipping

    def draw_instanced_particles(self, *args):
        return True

    def draw_compute_particles(self, *args):
        pass

    def include(self, surface):
        bounds = visible_panel_y_range(surface, self.draw_transform())
        if bounds is not None:
            self.ranges.append(bounds)

    @contextmanager
    def directional_blur(self, bounds, displacement, strength, samples=33):
        yield

    @contextmanager
    def translated(self, dx, dy):
        previous = self.viewport
        x, y, width, height = previous
        self.viewport = (x + round(dx), y + round(dy), width, height)
        try:
            yield
        finally:
            self.viewport = previous

    @contextmanager
    def scaled(self, amount, anchor):
        previous = self.scale, self.viewport
        sx, sy = self.scale
        x, y, width, height = self.viewport
        self.scale = c_float(sx * amount).value, c_float(sy * amount).value
        self.viewport = (round((x + (1 - amount) * anchor[0]) / amount),
                         round((y + (1 - amount) * anchor[1]) / amount), width, height)
        try:
            yield
        finally:
            self.scale, self.viewport = previous

    @contextmanager
    def clip(self, rect):
        previous = self.clipping
        left, top = ceil(rect.x), ceil(rect.y)
        right, bottom = floor(rect.x + rect.width), floor(rect.y + rect.height)
        if previous is not None:
            x, y, width, height = previous
            left, top = max(left, x), max(top, y)
            right, bottom = min(right, x + width), min(bottom, y + height)
        self.clipping = left, top, max(0, right - left), max(0, bottom - top)
        try:
            yield
        finally:
            self.clipping = previous
