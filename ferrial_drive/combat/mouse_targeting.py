"""마우스 월드 좌표의 최근접 후보를 일정 시간 확인한 뒤 자동 선택한다."""

from math import hypot, isfinite


class MouseAutoTargeting:
    def __init__(self, range_units=330, aim_range_units=460, switch_margin_seconds=1):
        if (not all(map(isfinite, (range_units, aim_range_units, switch_margin_seconds)))
                or not 0 < range_units < aim_range_units or switch_margin_seconds < 0):
            raise ValueError("자동 획득 범위·전환 대기 시간이 유효하지 않다.")
        self.range_units, self.aim_range_units = range_units, aim_range_units
        self.switch_margin_seconds = switch_margin_seconds
        self.reset()

    def reset(self, selected_id=None):
        self.selected_id, self.pending_id = selected_id, None
        self.pending_seconds = 0

    def update(self, candidates, origin_world, mouse_world, delta_seconds, *, aiming=False):
        if (not isfinite(delta_seconds) or delta_seconds < 0
                or not all(isfinite(value) for point in (origin_world, mouse_world) for value in point)):
            raise ValueError("표적 좌표와 갱신 시간은 유한해야 한다.")
        limit = self.aim_range_units if aiming else self.range_units
        entries, ids = [], set()
        for candidate in candidates:
            if candidate.target_id in ids:
                raise ValueError("표적 ID는 중복될 수 없다.")
            ids.add(candidate.target_id)
            if hypot(*(a - b for a, b in zip(candidate.position, origin_world))) <= limit:
                entries.append((hypot(*(a - b for a, b in zip(candidate.position, mouse_world))), candidate.target_id))
        valid = {target_id for _, target_id in entries}
        if self.selected_id not in valid:
            self.selected_id = None
        best = min(entries)[1] if entries else None
        if best is None or best == self.selected_id:
            self.pending_id, self.pending_seconds = None, 0
        elif best != self.pending_id:
            self.pending_id, self.pending_seconds = best, 0
        else:
            self.pending_seconds += delta_seconds
        if best is not None and best != self.selected_id and self.pending_seconds + 1e-9 >= self.switch_margin_seconds:
            self.selected_id = best
            self.pending_id, self.pending_seconds = None, 0
        return self.selected_id
