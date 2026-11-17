"""첫 후보는 즉시 획득하고 다른 표적으로 교체할 때만 대기한다."""

from math import hypot, isfinite


class MouseAutoTargeting:
    def __init__(self, range_units=330, aim_range_units=460, switch_margin_seconds=1, *, release_range_units=None,
                 retain_outside_range=False):
        if (not all(map(isfinite, (range_units, aim_range_units, switch_margin_seconds)))
                or not 0 < range_units < aim_range_units or switch_margin_seconds < 0):
            raise ValueError("자동 획득 범위·전환 대기 시간이 유효하지 않다.")
        self.range_units, self.aim_range_units = range_units, aim_range_units
        if release_range_units is not None and (not isfinite(release_range_units) or release_range_units < aim_range_units):
            raise ValueError("해제 거리는 조준 획득 거리 이상의 유한값이어야 한다.")
        self.release_range_units = release_range_units
        self.retain_outside_range = retain_outside_range
        self.switch_margin_seconds = switch_margin_seconds
        self.reset()

    def reset(self, selected_id=None):
        self.selected_id, self.pending_id = selected_id, None
        self.pending_seconds = 0

    def update(self, candidates, origin_world, mouse_world, delta_seconds, *, aiming=False, range_distances=None,
               acquisition_ids=None, preferred_id=None, switch_delay_seconds=None):
        """acquisition_ids가 있으면 외부의 가시성 후보를 거리 제한 대신 사용한다."""
        if (not isfinite(delta_seconds) or delta_seconds < 0
                or not all(isfinite(value) for point in (origin_world, mouse_world) for value in point)):
            raise ValueError("표적 좌표와 갱신 시간은 유한해야 한다.")
        limit = self.aim_range_units if aiming else self.range_units
        delay = self.switch_margin_seconds if switch_delay_seconds is None else switch_delay_seconds
        if not isfinite(delay) or delay < 0:
            raise ValueError("표적 교체 대기는 0 이상 유한 초 값이어야 한다.")
        release_limit = self.release_range_units if self.release_range_units is not None else limit
        entries, ids = [], set()
        current_valid = False
        for candidate in candidates:
            if candidate.target_id in ids:
                raise ValueError("표적 ID는 중복될 수 없다.")
            ids.add(candidate.target_id)
            if range_distances is not None:
                if candidate.target_id not in range_distances:
                    raise ValueError("범위 판정에는 모든 후보의 거리가 필요하다.")
                distance = range_distances[candidate.target_id]
                if not isfinite(distance) or distance < 0:
                    raise ValueError("표적 거리는 0 이상의 유한값이어야 한다.")
            else:
                distance = hypot(*(a - b for a, b in zip(candidate.position, origin_world)))
            retained = candidate.target_id == self.selected_id and (self.retain_outside_range or distance <= release_limit)
            current_valid = current_valid or retained
            acquired = candidate.target_id in acquisition_ids if acquisition_ids is not None else distance <= limit
            if acquired or retained:
                entries.append((hypot(*(a - b for a, b in zip(candidate.position, mouse_world))), candidate.target_id))
        if not current_valid:
            self.selected_id = None
        best = min(entries)[1] if entries else None
        if preferred_id is not None and any(target_id == preferred_id for _, target_id in entries):
            best = preferred_id
        if self.selected_id is None and best is not None:
            self.reset(best)
            return self.selected_id
        if best is None or best == self.selected_id:
            self.pending_id, self.pending_seconds = None, 0
        elif best != self.pending_id:
            self.pending_id, self.pending_seconds = best, 0
        else:
            self.pending_seconds += delta_seconds
        if best is not None and best != self.selected_id and self.pending_seconds + 1e-9 >= delay:
            self.selected_id = best
            self.pending_id, self.pending_seconds = None, 0
        return self.selected_id
