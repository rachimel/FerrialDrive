"""조준 방향의 보간과 여유각 뒤에 시작하는 하체 추종. 단위는 도·초다."""

from dataclasses import dataclass
from math import ceil, expm1, isfinite


def angle_delta_degrees(target, current):
    return (target - current + 180) % 360 - 180


@dataclass(frozen=True)
class AimFollowSettings:
    upper_response_seconds: float
    lower_response_seconds: float
    lower_start_degrees: float = 45.0
    settle_degrees: float = 0.1

    def __post_init__(self):
        values = (self.upper_response_seconds, self.lower_response_seconds,
                  self.lower_start_degrees, self.settle_degrees)
        if not all(isfinite(value) and value > 0 for value in values):
            raise ValueError("추종 시간과 각도는 양수 유한값이어야 한다.")
        if not self.settle_degrees < self.lower_start_degrees < 180:
            raise ValueError("정렬 오차 < 하체 추종 시작각 < 180도여야 한다.")


class AimFollow:
    def __init__(self, settings, *, yaw_degrees=0.0):
        self.settings = settings
        self.reset(yaw_degrees)

    def reset(self, yaw_degrees=0.0):
        if not isfinite(yaw_degrees):
            raise ValueError("초기 방향은 유한한 도 단위여야 한다.")
        self.upper_yaw_degrees = yaw_degrees % 360
        self.lower_yaw_degrees = yaw_degrees % 360
        self.lower_following = False

    @property
    def relative_yaw_degrees(self):
        return angle_delta_degrees(self.upper_yaw_degrees, self.lower_yaw_degrees)

    def update(self, delta_seconds, target_yaw_degrees):
        if not isfinite(delta_seconds) or delta_seconds < 0 or not isfinite(target_yaw_degrees):
            raise ValueError("경과 시간은 0 이상의 유한한 초, 목표는 유한한 도 단위여야 한다.")
        if delta_seconds == 0:
            return
        # 여유각 통과·정렬 종료를 작은 시간 구간에서 판별한다.
        steps = max(1, ceil(delta_seconds * 240))
        step_seconds = delta_seconds / steps
        upper_blend = -expm1(-step_seconds / self.settings.upper_response_seconds)
        lower_blend = -expm1(-step_seconds / self.settings.lower_response_seconds)
        for _ in range(steps):
            self.upper_yaw_degrees = (self.upper_yaw_degrees + angle_delta_degrees(
                target_yaw_degrees, self.upper_yaw_degrees) * upper_blend) % 360
            difference = self.relative_yaw_degrees
            if abs(difference) > self.settings.lower_start_degrees:
                self.lower_following = True
            if self.lower_following:
                self.lower_yaw_degrees = (self.lower_yaw_degrees + difference * lower_blend) % 360
                # 시작각 안에 재진입해도 정렬될 때까지 추종을 이어간다.
                if (abs(self.relative_yaw_degrees) <= self.settings.settle_degrees
                        and abs(angle_delta_degrees(target_yaw_degrees,
                                                    self.upper_yaw_degrees)) <= self.settings.settle_degrees):
                    self.lower_following = False
