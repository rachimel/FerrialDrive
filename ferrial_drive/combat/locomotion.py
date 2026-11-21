"""미터 단위 이동과 모션 상태. 창·입력 장치·에셋 로딩과 독립이다."""

from ctypes import Structure, c_double
from dataclasses import dataclass, replace
from math import atan2, floor, hypot, isfinite, pi

from ferrial_drive.assets.directional import SCREEN_DIRECTIONS

from .entity_storage import DenseStorage, EntityRegistry, vector_field


def unit_vector(vector):
    if len(vector) != 2 or not all(map(isfinite, vector)):
        raise ValueError("방향은 유한한 2차원 벡터여야 한다.")
    length = hypot(*vector)
    return tuple(value / length for value in vector) if length else (0.0, 0.0)


def direction_name(vector):
    return SCREEN_DIRECTIONS[floor(atan2(vector[1], vector[0]) * 4 / pi + 0.5) % 8]


@dataclass(frozen=True)
class LocomotionSettings:
    map_size_m: float = 1000
    radius_m: float = 2.5
    run_speed_mps: float = 50
    dash_speed_mps: float = 100
    movement_acceleration_seconds: float = 0.2
    boost_start_speed_mps: float = 250
    boost_prepare_seconds: float = 0.08
    boost_duration_seconds: float = 0.2
    attack_run_speed_mps: float = 27
    attack_dash_speed_mps: float = 90
    third_attack_run_speed_mps: float = 36
    third_attack_dash_speed_mps: float = 120
    fourth_attack_run_speed_mps: float = 18
    fourth_attack_dash_speed_mps: float = 60

    def __post_init__(self):
        values = (self.map_size_m, self.radius_m, self.run_speed_mps, self.dash_speed_mps,
                  self.movement_acceleration_seconds,
                  self.boost_start_speed_mps, self.boost_duration_seconds, self.attack_run_speed_mps,
                  self.attack_dash_speed_mps, self.third_attack_run_speed_mps, self.third_attack_dash_speed_mps,
                  self.fourth_attack_run_speed_mps, self.fourth_attack_dash_speed_mps)
        if (not all(isfinite(v) and v > 0 for v in values) or self.radius_m * 2 >= self.map_size_m
                or not isfinite(self.boost_prepare_seconds) or self.boost_prepare_seconds < 0):
            raise ValueError("거리·속도·시간은 양수 유한값이며 반경은 맵 안에 들어가야 한다.")


class PlayerTransform(Structure):
    _fields_ = [(name, c_double) for name in ("x", "y", "fx", "fy")]


class LocomotionController:
    position_m = vector_field("x", "y", lambda x, y: (x, y))
    facing = vector_field("fx", "fy", lambda x, y: (x, y))

    def __init__(self, settings=None, *, registry=None):
        self.settings = settings or LocomotionSettings()
        registry = EntityRegistry() if registry is None else registry
        self.eid = registry.create()
        self._transforms = DenseStorage(registry, PlayerTransform, 1)
        self._transforms.append(self.eid, self, PlayerTransform())
        self.health = None
        self.reset()

    def damage(self, amount):
        before = self.health.current
        self.health = replace(self.health, current=max(0, before - amount))
        return before, self.health.current

    def reset(self):
        self.speed_multiplier = 1.0
        self.position_m = (self.settings.map_size_m / 2,) * 2
        self.facing = (1.0, 1.0)
        self.state = "idle"
        self.strong_dash = False
        self.speed_mps = 0.0
        self.movement_speed_mps = 0.0
        self._speed_target_mps = 0.0
        self._speed_start_mps = 0.0
        self._speed_elapsed_seconds = 0.0
        self._last_movement = (0.0, 0.0)
        self.distance_m = 0.0
        self.boost_remaining_seconds = 0.0
        self.boost_prepare_remaining_seconds = 0.0
        self.boost_direction = (0.0, 1.0)
        self._boost_speed_mps = 0.0
        self._boost_target_mps = None

    @property
    def direction(self):
        return direction_name(self.facing)

    @property
    def boost_preparing(self):
        return self.boost_prepare_remaining_seconds > 0

    @property
    def presentation_state(self):
        # 약출력은 기존 카메라·레이더 설정의 기본 이동 값을 사용한다.
        return "run" if self.state == "dash" and not self.strong_dash else self.state

    @property
    def dash_output(self):
        return min(1.0, self.movement_speed_mps / self.settings.dash_speed_mps)

    def request_boost(self, movement, aim):
        if self.boost_remaining_seconds > 0 or self.boost_preparing:
            return False
        movement, aim = unit_vector(movement), unit_vector(aim)
        self.boost_direction = movement if any(movement) else aim if any(aim) else unit_vector(self.facing)
        self.boost_prepare_remaining_seconds = self.settings.boost_prepare_seconds
        if not self.boost_preparing:
            self._start_boost()
        return True

    def _start_boost(self):
        self.boost_remaining_seconds = self.settings.boost_duration_seconds
        self._boost_speed_mps = self.settings.boost_start_speed_mps
        self._boost_target_mps = None

    def _move(self, direction, speed_mps, seconds):
        speed_mps *= self.speed_multiplier
        low, high = self.settings.radius_m, self.settings.map_size_m - self.settings.radius_m
        previous = self.position_m
        self.position_m = tuple(max(low, min(high, value + axis * speed_mps * seconds))
                                for value, axis in zip(previous, direction))
        distance = hypot(*(b - a for a, b in zip(previous, self.position_m)))
        self.distance_m += distance
        return distance

    def _set_movement_speed(self, speed_mps):
        self.movement_speed_mps = self._speed_target_mps = self._speed_start_mps = speed_mps
        self._speed_elapsed_seconds = self.settings.movement_acceleration_seconds

    def _advance_movement_speed(self, target_mps, seconds):
        if target_mps != self._speed_target_mps:
            self._speed_start_mps = self.movement_speed_mps
            self._speed_target_mps = target_mps
            self._speed_elapsed_seconds = 0.0
        duration = self.settings.movement_acceleration_seconds
        ramp_seconds = min(seconds, max(0.0, duration-self._speed_elapsed_seconds))
        start = self._speed_elapsed_seconds/duration
        end = min(1.0, (self._speed_elapsed_seconds+ramp_seconds)/duration)
        difference = target_mps-self._speed_start_mps
        # 속도 곡선을 구간 적분하고 남은 시간은 목표 속도로 이동한다.
        area = (end**3-end**4/2)-(start**3-start**4/2)
        distance = self._speed_start_mps*ramp_seconds + difference*duration*area
        distance += target_mps*(seconds-ramp_seconds)
        self._speed_elapsed_seconds = min(duration, self._speed_elapsed_seconds+seconds)
        self.movement_speed_mps = self._speed_start_mps + difference*end*end*(3-2*end)
        return distance/seconds if seconds else self.movement_speed_mps

    def _advance_boost_speed(self, target_mps, seconds):
        if target_mps != self._boost_target_mps:
            self._boost_start_mps = self._boost_speed_mps
            self._boost_target_mps = target_mps
            self._boost_ramp_seconds = self.boost_remaining_seconds
            self._boost_elapsed_seconds = 0.0
        duration = self._boost_ramp_seconds
        start = self._boost_elapsed_seconds / duration
        end = min(1, (self._boost_elapsed_seconds + seconds) / duration)
        difference = target_mps - self._boost_start_mps
        area = (end**3 - end**4 / 2) - (start**3 - start**4 / 2)
        distance = self._boost_start_mps * seconds + difference * duration * area
        self._boost_elapsed_seconds += seconds
        self._boost_speed_mps = self._boost_start_mps + difference * end * end * (3 - 2 * end)
        return distance / seconds if seconds else self._boost_speed_mps

    def _advance_regular(self, seconds, movement, aim, dash, movement_speed_mps, movement_end_speed_mps, face_movement):
        coasting = (movement_speed_mps is None and not any(movement)
                    and any(self._last_movement) and self.movement_speed_mps > 0)
        direction = self._last_movement if coasting else movement
        self.state = "dash" if any(direction) else "idle"
        if not coasting:
            self.strong_dash = bool(dash and any(movement))
        if self.state == "dash" and face_movement:
            self.facing = direction
        elif any(aim):
            self.facing = aim
        speed = self.settings.dash_speed_mps if dash else self.settings.run_speed_mps
        if movement_speed_mps is not None:
            speed = movement_speed_mps
            self._set_movement_speed(speed if movement_end_speed_mps is None else movement_end_speed_mps)
            self._last_movement = (0.0, 0.0)
        elif any(movement) or coasting:
            if any(movement):
                self._last_movement = movement
            else:
                speed = 0.0
            speed = self._advance_movement_speed(speed, seconds)
            if coasting and self.movement_speed_mps <= 0:
                self.state = "idle"
                self.strong_dash = False
                self._last_movement = (0.0, 0.0)
        else:
            speed = 0.0
            self._set_movement_speed(0.0)
        return self._move(direction, speed, seconds)

    def update(self, delta_seconds, movement, aim, *, dash=False, movement_speed_mps=None,
               movement_end_speed_mps=None, face_movement=True):
        if not isfinite(self.speed_multiplier) or self.speed_multiplier <= 0:
            raise ValueError("이동 배율은 양수 유한값이어야 한다.")
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("갱신 시간은 0 이상의 유한한 초 단위여야 한다.")
        if movement_speed_mps is not None and (not isfinite(movement_speed_mps) or movement_speed_mps < 0):
            raise ValueError("이동 속도는 0 이상의 유한한 m/s 값이다.")
        if movement_end_speed_mps is not None and (movement_speed_mps is None
                or not isfinite(movement_end_speed_mps) or movement_end_speed_mps < 0):
            raise ValueError("구간 종료 속도에는 유한한 이동 속도 재정의가 필요하다.")
        movement, aim = unit_vector(movement), unit_vector(aim)
        remaining, traveled = delta_seconds, 0.0
        if self.boost_preparing:
            elapsed = min(remaining, self.boost_prepare_remaining_seconds)
            traveled += self._advance_regular(elapsed, movement, aim, dash, movement_speed_mps,
                                             movement_end_speed_mps, face_movement)
            remaining -= elapsed
            self.boost_prepare_remaining_seconds = max(0, self.boost_prepare_remaining_seconds - elapsed)
            if self.boost_prepare_remaining_seconds < 1e-10:
                self.boost_prepare_remaining_seconds = 0
                self._start_boost()
            else:
                self.speed_mps = traveled / delta_seconds if delta_seconds else 0
                return
        if self.boost_remaining_seconds > 0:
            self._last_movement = (0.0, 0.0)
            elapsed = min(remaining, self.boost_remaining_seconds)
            resume_speed = (self.settings.dash_speed_mps if dash else self.settings.run_speed_mps) if any(movement) else 0
            traveled += self._move(self.boost_direction, self._advance_boost_speed(resume_speed, elapsed), elapsed)
            remaining -= elapsed
            self.boost_remaining_seconds = max(0.0, self.boost_remaining_seconds - elapsed)
            self._set_movement_speed(self._boost_speed_mps)
            if self.boost_remaining_seconds < 1e-10:
                self.boost_remaining_seconds = 0.0
                self._set_movement_speed(resume_speed)
            if any(aim):
                self.facing = aim
        if self.boost_remaining_seconds > 0:
            self.state = "boost"
        else:
            traveled += self._advance_regular(remaining, movement, aim, dash, movement_speed_mps,
                                             movement_end_speed_mps, face_movement)
        self.speed_mps = traveled / delta_seconds if delta_seconds else 0.0


class LocomotionPlayback:
    """논리 상태 전환 즉시 모션을 선택하고 재생 종료 잔여 시간을 다음 반복에 넘긴다."""

    def __init__(self, clips, *, transition_seconds=0.12):
        if not isfinite(transition_seconds) or transition_seconds <= 0:
            raise ValueError("전환 시간은 양수 초 단위여야 한다.")
        self.clips = clips
        self.transition_seconds = transition_seconds
        for motion in ("idle_loop", "dash_loop", "boost_loop"):
            if any(f"{motion}/{direction}" not in clips for direction in SCREEN_DIRECTIONS):
                raise ValueError(f"8방향 반복 클립 누락: {motion}")
        self.reset()

    def reset(self):
        self.state = "idle"
        self.motion = "idle_loop"
        self.elapsed_seconds = 0.0
        self.direction = "se"

    @property
    def clip_name(self):
        return f"{self.motion}/{self.direction}"

    @property
    def frame_index(self):
        clip = self.clips[self.clip_name]
        if self.motion.endswith("_loop"):
            return clip.frame_at(self.elapsed_seconds)
        phase = min(1.0, self.elapsed_seconds / self.transition_seconds)
        return min(len(clip.frames) - 1, int(phase * len(clip.frames)))

    def update(self, state, direction, delta_seconds, *, loop_speed=1.0):
        if state not in ("idle", "dash", "boost") or direction not in SCREEN_DIRECTIONS:
            raise ValueError("지원하지 않는 이동 상태·방향이다.")
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("재생 시간은 0 이상의 유한한 초 단위다.")
        if not isfinite(loop_speed) or loop_speed <= 0:
            raise ValueError("반복 재생 속도는 양수여야 한다.")
        self.direction = direction
        if state != self.state:
            transition = f"{self.state}_to_{state}"
            self.motion = transition if f"{transition}/{direction}" in self.clips else f"{state}_loop"
            self.elapsed_seconds = 0.0
            self.state = state
        self.elapsed_seconds += delta_seconds * (loop_speed if self.motion.endswith("_loop") else 1)
        if not self.motion.endswith("_loop") and self.elapsed_seconds >= self.transition_seconds:
            self.elapsed_seconds = (self.elapsed_seconds - self.transition_seconds) * loop_speed
            self.motion = f"{self.state}_loop"
