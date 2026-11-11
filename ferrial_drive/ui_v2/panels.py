"""대화창·미니맵의 면과 분절 테두리 형상. 입력·시간·렌더러와 분리한다."""

from dataclasses import dataclass
from math import ceil, hypot, isfinite

from .geometry import tapered_stroke_mesh


@dataclass(frozen=True)
class PanelBorderPart:
    part_id: str
    polygons: tuple
    opacity: float


@dataclass(frozen=True)
class PanelGeometry:
    surface: tuple
    border_parts: tuple[PanelBorderPart, ...]


def scale_panel_geometry(geometry, center, width_ratio, height_ratio):
    """완성 형상과 분리 테두리를 패널 중앙 기준으로 함께 펼친다."""
    if width_ratio == height_ratio == 1:
        return geometry
    cx, cy = center
    def points(polygon):
        return tuple((cx + (x - cx) * width_ratio, cy + (y - cy) * height_ratio) for x, y in polygon)
    return PanelGeometry(points(geometry.surface), tuple(
        PanelBorderPart(part.part_id, tuple(points(polygon) for polygon in part.polygons), part.opacity)
        for part in geometry.border_parts))


def clip_panel_band(surface, top_pixels, height_pixels):
    """패널 면을 수평 띠로 자른다. 사선 외곽과 짧은 절단을 유지한다."""
    points = surface
    for boundary, below in ((top_pixels, True), (top_pixels + height_pixels, False)):
        if not points:
            return ()
        result, previous = [], points[-1]
        previous_inside = (previous[1] >= boundary) if below else (previous[1] <= boundary)
        for current in points:
            inside = (current[1] >= boundary) if below else (current[1] <= boundary)
            if inside != previous_inside:
                amount = (boundary - previous[1]) / (current[1] - previous[1])
                result.append((previous[0] + (current[0] - previous[0]) * amount, boundary))
            if inside:
                result.append(current)
            previous, previous_inside = current, inside
        points = tuple(result)
    return points


def clip_panel_rect(surface, left, top, width, height):
    """패널 면을 사각 영역으로 자른다. 화면·반복 타일 마스킹에 사용한다."""
    points = clip_panel_band(surface, top, height)
    swapped = clip_panel_band(tuple((y, x) for x, y in points), left, width)
    return tuple((x, y) for y, x in swapped)


def visible_panel_y_range(surface, transform):
    """배율·viewport·clip 적용 후 실제 화면에 남은 패널의 Y 범위."""
    (sx, sy), (vx, vy, vw, vh), (width, height), clipping = transform
    left, top = max(0, vx * sx), max(0, vy * sy)
    right, bottom = min(width, (vx + vw) * sx), min(height, (vy + vh) * sy)
    if clipping is not None:
        cx, cy, cw, ch = clipping
        left, top = max(left, (vx + cx) * sx), max(top, (vy + cy) * sy)
        right, bottom = min(right, (vx + cx + cw) * sx), min(bottom, (vy + cy + ch) * sy)
    if right <= left or bottom <= top:
        return None
    screen = tuple(((x + vx) * sx, (y + vy) * sy) for x, y in surface)
    screen = clip_panel_rect(screen, left, top, right - left, bottom - top)
    if len(screen) < 3:
        return None
    low, high = min(y for _, y in screen), max(y for _, y in screen)
    return (low, high) if high > low else None


def merge_panel_y_ranges(ranges):
    merged = []
    for low, high in sorted(ranges):
        if high <= low:
            continue
        if merged and low <= merged[-1][1] + 1e-6:
            merged[-1] = (merged[-1][0], max(high, merged[-1][1]))
        else:
            merged.append((low, high))
    return tuple(merged)


def panel_bright_band_top(ranges, travel_pixels, band_height, panel_y):
    """빈 Y 구간을 뺀 전역 경로의 띠를 해당 패널의 화면 Y로 환산한다."""
    length = sum(high - low for low, high in ranges)
    if not length:
        return None
    band_top = travel_pixels % (length + band_height) - band_height
    prefix = 0
    for low, high in ranges:
        if low - 1e-6 <= panel_y <= high + 1e-6:
            return low + band_top - prefix
        prefix += high - low
    return None


def build_scanlines(surface, spacing_pixels, thickness_pixels):
    """고정 비교용 수평 줄무늬를 패널의 실제 사선·절단 외곽 안으로 자른다."""
    if (not all(map(isfinite, (spacing_pixels, thickness_pixels)))
            or not 0 < thickness_pixels <= spacing_pixels):
        raise ValueError("Scanline 두께·간격은 양수이며 두께가 간격보다 클 수 없다.")

    top, bottom = min(y for _, y in surface), max(y for _, y in surface)
    strips = []
    for index in range(ceil((bottom - top) / spacing_pixels)):
        y = top + (index + 0.5) * spacing_pixels
        strip = clip_panel_band(surface, y, thickness_pixels)
        if len(strip) >= 3:
            strips.append(strip)
    return tuple(strips)


def build_panel_geometry(rect, cut_pixels, frame, border):
    """면·좌상단/우하단 꺾임·가로선·끝 조각을 독립 형상으로 반환한다."""
    x, y, width, height = rect
    if width <= 0 or height <= 0:
        raise ValueError("패널 크기는 양수여야 한다.")
    cut = min(cut_pixels, width / 5, height / 3)
    a, b = (x + cut, y), (x + width, y)
    c, d = (x + width - cut, y + height), (x, y + height)
    side_length = hypot(cut, height)
    bevel = min(frame["bevel_pixels"], side_length / 8, (width - cut) / 8)
    before = (a[0] - cut / side_length * bevel, y + height / side_length * bevel)
    after = (a[0] + bevel, y)

    def opposite(point):
        return 2 * x + width - point[0], 2 * y + height - point[1]

    surface = (after, b, opposite(before), opposite(after), d, before)
    parts = []
    for prefix, side_ratio, rail_ratio, alpha, rotate in (
            ("upper", frame["upper_side_ratio"], frame["upper_rail_ratio"], 0.8, False),
            ("lower", frame["lower_side_ratio"], frame["lower_rail_ratio"], 0.5, True)):
        side = min(side_length * side_ratio, side_length - bevel)
        leg = (a[0] - cut / side_length * side, y + height / side_length * side)
        joint = (a[0] + max(frame["corner_join_pixels"], bevel + border["corner_hold_pixels"]), y)
        rail_end = (joint[0] + (width - cut) * rail_ratio, y)

        def transform(polygons):
            return tuple(tuple(opposite(point) if rotate else point for point in polygon)
                         for polygon in polygons)

        corner = tapered_stroke_mesh((leg, before, after, joint), (1, 2),
                                      frame["rail_width_pixels"], border["corner_width_pixels"],
                                      border["reach_pixels"], border["corner_hold_pixels"])
        parts.append(PanelBorderPart(prefix + "_corner", transform(corner), alpha))
        rail = tapered_stroke_mesh((joint, rail_end), (0,), border["thin_width_pixels"],
                                    frame["rail_width_pixels"], rail_end[0] - joint[0],
                                    border["corner_hold_pixels"])
        parts.append(PanelBorderPart(prefix + "_rail", transform(rail), alpha))
        cursor = rail_end[0]
        for index, length in enumerate(frame["fragment_lengths_pixels"]):
            cursor += frame["fragment_gap_pixels"]
            half = frame["fragment_height_pixels"] / 2
            slant = min(frame["fragment_slant_pixels"], length / 2)
            fragment = ((cursor + slant, y - half), (cursor + length, y - half),
                        (cursor + length - slant, y + half), (cursor, y + half))
            parts.append(PanelBorderPart(f"{prefix}_fragment_{index}", transform((fragment,)), alpha))
            cursor += length
    return PanelGeometry(surface, tuple(parts))
