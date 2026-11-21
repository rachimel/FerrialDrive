"""외부 테마 미리보기에서 실제로 그린 팔레트 출처와 화면 범위를 수집한다."""

from inspect import signature
from math import ceil, floor


class PreviewColor(str):
    def __new__(cls, value, widget, role, palette):
        color = super().__new__(cls, value)
        color.widget, color.role, color.palette = widget, role, palette
        return color


class ThemePreviewRenderer:
    """실제 렌더러에 위임한다. 미리보기 캡처 프레임에서만 연결한다."""

    DRAW_METHODS = {"rect", "metallic_rect", "line", "soft_line", "ring", "filled_triangle",
                    "text", "rich_text", "neon_text", "gradient_text", "warped_text", "filtered_polygons",
                    "scanline_layer", "weapon_silhouette", "image"}

    def __init__(self, source):
        self.source = source
        self.regions = {}

    def hud_batch(self):
        return self.source.hud_batch()

    def __getattr__(self, name):
        method = getattr(self.source, name)
        if name not in self.DRAW_METHODS:
            return method
        parameters = signature(method)

        def draw(*args, **kwargs):
            values = parameters.bind(*args, **kwargs)
            values.apply_defaults()
            self.record(name, values.arguments)
            return method(*args, **kwargs)

        setattr(self, name, draw)
        return draw

    def record(self, method, values):
        colors = [value for value in values.values() if isinstance(value, PreviewColor)]
        if not colors or values.get("opacity", 1) <= 0:
            return
        points = self.points(method, values)
        if not points:
            return
        xs, ys = zip(*points)
        left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
        # SDL의 clip은 viewport에 상대적인 논리 좌표다.
        (sx, sy), (vx, vy, _, _), (width, height), clip = self.source.draw_transform()
        if clip is not None:
            x, y, w, h = clip
            left, top, right, bottom = max(left, x), max(top, y), min(right, x + w), min(bottom, y + h)
        if right <= left or bottom <= top:
            return
        left, top = max(0, floor((left + vx) * sx)), max(0, floor((top + vy) * sy))
        right, bottom = min(width, ceil((right + vx) * sx)), min(height, ceil((bottom + vy) * sy))
        if right <= left or bottom <= top:
            return
        for color in colors:
            key = color.widget, color.role, color.palette
            previous = self.regions.get(key, (left, top, right, bottom))
            self.regions[key] = (min(previous[0], left), min(previous[1], top),
                                 max(previous[2], right), max(previous[3], bottom))

    def points(self, method, values):
        v = values
        if method in ("rect", "metallic_rect", "image", "weapon_silhouette"):
            rect = v["rect"]
            return ((rect.x, rect.y), (rect.x + rect.width, rect.y + rect.height))
        if method == "line":
            return ((min(v["x1"], v["x2"]) - 1, min(v["y1"], v["y2"]) - 1),
                    (max(v["x1"], v["x2"]) + 1, max(v["y1"], v["y2"]) + 1))
        if method == "soft_line":
            a, b = v["first"], v["last"]
            return ((min(a[0], b[0]) - 1, min(a[1], b[1]) - 1),
                    (max(a[0], b[0]) + 1, max(a[1], b[1]) + 1))
        if method == "ring":
            radius = v["radius"] + v["thickness"]
            return ((v["x"] - radius, v["y"] - radius), (v["x"] + radius, v["y"] + radius))
        if method == "filled_triangle":
            return (v["first"], v["second"], v["third"])
        if method == "filtered_polygons":
            return tuple(point for polygon in v["polygons"] for point in polygon)
        if method == "scanline_layer":
            return v["surface"]
        if method in ("text", "rich_text", "neon_text", "gradient_text", "warped_text"):
            if not v["text"]:
                return ()
            if method == "rich_text":
                width, height = self.source.rich_text_size(v["text"], v["role"])
            else:
                width, height = self.source.text_size(v["text"], v["role"])
            width *= v.get("scale_x", 1)
            height *= v.get("scale_y", 1)
            if v.get("max_width") is not None:
                width = min(width, v["max_width"])
            left, top = v["x"], v["y"]
            left -= width * {"center": .5, "right": 1}.get(v.get("align"), 0)
            right, bottom = left + width, top + height
            clip = v.get("clip_rect")
            if clip is not None:
                left, top = max(left, clip.x), max(top, clip.y)
                right, bottom = min(right, clip.x + clip.width), min(bottom, clip.y + clip.height)
            if right <= left or bottom <= top:
                return ()
            points = ((left, top), (right, top), (right, bottom), (left, bottom))
            return tuple(v["project"](x, y) for x, y in points) if method == "warped_text" else points
        return ()

    def export(self):
        return [{"widget": widget, "role": role, "palette": palette, "bounds": list(bounds)}
                for (widget, role, palette), bounds in self.regions.items()]
