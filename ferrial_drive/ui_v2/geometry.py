"""UI의 가벼운 원근·기울기 투영. 렌더러와 게임 상태에 의존하지 않는다."""

from dataclasses import dataclass
from math import hypot, isfinite


def segmented_stroke_mesh(points, width, sections):
    """경로 전체의 길이 비율로 분절·굵기를 지정한다. 꺾임의 단면을 공유한다."""
    if not isfinite(width) or width <= 0:
        raise ValueError('강조선 두께는 양수인 유한한 픽셀 값이어야 한다.')
    previous_end = 0
    for start, end, first_width, last_width in sections:
        if (not all(map(isfinite, (start, end, first_width, last_width)))
                or not previous_end <= start < end <= 1
                or not 0 < first_width <= 1 or not 0 < last_width <= 1):
            raise ValueError('강조선 구간은 겹치지 않는 0~1 길이 비율과 양수인 1 이하 굵기 비율이어야 한다.')
        previous_end = end
    path = []
    for point in points:
        if not path or hypot(point[0] - path[-1][0], point[1] - path[-1][1]) > 1e-9:
            path.append(point)
    if len(path) < 2:
        return ()
    lengths = [hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:])]
    normals = [(-(b[1] - a[1]) / length, (b[0] - a[0]) / length)
               for a, b, length in zip(path, path[1:], lengths)]
    distances, joins = [0], [normals[0]]
    for length in lengths:
        distances.append(distances[-1] + length)
    for first, last in zip(normals, normals[1:]):
        denominator = 1 + first[0] * last[0] + first[1] * last[1]
        if denominator < 0.25:
            raise ValueError('강조선의 접힘 각도가 너무 좁다.')
        joins.append(tuple((a + b) / denominator for a, b in zip(first, last)))
    joins.append(normals[-1])
    total, quads = distances[-1], []
    for start, end, first_width, last_width in sections:
        low, high = start * total, end * total
        samples = [low, *(distance for distance in distances[1:-1] if low < distance < high), high]
        edges = []
        for distance in samples:
            index = next(i for i, stop in enumerate(distances[1:]) if distance <= stop)
            t = (distance - distances[index]) / lengths[index]
            normal = joins[index] if t <= 1e-9 else joins[index + 1] if t >= 1 - 1e-9 else normals[index]
            x, y = (a + (b - a) * t for a, b in zip(path[index], path[index + 1]))
            amount = (distance - low) / (high - low)
            half = width * (first_width + (last_width - first_width) * amount) / 2
            nx, ny = normal
            edges.append(((x + nx * half, y + ny * half), (x - nx * half, y - ny * half)))
        for first, last in zip(edges, edges[1:]):
            quads.append((first[0], last[0], last[1], first[1]))
    return tuple(quads)


def hatched_stroke_mesh(points, width, pitch_start, pitch_end, cut_width):
    """선의 띠 안에만 빗금을 만든다. 꺾인 구간에서도 간격의 위상을 이어간다."""
    if not all(isfinite(v) and v > 0 for v in (width, pitch_start, pitch_end, cut_width)) or cut_width >= min(pitch_start, pitch_end):
        raise ValueError('빗금 두께·간격은 양수이며 무늬 폭은 간격보다 작아야 한다.')
    total = sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))
    centers, position = [-pitch_start], 0
    while position <= total + width:
        centers.append(position)
        t = min(1, position / total) if total else 1
        position += pitch_start + (pitch_end - pitch_start) * t
    shapes, travelled = [], 0
    for a, b in zip(points, points[1:]):
        length = hypot(b[0] - a[0], b[1] - a[1])
        if not length:
            continue
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        for center in centers:
            offset = center - travelled
            if offset < -width or offset > length + width:
                continue
            half = width / 2
            shape = ((offset - half, -half), (offset - half + cut_width, -half),
                     (offset + half + cut_width, half), (offset + half, half))
            # 선분 시작/끝을 넘는 빗금만 잘라 바깥 테두리를 건드리지 않는다.
            for limit, sign in ((0, 1), (length, -1)):
                clipped = []
                if not shape:
                    break
                previous = shape[-1]
                for point in shape:
                    before, inside = sign * (previous[0] - limit) >= 0, sign * (point[0] - limit) >= 0
                    if before != inside:
                        t = (limit - previous[0]) / (point[0] - previous[0])
                        clipped.append((limit, previous[1] + (point[1] - previous[1]) * t))
                    if inside:
                        clipped.append(point)
                    previous = point
                shape = tuple(clipped)
            if len(shape) >= 3:
                shapes.append(tuple((a[0] + x * ux - y * uy, a[1] + x * uy + y * ux) for x, y in shape))
        travelled += length
    return tuple(shapes)


def tapered_stroke_mesh(points, corner_indices, thin_width, corner_width, reach, corner_hold_pixels=0):
    """지정한 꼭짓점으로 갈수록 직선으로 두꺼워지는 선. 이음부 단면을 공유한다."""
    if (not all(map(isfinite, (thin_width, corner_width, reach)))
            or not 0 < thin_width <= corner_width or reach <= 0):
        raise ValueError("테두리 두께와 변화 거리는 양수이며 꼭짓점 두께가 더 작을 수 없다.")
    if not isfinite(corner_hold_pixels) or corner_hold_pixels < 0:
        raise ValueError("최대 두께 유지 거리는 0 이상의 유한한 픽셀 값이어야 한다.")
    normals, lengths = [], []
    for a, b in zip(points, points[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = hypot(dx, dy)
        if length == 0:
            raise ValueError("테두리에 길이 0인 선분을 사용할 수 없다.")
        normals.append((-dy / length, dx / length))
        lengths.append(length)
    joins = []
    for index in range(len(points)):
        if index == 0 or index == len(points) - 1:
            joins.append(normals[0 if index == 0 else -1])
        else:
            a, b = normals[index - 1], normals[index]
            denominator = 1 + a[0] * b[0] + a[1] * b[1]
            if denominator < 0.25:
                raise ValueError("테두리의 접힘 각도가 너무 좁다.")
            joins.append(((a[0] + b[0]) / denominator, (a[1] + b[1]) / denominator))
    quads = []
    for index, (a, b, length, normal) in enumerate(zip(points, points[1:], lengths, normals)):
        both_corners = index in corner_indices and index + 1 in corner_indices
        ramp = min(reach, length / 2 if both_corners else length)
        hold = min(corner_hold_pixels, ramp)
        nodes = []
        samples = {0, 1}
        for distance in (hold / length, ramp / length):
            if index in corner_indices:
                samples.add(distance)
            if index + 1 in corner_indices:
                samples.add(1 - distance)
        def influence(distance):
            if distance <= hold:
                return 1
            return max(0, (ramp - distance) / (ramp - hold)) if ramp > hold else 0
        for t in sorted(samples):
            strength = max(influence(t * length) if index in corner_indices else 0,
                           influence((1 - t) * length) if index + 1 in corner_indices else 0)
            half = (thin_width + (corner_width - thin_width) * strength) / 2
            nx, ny = joins[index] if t == 0 else joins[index + 1] if t == 1 else normal
            x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            nodes.append(((x + nx * half, y + ny * half), (x - nx * half, y - ny * half)))
        for first, second in zip(nodes, nodes[1:]):
            quads.append((first[0], second[0], second[1], first[1]))
    return tuple(quads)


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


def resource_geometry(layout, bevel_pixels=10):
    """HP·마름모·에너지·레벨의 공통 접점과 사선 모서리를 계산한다."""
    hx, hy, hw, hh = layout["hp_bar"]
    ex, ey, ew, eh = layout["energy_bar"]
    cx = layout["ultimate_center_x"]
    top, bottom = hy, ey + eh + 4
    cy, radius = hy + hh, layout["ultimate_radius_pixels"]
    level_left, level_top = hx + hw, top
    neck = (level_left + bevel_pixels * 7 / 6, cy)
    hp_outline = ((cx + radius - hh, top), (neck[0], top), neck, (cx + radius, cy))
    hp_shape = hp_outline
    right = ex + ew + layout["energy_level_width_pixels"]
    right_cut = layout.get('level_right_bevel_pixels', bevel_pixels)
    upper = (right - right_cut, level_top)
    side = (right + 6, level_top + right_cut)
    level_shape = (neck, (neck[0], level_top), upper,
                   side, (side[0], bottom - right_cut), (right - right_cut, bottom),
                   (neck[0], bottom))
    # 큰 마름모의 변 중간에도 바를 붙일 수 있도록 각 높이의 접점을 구한다.
    icon_right, icon_bottom = (cx + radius, cy), (cx + radius - (bottom - cy), bottom)
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
