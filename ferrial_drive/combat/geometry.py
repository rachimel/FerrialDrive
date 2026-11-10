"""월드 좌표의 벡터·선분·볼록 다각형 접촉 검사."""

from dataclasses import dataclass
from math import hypot


@dataclass(frozen=True)
class Vec2:
    x: float = 0
    y: float = 0

    def __add__(self, other):
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar):
        return Vec2(self.x * scalar, self.y * scalar)

    @property
    def length(self):
        return hypot(self.x, self.y)

    def normalized(self, fallback=None):
        return self * (1 / self.length) if self.length > 1e-9 else (fallback or Vec2())


def cross(first, second):
    return first.x * second.y - first.y * second.x


def convex_hull(points):
    """칼날의 이전·현재 폭을 포함하는 볼록 외곽선을 만든다."""
    points = [Vec2(x, y) for x, y in sorted({(p.x, p.y) for p in points})]
    if len(points) <= 2:
        return tuple(points)
    lower, upper = [], []
    for chain, ordered in ((lower, points), (upper, reversed(points))):
        for point in ordered:
            while len(chain) >= 2 and cross(chain[-1] - chain[-2], point - chain[-1]) <= 0:
                chain.pop()
            chain.append(point)
    return tuple(lower[:-1] + upper[:-1])


def point_segment_distance_squared(point, start, end):
    delta, offset = end - start, point - start
    length_squared = delta.x * delta.x + delta.y * delta.y
    fraction = (max(0.0, min(1.0, (offset.x * delta.x + offset.y * delta.y) / length_squared))
                if length_squared > 1e-12 else 0)
    nearest = start + delta * fraction
    difference = point - nearest
    return difference.x * difference.x + difference.y * difference.y


def segments_intersect(first_start, first_end, second_start, second_end):
    if (max(min(first_start.x, first_end.x), min(second_start.x, second_end.x))
            > min(max(first_start.x, first_end.x), max(second_start.x, second_end.x)) + 1e-9
            or max(min(first_start.y, first_end.y), min(second_start.y, second_end.y))
            > min(max(first_start.y, first_end.y), max(second_start.y, second_end.y)) + 1e-9):
        return False
    first, second = first_end - first_start, second_end - second_start
    a = cross(first, second_start - first_start)
    b = cross(first, second_end - first_start)
    c = cross(second, first_start - second_start)
    d = cross(second, first_end - second_start)
    return a * b <= 1e-9 and c * d <= 1e-9


def point_in_polygon(point, vertices):
    if len(vertices) < 3:
        return False
    sides = [cross(second - first, point - first)
             for first, second in zip(vertices, vertices[1:] + vertices[:1])]
    return all(side >= -1e-9 for side in sides) or all(side <= 1e-9 for side in sides)


def moving_circle_touches_polygon(start, end, radius, vertices):
    """대상의 프레임 사이 이동도 포함하여 얇은 Trail 관통 누락을 막는다."""
    if not vertices:
        return False
    if point_in_polygon(start, vertices) or point_in_polygon(end, vertices):
        return True
    for first, second in zip(vertices, vertices[1:] + vertices[:1]):
        if segments_intersect(start, end, first, second):
            return True
        distance_squared = min(point_segment_distance_squared(start, first, second),
                               point_segment_distance_squared(end, first, second),
                               point_segment_distance_squared(first, start, end),
                               point_segment_distance_squared(second, start, end))
        if distance_squared <= radius * radius + 1e-9:
            return True
    return False
