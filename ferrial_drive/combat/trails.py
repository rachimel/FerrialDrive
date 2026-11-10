"""전투에서 만드는 칼날 궤적. 같은 다각형을 그리기와 명중 검사에 사용한다."""

from dataclasses import dataclass
from math import atan2, cos, radians, sin

from .geometry import Vec2, convex_hull


@dataclass(frozen=True)
class BladePose:
    root: Vec2
    tip: Vec2


@dataclass(frozen=True)
class TrailSection:
    vertices: tuple[Vec2, ...]
    start_tip: Vec2
    end_tip: Vec2
    created_seconds: float
    started_seconds: float


def blade_pose(origin, direction, reach_units, half_angle_degrees, combo_index, progress):
    progress = max(0.0, min(1.0, progress))
    angle = atan2(direction.y, direction.x)
    half_angle = radians(half_angle_degrees)
    if combo_index == 0:
        angle += half_angle * (-0.55 + 1.1 * progress)
    elif combo_index == 1:
        angle += half_angle * (-1 + 2 * progress)
    elif combo_index == 3:
        angle += half_angle * (1 - 2 * progress)
    root_distance = min(14.0, reach_units * 0.3)
    root = origin + direction * root_distance
    length = reach_units - root_distance
    if combo_index == 2:
        length *= 0.45 + progress * 0.55
    return BladePose(root, root + Vec2(cos(angle), sin(angle)) * length)


def trail_section(previous, current, half_width_units, created_seconds, *, started_seconds=None):
    points = []
    for pose in (previous, current):
        direction = (pose.tip - pose.root).normalized(Vec2(1, 0))
        offset = Vec2(-direction.y, direction.x) * half_width_units
        points.extend((pose.root + offset, pose.tip + offset,
                       pose.tip - offset, pose.root - offset))
    return TrailSection(convex_hull(points), previous.tip, current.tip, created_seconds,
                        created_seconds if started_seconds is None else started_seconds)
