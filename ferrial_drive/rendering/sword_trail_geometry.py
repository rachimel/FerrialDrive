"""타격별 Trail 표시 곡선을 연결한다. 실제 명중 면은 수정하지 않는다."""

from dataclasses import replace
from ferrial_drive.combat.geometry import Vec2, cross


def ribbon_edges(points, half_widths):
    """진행 곡선의 수직 방향으로 폭을 유지하며 공유 꼭짓점을 연결한다."""
    result, previous = [], None
    for index, (point, width) in enumerate(zip(points, half_widths)):
        tangent = points[min(len(points) - 1, index + 1)] - points[max(0, index - 1)]
        normal = Vec2(-tangent.y, tangent.x).normalized(previous or Vec2(0, 1))
        if previous is not None and normal.x * previous.x + normal.y * previous.y < 0:
            normal = normal * -1
        result.append((point - normal * width, point + normal * width))
        previous = normal
    return result


def sweep_runs(sections, minimum_sweep_ratio=0.12):
    """칼날 투영이 접히거나 면이 뒤집히는 지점에서 표시 띠를 분리한다."""
    groups, result = {}, []
    for section in sections:
        groups.setdefault(section.strike_id, []).append(section)
    for rows in groups.values():
        if rows[0].chevron:
            result.append(rows)
            continue
        maximum = max((row.tip_b - row.root_b).length for row in rows)
        current, winding = [], None

        def flush():
            distance = sum(((row.tip_b + row.root_b - row.tip_a - row.root_a) * 0.5).length for row in current)
            if current and distance >= maximum * 0.06:
                result.append(current[:])

        for row in rows:
            before, after = row.tip_a - row.root_a, row.tip_b - row.root_b
            movement = (row.tip_b + row.root_b - row.tip_a - row.root_a) * 0.5
            signed = cross((before + after).normalized(), movement.normalized())
            folded = before.x * after.x + before.y * after.y <= 0
            collapsed = min(before.length, after.length) < maximum * 0.08 or abs(signed) < minimum_sweep_ratio
            sign = 1 if signed >= 0 else -1
            if folded or collapsed or winding is not None and sign != winding:
                flush()
                current, winding = [], None
            if not folded and not collapsed:
                current.append(row)
                winding = sign
        flush()
    return result


def curved_trail_sections(sections, sample_seconds=1 / 240):
    groups = {}
    for section in sections:
        groups.setdefault(section.strike_id, []).append(section)
    result = []
    for rows in groups.values():
        if rows[0].chevron or len(rows) < 3:
            result.extend(rows)
            continue
        roots = [rows[0].root_a] + [row.root_b for row in rows]
        tips = [rows[0].tip_a] + [row.tip_b for row in rows]

        def soften(points):
            return [points[0]] + [sum_vectors([
                points[max(0, min(len(points) - 1, index + offset))] * weight
                for offset, weight in ((-2, 1), (-1, 2), (0, 3), (1, 2), (2, 1))]) * (1 / 9)
                for index in range(1, len(points) - 1)] + [points[-1]]

        roots, tips = soften(roots), soften(tips)

        def curve(points, index, t):
            a, b, c, d = [points[max(0, min(len(points) - 1, n))] for n in
                          (index - 1, index, index + 1, index + 2)]
            return (b * 2 + (c - a) * t + (a * 2 - b * 5 + c * 4 - d) * t ** 2
                    + (b * 3 - a - c * 3 + d) * t ** 3) * 0.5

        for index, row in enumerate(rows):
            previous_time = rows[index - 1].created_seconds if index else row.created_seconds - sample_seconds
            for part in range(3):
                low, high = part / 3, (part + 1) / 3
                result.append(replace(row, root_a=curve(roots, index, low), root_b=curve(roots, index, high),
                                      tip_a=curve(tips, index, low), tip_b=curve(tips, index, high),
                                      created_seconds=previous_time + (row.created_seconds - previous_time) * high))
    return result


def sum_vectors(values):
    total = values[0]
    for value in values[1:]:
        total = total + value
    return total
