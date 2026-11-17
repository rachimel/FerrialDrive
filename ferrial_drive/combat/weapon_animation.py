"""수납·인출·조준과 총 이동 모션 선택. 실제 이동과 사격 규칙은 소유하지 않는다."""

from dataclasses import dataclass
from math import isfinite


def relative_movement(movement, facing):
    forward = movement[0] * facing[0] + movement[1] * facing[1]
    right = movement[1] * facing[0] - movement[0] * facing[1]
    return ("forward" if forward >= 0 else "backward") if abs(forward) >= abs(right) else ("right" if right > 0 else "left")


@dataclass(frozen=True)
class WeaponMotion:
    name: str
    elapsed_seconds: float
    playback_speed: float = 1
    loop: bool = False
    direction: str = "se"

    @property
    def clip_name(self):
        return self.name + "/" + self.direction

    @property
    def motion(self):
        return self.name


class WeaponAnimation:
    def __init__(self, *, swap_speed=1, aim_speed=1):
        if any(not isfinite(v) or v <= 0 for v in (swap_speed, aim_speed)):
            raise ValueError("스왑·조준 배율은 양수 유한값이어야 한다.")
        self.swap_speed = swap_speed
        self.aim_speed = aim_speed
        self.reset()

    def reset(self):
        self.kind = self.target_kind = "melee"
        self.queue = []
        self.elapsed_seconds = 0.0
        self.aiming = False
        self.aim_transition = None
        self.aim_elapsed_seconds = 0.0
        self.movement_state = "idle"
        self.movement_elapsed_seconds = 0.0
        self.animation_speed = self.loop_speed = 1

    @property
    def switching(self):
        return bool(self.queue)

    def request(self, kind, *, force=False):
        if kind not in ("melee", "ranged"):
            raise ValueError("근접·원거리 무기만 지원한다.")
        if self.switching or (kind == self.kind and not force):
            return False
        self.target_kind = kind
        self.queue = ["sword_sheath" if self.kind == "melee" else "gun_holster",
                      "sword_draw" if kind == "melee" else "gun_draw"]
        self.elapsed_seconds = 0
        self.aim_transition = None
        return True

    def update(self, seconds, durations, *, aiming=False, state="idle", loop_speed=1, animation_speed=1):
        if not isfinite(seconds) or seconds < 0 or any(not isfinite(v) or v <= 0 for v in (loop_speed, animation_speed)):
            raise ValueError("갱신 시간은 0 이상 초, 재생 배율은 양수다.")
        self.animation_speed, self.loop_speed = animation_speed, loop_speed
        seconds *= animation_speed
        self.elapsed_seconds += seconds * (self.swap_speed if self.switching else 1)
        while self.queue and self.elapsed_seconds + 1e-10 >= durations.get(self.queue[0], 0.5):
            self.elapsed_seconds = max(0, self.elapsed_seconds - durations.get(self.queue[0], 0.5))
            self.queue.pop(0)
            if not self.queue:
                self.kind = self.target_kind
                self.aiming = False
                self.elapsed_seconds = 0
        self.aim_elapsed_seconds += seconds * self.aim_speed
        if aiming != self.aiming:
            self.aiming = aiming
            self.aim_transition = "gun_aim_enter" if aiming else "gun_aim_exit"
            self.aim_elapsed_seconds = 0
        if state == "run" or self.kind != "ranged" or self.switching:
            self.aim_transition = None
        if self.aim_transition and self.aim_elapsed_seconds >= durations.get(self.aim_transition, 2/3):
            self.aim_transition = None
        if state != self.movement_state:
            self.movement_elapsed_seconds = 0
            self.movement_state = state
        self.movement_elapsed_seconds += seconds * loop_speed

    def select(self, state, movement, facing, *, shot_age_seconds, shot_interval_seconds, durations):
        if self.queue:
            return WeaponMotion(self.queue[0], self.elapsed_seconds, self.animation_speed * self.swap_speed)
        if self.kind == "melee":
            return None
        prefix = "gun_aim" if self.aiming else "gun_hip"
        if state == "run":
            return WeaponMotion(prefix + "_run_" + relative_movement(movement, facing), self.movement_elapsed_seconds,
                                self.animation_speed * self.loop_speed, True)
        if self.aim_transition:
            return WeaponMotion(self.aim_transition, self.aim_elapsed_seconds, self.animation_speed * self.aim_speed)
        if state in ("dash", "boost"):
            return WeaponMotion(prefix + "_dash", self.movement_elapsed_seconds, self.animation_speed, True)
        if shot_age_seconds < shot_interval_seconds:
            name = prefix + "_fire"
            speed = durations.get(name, 0.5) / shot_interval_seconds
            return WeaponMotion(name, shot_age_seconds * speed, speed)
        return WeaponMotion("gun_aim_hold" if self.aiming else "gun_ready", self.movement_elapsed_seconds,
                            self.animation_speed, True)
