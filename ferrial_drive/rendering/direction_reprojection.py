"""직교 카메라의 깊이 픽셀에서 인접 방향의 동일 표면 좌표를 복원한다."""

from math import cos, floor, hypot, isfinite, radians, sin, sqrt


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def view_rotation(data, yaw_degrees):
    angle = radians(yaw_degrees)
    c, s = cos(angle), sin(angle)
    outer, skew = data["vertical"], data["yaw_tangent"]
    return tuple(c * (row == column) + (1 - c) * outer[3 * row + column] + s * skew[3 * row + column]
                 for row in range(3) for column in range(3))


def direction_span(upper_yaw, lower_yaw):
    """각 추종 공간에 필요한 인접 방향과 보간 위상을 반환한다."""
    if not isfinite(upper_yaw) or not isfinite(lower_yaw):
        raise ValueError("보간 각도는 유한한 도 단위다.")
    spans = []
    for yaw in (upper_yaw, lower_yaw):
        phase = yaw % 360 / 45
        first = floor(phase)
        weight = phase - first
        spans.append((first, (first + 1) % 8 if weight else first, weight))
    return None if spans[0] == spans[1] and not spans[0][2] else tuple(spans)


def direction_banks(spans):
    return tuple(dict.fromkeys(direction for span in spans for direction in span[:2]))


def direction_frame(correspondence, clips, spans, interval):
    """상하체의 방향별 깊이로 목표 각도의 픽셀 변위를 재구성한다."""
    index, alpha = interval["first"], interval["alpha"]
    origin = correspondence["origin"]
    scale = correspondence["pixels_per_cm"]
    transforms = []
    banks = direction_banks(spans)
    for first, second, weight in spans:
        transforms.append(view_rotation(correspondence, 45 * weight))
        transforms.append(view_rotation(correspondence, 45 * (weight - (first != second))))
    # 새 상체와 하체의 회전점이 같은 허리 위치를 유지하도록 이동한다.
    def projected_waist(group):
        waists = clips[spans[group][0]]["anchors"]
        waist = [a + (b - a) * alpha for a, b in zip(waists[index]["waist"], waists[index + 1]["waist"])]
        relative = (waist[0] - origin[0], waist[1] - origin[1],
                    (waist[2] + correspondence["calibrated_depth_offset_cm"] - origin[2]) * scale)
        matrix = transforms[group * 2]
        return [dot(matrix[i:i + 3], relative) for i in (0, 3, 6)]

    shift = tuple(b - a for a, b in zip(projected_waist(0), projected_waist(1)))
    matrices = []
    for mat in transforms:
        a, b, c, d, e, f, *depth = mat
        inverse = 1 / (a * e - b * d)
        matrices.extend((e * inverse, -b * inverse, (b * f - e * c) * inverse, 0,
                         -d * inverse, a * inverse, (d * c - a * f) * inverse, 0,
                         *depth, 0))

    endpoints = []
    rectangles = []
    depth_extents = []
    for name, part in clips[banks[0]]["parts"].items():
        group = 0 if part["space"] == "upper" else 1
        dx, dy, _ = shift if group == 0 else (0, 0, 0)
        corners = []
        for end, direction in enumerate(spans[group][:2]):
            spec = clips[direction]["parts"][name]
            a, b = spec["frames"][index:index + 2]
            center = a["center_depth"] + (b["center_depth"] - a["center_depth"]) * alpha
            endpoints.append({"a": a, "b": b, "crop": spec["crop"], "bank": banks.index(direction),
                              "shift": (group, 0, center)})
            x, y, w, h = spec["crop"]
            mat = transforms[2 * group + end]
            near = min(a["depth_extent"][0], b["depth_extent"][0])
            far = max(a["depth_extent"][1], b["depth_extent"][1])
            for u in (x, x + w):
                for v in (y, y + h):
                    for depth_cm in (near, far):
                        p = (u - origin[0], v - origin[1], (depth_cm - origin[2]) * scale)
                        corners.append((dot(mat[:3], p) + origin[0] + dx, dot(mat[3:6], p) + origin[1] + dy))
                        depth_extents.append(origin[2] + (dot(mat[6:9], p) + (shift[2] if group == 0 else 0)) / scale)
        rectangles.append((min(x for x, _ in corners) - 2, min(y for _, y in corners) - 2,
                           max(x for x, _ in corners) + 2, max(y for _, y in corners) + 2))
    left = floor(min(r[0] for r in rectangles))
    top = floor(min(r[1] for r in rectangles))
    right = -floor(-max(r[2] for r in rectangles))
    bottom = -floor(-max(r[3] for r in rectangles))
    return {"alpha": alpha, "parts": endpoints, "bounds": (left, top, right - left, bottom - top),
            "depth_bounds": (min(depth_extents), max(depth_extents)),
            "angle_rects": [component for rect in rectangles for component in rect], "angle_matrices": matrices,
            "angle_origin": (*origin, scale), "angle_weights": (*shift[:2], spans[0][2], spans[1][2]),
            "waist_depth_shift": shift[2] / scale}


def calibrated_camera(camera, size):
    position, target = camera["position"], camera["target"]
    delta = [b - a for a, b in zip(position, target)]
    length = sqrt(dot(delta, delta))
    forward = tuple(v / length for v in delta)
    horizontal = hypot(*forward[:2])
    right = (-forward[1] / horizontal, forward[0] / horizontal, 0)
    down = (forward[2] * right[1], -forward[2] * right[0], -horizontal)
    basis = (right, down, forward)
    scale = size[0] / camera["width_cm"]
    return {
        "pixels_per_cm": scale,
        "origin": [size[0] / 2 - dot(target, right) * scale,
                   size[1] / 2 - dot(target, down) * scale, -dot(position, forward)],
        "vertical": [a[2] * b[2] for a in basis for b in basis],
        "yaw_tangent": [dot(a, (-b[1], b[0], 0)) for a in basis for b in basis],
    }


def depth_pixels(folder, frame, crop):
    import numpy as np
    import zlib
    return np.frombuffer(zlib.decompress((folder / frame["depth"]).read_bytes()), "<f4").reshape(crop[3], crop[2])


def bake_correspondence(source, clips, camera, size, *, depth_offset_cm=None):
    """이웃 방향의 깊이 일치를 최대화해 MRQ 깊이 원점과 회전 관계를 저장한다."""
    import numpy as np

    data = calibrated_camera(camera, size)
    directions = {clip["direction"]: clip for clip in clips.values()}
    pairs = [(d, (d + 1) % 8) for d in sorted(directions) if (d + 1) % 8 in directions]
    if not pairs:
        raise ValueError("기준이 될 인접 방향의 프리렌더가 필요하다.")
    origin, scale = np.array(data["origin"]), data["pixels_per_cm"]
    rotations = {sign: np.array(view_rotation(data, sign * 45)).reshape(3, 3) for sign in (1, -1)}
    comparisons = []
    for first, second in pairs:
        for direction, adjacent, sign in ((first, second, 1), (second, first, -1)):
            left, right = directions[direction], directions[adjacent]
            for name, a in left["parts"].items():
                b = right["parts"][name]
                for index in (0, len(a["frames"]) // 2):
                    a_depth = depth_pixels((source.parent / a["clip"]).parent, a["frames"][index], a["crop"])
                    b_depth = depth_pixels((source.parent / b["clip"]).parent, b["frames"][index], b["crop"])
                    y, x = np.nonzero(np.isfinite(a_depth[2::8, 2::8]) & (a_depth[2::8, 2::8] > 0))
                    y, x = y * 8 + 2, x * 8 + 2
                    points = np.stack((x + .5 + a["crop"][0] - origin[0], y + .5 + a["crop"][1] - origin[1],
                                       (a_depth[y, x] - origin[2]) * scale))
                    projected = rotations[sign] @ points
                    projected += np.array([[origin[0] - b["crop"][0]], [origin[1] - b["crop"][1]], [origin[2] * scale]])
                    offset_factor = (np.eye(3)[:, 2] - rotations[sign][:, 2]) * scale
                    comparisons.append((projected, offset_factor[:, None], b_depth))
    samples = sum(p.shape[1] for p, _, _ in comparisons)
    if not samples:
        raise ValueError("깊이 원점을 검증할 표면이 없다.")

    def score(offset_cm):
        hits = 0
        for projected, correction, depth in comparisons:
            x, y, z = projected + correction * offset_cm
            ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
            valid = (ix >= 0) & (iy >= 0) & (ix < depth.shape[1]) & (iy < depth.shape[0])
            hits += np.count_nonzero(np.abs(depth[iy[valid], ix[valid]] - z[valid] / scale) < 4)
        return hits

    # MRQ의 직교 깊이는 가시 표면까지의 카메라 축 거리와 상수만큼 차이 날 수 있다.
    offset = depth_offset_cm
    if offset is None:
        offset = max(range(-2048, 2049, 32), key=score)
        offset = max(range(offset - 32, offset + 33), key=score)
    fraction = score(offset) / samples
    if fraction < .1:
        raise ValueError(f"인접 방향의 깊이 대응을 검증하지 못했다 ({fraction:.1%}).")
    data["origin"][2] += offset
    data.update(pairs=pairs, calibrated_depth_offset_cm=offset, depth_inlier_fraction=fraction,
                depth_sample_count=samples)
    return data
