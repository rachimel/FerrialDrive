"""총탄 선분과 표적 원의 교차 계산. 명중 순서와 피해 처리는 호출자가 소유한다."""

from .geometry import _segment_circle_fraction, segment_circle
from .numeric_runtime import configure_combat_blas

configure_combat_blas()

try:
    from numba import njit
    import numpy as np
except ModuleNotFoundError as error:
    if error.name not in {"numpy", "numba"}:
        raise
    njit = None


# 작은 표적 묶음은 배열 변환과 Python↔Numba 호출 비용을 피한다.
MIN_BATCH_TARGETS = 8
_circle_fraction = njit(inline="always")(_segment_circle_fraction) if njit else _segment_circle_fraction


def _fill_contacts(x, y, dx, dy, circles, count, indices, fractions):
    length_squared = dx * dx + dy * dy
    contacts = 0
    for index in range(count):
        fraction = _circle_fraction(dx, dy, length_squared, x - circles[index, 0], y - circles[index, 1],
                                    circles[index, 2])
        if fraction >= 0:
            indices[contacts] = index
            fractions[contacts] = fraction
            contacts += 1
    return contacts


_compiled_contacts = njit(cache=True)(_fill_contacts) if njit else None


class ProjectileContacts:
    def __init__(self):
        self.capacity = self.count = 0
        self.circles = self.indices = self.fractions = None

    def _reserve(self, count):
        if count > self.capacity:
            capacity = max(count, MIN_BATCH_TARGETS, self.capacity * 2)
            circles = np.empty((capacity, 3), dtype=np.float64)
            indices = np.empty(capacity, dtype=np.intp)
            fractions = np.empty(capacity, dtype=np.float64)
            self.circles, self.indices, self.fractions = circles, indices, fractions
            self.capacity = capacity

    def warm_up(self):
        if _compiled_contacts is not None:
            self._reserve(1)
            _compiled_contacts(0., 0., 0., 0., self.circles, 0, self.indices, self.fractions)

    def prepare(self, targets, bullet_radius):
        self.count = 0
        if _compiled_contacts is None or not isinstance(targets, (list, tuple)) or len(targets) < MIN_BATCH_TARGETS:
            return
        self._reserve(len(targets))
        for index, target in enumerate(targets):
            self.circles[index] = (target.center.x, target.center.y, target.radius_pixels + bullet_radius)
        self.count = len(targets)

    def find(self, start, end, targets, bullet_radius):
        if not self.count:
            return [(fraction, target) for target in targets
                    if (fraction := segment_circle(start, end, target.center,
                                                   target.radius_pixels + bullet_radius)) is not None]
        count = _compiled_contacts(float(start.x), float(start.y), float(end.x - start.x), float(end.y - start.y),
                                   self.circles, self.count, self.indices, self.fractions)
        return [(float(self.fractions[index]), targets[self.indices[index]]) for index in range(count)]
