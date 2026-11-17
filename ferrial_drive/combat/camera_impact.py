"""명중 방향의 짧은 화면 충격. 조준·카메라 추적·게임 시간과 독립이다."""

from math import cos, exp, hypot, isfinite, tau


class CameraImpact:
    def __init__(self, *, enabled=True, amplitude_pixels=3, duration_seconds=0.1,
                 overdrive_amplitude_pixels=None, frequency_hz=12, damping=1.8):
        if overdrive_amplitude_pixels is None:
            overdrive_amplitude_pixels = amplitude_pixels
        if (type(enabled) is not bool or not isfinite(amplitude_pixels) or amplitude_pixels < 0
                or not isfinite(overdrive_amplitude_pixels) or overdrive_amplitude_pixels < 0
                or not isfinite(duration_seconds) or duration_seconds <= 0
                or not isfinite(frequency_hz) or frequency_hz <= 0
                or not isfinite(damping) or damping < 0):
            raise ValueError("카메라 충격은 0 이상 진폭·감쇠와 양수 초 단위 수명·Hz 진동수가 필요하다.")
        self.enabled = enabled
        self.amplitude_pixels = amplitude_pixels
        self.overdrive_amplitude_pixels = overdrive_amplitude_pixels
        self.duration_seconds = duration_seconds
        self.frequency_hz = frequency_hz
        self.damping = damping
        self.reset()

    def reset(self):
        self.elapsed_seconds = self.duration_seconds
        self.direction = (0, 0)
        self.last_strike_id = None
        self.active_amplitude_pixels = 0

    def trigger(self, strike_id, direction, *, overdrive=False, amplitude_pixels=None):
        if len(direction) != 2 or not all(map(isfinite, direction)):
            raise ValueError("카메라 충격 방향은 유한한 2차원 벡터여야 한다.")
        if amplitude_pixels is not None and (not isfinite(amplitude_pixels) or amplitude_pixels < 0):
            raise ValueError("명중별 카메라 충격은 0 이상의 유한한 픽셀 값이다.")
        length = hypot(*direction)
        if not self.enabled or not length or strike_id == self.last_strike_id:
            return
        # 같은 타격의 다중 표적은 한 번만 반응하고 새 타격도 진폭을 합산하지 않는다.
        self.last_strike_id = strike_id
        self.direction = tuple(value / length for value in direction)
        self.active_amplitude_pixels = (amplitude_pixels if amplitude_pixels is not None else
                                        self.overdrive_amplitude_pixels if overdrive else self.amplitude_pixels)
        self.elapsed_seconds = 0

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("카메라 충격 갱신 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        self.elapsed_seconds = min(self.duration_seconds, self.elapsed_seconds + delta_seconds)

    @property
    def offset_pixels(self):
        progress = self.elapsed_seconds / self.duration_seconds
        if not self.enabled or progress >= 1 - 1e-9:
            return (0, 0)
        # 감쇠 반동 뒤 위치·속도가 모두 0에 닿도록 종료 구간을 부드럽게 닫는다.
        envelope = exp(-self.damping * progress) * (1 - progress) ** 2
        strength = self.active_amplitude_pixels * envelope * cos(tau * self.frequency_hz * self.elapsed_seconds)
        return tuple(value * strength for value in self.direction)
