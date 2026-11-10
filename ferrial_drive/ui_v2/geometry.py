"""UI의 가벼운 원근·기울기 투영. 렌더러와 게임 상태에 의존하지 않는다."""

from dataclasses import dataclass
from math import isfinite


def scaled_point(point, anchor, amount):
    return tuple(center + (value - center) * amount for value, center in zip(point, anchor))


def slanted_meter(bar, ratio=1):
    """채움 끝도 외곽과 같은 사선인 평행사변형. 직사각형 클립을 쓰지 않는다."""
    x, y, width, height = bar
    cut = min(18, height * 0.65)
    fill_width = width * max(0, min(1, ratio))
    return ((x - cut, y), (x - cut + fill_width, y),
            (x + fill_width, y + height), (x, y + height))


def quad_fill(points, ratio):
    amount = max(0, min(1, ratio))
    a, b, c, d = points
    mix = lambda first, last: tuple(x + (y - x) * amount for x, y in zip(first, last))
    return a, mix(a, b), mix(d, c), d


def quadratic_curve(start, control, end, steps=10):
    return tuple(tuple((1 - t) ** 2 * a + 2 * (1 - t) * t * b + t ** 2 * c
                       for a, b, c in zip(start, control, end))
                 for t in (index / steps for index in range(1, steps + 1)))


@dataclass(frozen=True)
class ResourceGeometry:
    icon_center: tuple
    icon_radius: float
    hp_shape: tuple
    hp_outline: tuple
    energy_outline: tuple
    energy_body: tuple
    level_shape: tuple
    energy_channel: tuple
    level_top: float
    level_left: float

    def energy_tip(self, ratio):
        shape = quad_fill(self.energy_channel, ratio)
        return tuple((a + b) / 2 for a, b in zip(shape[1], shape[2]))


def resource_geometry(layout, curve_radius=10):
    """두 바의 외곽에서 마름모와 HP 아래에 붙는 레벨 곡선을 함께 계산한다."""
    hx, hy, hw, hh = layout["hp_bar"]
    ex, ey, ew, eh = layout["energy_bar"]
    cx = layout["ultimate_center_x"]
    top, bottom = hy - 4, ey + eh + 4
    cy, radius = (top + bottom) / 2, (bottom - top) / 2
    level_left, level_top = hx + hw, ey - hh
    neck = (level_left + curve_radius * 7 / 6, cy)
    shoulder = (level_left + curve_radius / 4, level_top + curve_radius / 3)
    side_slope = (neck[0] - shoulder[0]) / (neck[1] - shoulder[1])
    cap_x = lambda y: neck[0] + (y - cy) * side_slope
    hp_outline = ((cx, top), (cap_x(top), top), neck, (cx + radius, cy))
    # 채움을 공유 경계 쪽으로 내리고 양 끝을 각 외곽의 사선에 맞춘다.
    fill_top, fill_bottom = cy - hh - 3, cy - 3
    left = cx + fill_top - top + 2
    hp_shape = ((left, fill_top), (cap_x(fill_top) - 3, fill_top),
                (cap_x(fill_bottom) - 3, fill_bottom), (left + hh, fill_bottom))
    right = ex + ew + layout["energy_level_width_pixels"]
    upper = (right - curve_radius * 2, level_top)
    side, end = (right + 6, level_top + curve_radius * 1.8), (right - curve_radius, bottom)
    level_shape = ((neck, shoulder) + quadratic_curve(shoulder, (level_left, level_top),
                                                    (level_left + curve_radius, level_top))
                   + (upper,) + quadratic_curve(upper, (right + 6, level_top), side)
                   + quadratic_curve(side, (right + 10, bottom), end)
                   + ((neck[0], bottom),))
    icon_right, icon_bottom = (cx + radius, cy), (cx, bottom)
    energy_body = (icon_right, neck, level_shape[-1], icon_bottom)
    energy_outline = (icon_right,) + level_shape[:-1] + (icon_bottom,)
    channel_top, channel_bottom = ey + 2, bottom - 5
    left_top = cx + radius - (channel_top - cy) + 4
    left_bottom = cx + radius - (channel_bottom - cy) + 4
    channel = ((left_top, channel_top), (neck[0] + 2, channel_top),
               (neck[0] + 2 - (channel_bottom - channel_top), channel_bottom), (left_bottom, channel_bottom))
    return ResourceGeometry((cx, cy), radius, hp_shape, hp_outline, energy_outline,
                            energy_body, level_shape, channel, level_top, level_left)


def body_diamond(body, size_scale):
    x, y, width, height = body
    return x + width / 2, y + height / 2, width * size_scale / 2, height * size_scale / 2


def counter_plaque(left, right, thickness, slant):
    """투영 후 두 점을 윗변으로 쓰는 평행사변형."""
    return left, right, (right[0] - slant, right[1] + thickness), (left[0] - slant, left[1] + thickness)


@dataclass(frozen=True)
class PerspectivePlane:
    x: float
    y: float
    width: float
    height: float
    depth: float = 0.25
    lean: float = 0.15
    slope: float = 0.06

    def __post_init__(self):
        if not all(isfinite(value) for value in (self.x, self.y, self.width, self.height,
                                                self.depth, self.lean, self.slope)):
            raise ValueError("UI 투영 값은 유한해야 한다.")
        if self.width <= 0 or self.height <= 0 or not 0 <= self.depth <= 1:
            raise ValueError("투영 크기는 양수, 원근 강도는 0~1이어야 한다.")

    def point(self, x, y):
        denominator = 1 + self.depth * (1 - x / self.width)
        local_y = (y - self.height / 2) / denominator
        local_x = x / denominator
        return (self.x + local_x - self.lean * local_y,
                self.y + local_y + self.height / 2 + self.slope * local_x)
