"""거리·커서 각도 우선 표적 획득. UI와 장치 입력에 의존하지 않는다."""

from dataclasses import dataclass
from math import atan2, degrees, hypot, isfinite


@dataclass(frozen=True)
class TargetCandidate:
    target_id: str
    position: tuple[float, float]

    def __post_init__(self):
        if not self.target_id or len(self.position) != 2 or not all(map(isfinite, self.position)):
            raise ValueError("표적은 고유 ID와 유한한 2차원 위치가 필요하다.")


class TargetAcquisition:
    def __init__(self, range_units, aim_range_units, angle_tolerance_degrees):
        if (not all(map(isfinite, (range_units, aim_range_units, angle_tolerance_degrees)))
                or range_units <= 0 or aim_range_units <= range_units
                or not 0 <= angle_tolerance_degrees <= 180):
            raise ValueError("획득 거리는 양수이며 조준 거리가 더 커야 한다. 각도 동률 범위는 0~180도다.")
        self.range_units = range_units
        self.aim_range_units = aim_range_units
        self.angle_tolerance_degrees = angle_tolerance_degrees
        self.acquired_ids = set()

    def clear(self):
        self.acquired_ids.clear()

    def acquire(self, candidates, origin, cursor, *, aiming=False):
        """명시적 획득 입력당 한 번 호출한다. 좌표계·거리 단위는 호출자가 통일한다."""
        if not all(isfinite(value) for point in (origin, cursor) for value in point):
            raise ValueError("플레이어와 커서 위치는 유한해야 한다.")
        limit = self.aim_range_units if aiming else self.range_units
        direction = (cursor[0] - origin[0], cursor[1] - origin[1])
        ranked, ids = [], set()
        for candidate in candidates:
            if candidate.target_id in ids:
                raise ValueError("표적 ID는 중복될 수 없다.")
            ids.add(candidate.target_id)
            dx, dy = candidate.position[0] - origin[0], candidate.position[1] - origin[1]
            distance = hypot(dx, dy)
            if distance > limit:
                continue
            # 커서가 플레이어와 같으면 방향 차이를 0으로 두어 거리로 선택한다.
            angle = abs(degrees(atan2(direction[0] * dy - direction[1] * dx,
                                     direction[0] * dx + direction[1] * dy))) if any(direction) else 0
            ranked.append((angle, distance, candidate.target_id))
        if not ranked:
            self.clear()
            return None
        remaining = [entry for entry in ranked if entry[2] not in self.acquired_ids]
        if not remaining:
            self.clear()
            remaining = ranked
        best_angle = min(entry[0] for entry in remaining)
        tied = [entry for entry in remaining if entry[0] <= best_angle + self.angle_tolerance_degrees]
        selected = min(tied, key=lambda entry: (entry[1], entry[0], entry[2]))[2]
        self.acquired_ids.add(selected)
        return selected
