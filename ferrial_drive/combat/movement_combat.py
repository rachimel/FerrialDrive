"""4타 예약·방향 고정 전진과 공격을 유지하는 부스트 이동을 연결한다."""

from math import isfinite
from dataclasses import dataclass

from ferrial_drive.assets.combo import ComboPlayback
from .locomotion import direction_name, unit_vector


@dataclass(frozen=True)
class AttackStep:
    strike_id: int
    clip_name: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    real_seconds: float
    start_position_m: tuple
    end_position_m: tuple
    dash: bool = False
    boosting: bool = False


def average_smoothstep(start, end):
    """정규화한 타격 시간의 속도 곡선을 적분해 프레임 구간 평균을 구한다."""
    if end <= start:
        return start * start * (3 - 2 * start)
    # SmoothStep(3t²-2t³)의 원시함수는 t³-t⁴/2다.
    return ((end**3-end**4/2) - (start**3-start**4/2)) / (end-start)


class MovementCombat:
    def __init__(self, controller, clips, *, speed=1.25, acceleration="smoothstep"):
        if not isfinite(speed) or speed <= 0:
            raise ValueError("공격 재생 속도는 양수여야 한다.")
        if acceleration not in ("constant", "smoothstep", "quint_in"):
            raise ValueError("공격 전진은 constant/smoothstep/quint_in 중 하나다.")
        self.controller = controller
        self.combo = ComboPlayback(clips)
        self.speed = speed
        self.acceleration = acceleration
        self.strike_direction = unit_vector(controller.facing)
        self.auto_queued = False
        self.strike_id = 0
        self.attack_steps = []

    @property
    def active(self):
        return self.combo.active

    def request_attack(self, aim, *, automatic=False):
        starting = not self.combo.active or self.combo.waiting_for_input
        aim = unit_vector(aim)
        selected = aim if any(aim) else unit_vector(self.controller.facing)
        direction = direction_name(selected)
        if not self.combo.active or self.combo.waiting_for_input:
            self.strike_direction = selected
        if self.combo.waiting_for_input:
            self.combo.direction = direction
        was_queued = self.combo.queued
        accepted = self.combo.request(direction)
        if accepted and starting:
            self.strike_id += 1
        if accepted and self.combo.queued:
            self.auto_queued = (not was_queued or self.auto_queued) if automatic else False
        return accepted

    def stop_auto_swing(self):
        if self.auto_queued:
            self.combo.clear_buffer()
        self.auto_queued = False

    def request_boost(self, movement, aim):
        return self.controller.request_boost(movement, aim)

    @property
    def boosting(self):
        return self.controller.boost_preparing or self.controller.boost_remaining_seconds > 0

    def update(self, delta_seconds, movement, aim, *, dash=False, auto_swing=False):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("갱신 시간은 0 이상의 유한한 초 단위다.")
        movement, aim = unit_vector(movement), unit_vector(aim)
        self.attack_steps = []
        if not auto_swing:
            self.stop_auto_swing()
        remaining = delta_seconds
        while True:
            if auto_swing:
                self.request_attack(aim, automatic=True)
            if not self.combo.active:
                self.controller.update(remaining, movement, aim, dash=dash)
                return
            if self.combo.waiting_for_input:
                if any(movement) and not self.boosting:
                    self.combo.reset()
                    continue
                self.controller.update(remaining, (0, 0), self.strike_direction, dash=dash,
                                       movement_speed_mps=0, face_movement=False)
                return
            duration = self.combo.clips[self.combo.clip_name].duration_ms/1000
            settings = self.controller.settings
            if self.combo.attack_index == 2:
                speed = settings.third_attack_dash_speed_mps if dash else settings.third_attack_run_speed_mps
            elif self.combo.attack_index == 3:
                speed = settings.fourth_attack_dash_speed_mps if dash else settings.fourth_attack_run_speed_mps
            else:
                speed = settings.attack_dash_speed_mps if dash else settings.attack_run_speed_mps
            until_end = max(0, duration-self.combo.elapsed_seconds)/self.speed
            until_boost_boundary = (self.controller.boost_prepare_remaining_seconds if self.controller.boost_preparing
                                    else self.controller.boost_remaining_seconds if self.boosting else float("inf"))
            elapsed = min(remaining, until_end, until_boost_boundary)
            start = self.combo.elapsed_seconds / duration
            end = min(1, (self.combo.elapsed_seconds + elapsed*self.speed) / duration)
            end_speed = speed if self.acceleration == "constant" else speed * (
                end**5 if self.acceleration == "quint_in" else end * end * (3 - 2 * end))
            if self.acceleration == "quint_in":
                # t⁵ 속도를 구간 적분해 프레임률에 따른 거리 차이를 방지한다.
                speed *= (end**6-start**6)/(6*(end-start)) if end > start else start**5
            elif self.acceleration == "smoothstep":
                speed *= average_smoothstep(start, end)
            old_index = self.combo.attack_index
            start_position = self.controller.position_m
            clip_name = self.combo.clip_name
            start_seconds = self.combo.elapsed_seconds
            selected = aim if any(aim) else unit_vector(self.controller.facing)
            boosting = self.boosting
            self.controller.update(elapsed, self.strike_direction, self.strike_direction, dash=dash,
                                   movement_speed_mps=speed, movement_end_speed_mps=end_speed, face_movement=False)
            if elapsed > 0:
                self.attack_steps.append(AttackStep(self.strike_id, clip_name, start_seconds,
                    min(duration, start_seconds + elapsed * self.speed), duration, elapsed,
                    start_position, self.controller.position_m, dash=dash, boosting=boosting))
            self.combo.update(elapsed*self.speed, next_direction=direction_name(selected))
            remaining = max(0, remaining-elapsed)
            if self.combo.active and not self.combo.waiting_for_input and self.combo.attack_index != old_index:
                self.strike_id += 1
                self.auto_queued = False
                self.strike_direction = selected
                self.controller.facing = selected
            if self.combo.waiting_for_input and any(movement) and not self.boosting:
                self.combo.reset()
            if remaining <= 1e-12:
                if auto_swing and not self.combo.active:
                    self.request_attack(aim, automatic=True)
                if not self.combo.active:
                    self.controller.update(0, movement, aim, dash=dash)
                elif self.combo.waiting_for_input:
                    self.controller.update(0, (0, 0), self.strike_direction, movement_speed_mps=0,
                                           face_movement=False)
                return
