"""흡수 Trail·패널 스캔·대화창 개폐의 시간 상태. 입력·렌더러와 분리한다."""

from dataclasses import dataclass
from math import cos, isfinite, tau

from ferrial_drive.animation import ScalarAnimation


def subtle_flicker(elapsed_seconds, *, minimum_opacity=0.5, period_seconds=0.5,
                   dim_seconds=0.25, seed=1):
    """고정 주기로 평소 밝기와 최소 불투명도를 교대한다. seed는 위상만 나눈다."""
    if (not all(map(isfinite, (elapsed_seconds, minimum_opacity, period_seconds, dim_seconds)))
            or elapsed_seconds < 0 or not 0 <= minimum_opacity <= 1
            or not 0 < dim_seconds < period_seconds):
        raise ValueError("밝기 시간·범위·주기가 유효하지 않다.")
    phase_seconds = (seed % 16) / 16 * period_seconds
    position = (elapsed_seconds + phase_seconds) % period_seconds
    return minimum_opacity if position < dim_seconds else 1


def breathing_opacity(elapsed_seconds, *, period_seconds=2.4, minimum_opacity=0.65):
    if (not all(map(isfinite, (elapsed_seconds, period_seconds, minimum_opacity)))
            or elapsed_seconds < 0 or period_seconds <= 0 or not 0 <= minimum_opacity <= 1):
        raise ValueError("호흡 시간·주기·밝기 범위가 유효하지 않다.")
    return minimum_opacity + (1 - minimum_opacity) * (0.5 + 0.5 * cos(tau * elapsed_seconds / period_seconds))


class IndicatorFade:
    def __init__(self, enter_seconds=0.06, exit_seconds=0.05):
        if not all(isfinite(value) and value > 0 for value in (enter_seconds, exit_seconds)):
            raise ValueError("인디케이터 전환 시간은 양수인 초 단위 값이어야 한다.")
        self.enter_seconds, self.exit_seconds = enter_seconds, exit_seconds
        self.reset(False)

    def reset(self, visible, *, animate=False):
        self.visible = bool(visible)
        self.animation = ScalarAnimation(0 if animate else float(visible), float(visible),
                                         self.enter_seconds if visible else self.exit_seconds)

    def request(self, visible):
        if self.visible != bool(visible):
            self.visible = bool(visible)
            self.animation = ScalarAnimation(self.opacity, float(visible),
                                             self.enter_seconds if visible else self.exit_seconds)

    def update(self, delta_seconds):
        self.animation.update(delta_seconds)

    @property
    def opacity(self):
        return self.animation.value


@dataclass(frozen=True)
class HealthFlashVisual:
    start_ratio: float
    end_ratio: float
    opacity: float


class HealthDamageFlash:
    """각 피해의 실제 HP 감소 구간만 잠시 강조한다. 빨간 Trail과 독립이다."""
    def __init__(self, hold_seconds=0, fade_seconds=0.08, *, attack_seconds=0.02):
        if (not all(map(isfinite, (hold_seconds, fade_seconds, attack_seconds)))
                or hold_seconds < 0 or fade_seconds <= 0 or attack_seconds <= 0):
            raise ValueError("HP flash 유지 시간은 0 이상, 등장/퇴장 시간은 양수인 초 단위 값이어야 한다.")
        self.hold_seconds, self.fade_seconds = hold_seconds, fade_seconds
        self.attack_seconds = attack_seconds
        self.clear()

    def clear(self):
        self._flashes = []

    def trigger(self, previous_ratio, current_ratio):
        if not all(isfinite(value) and 0 <= value <= 1 for value in (previous_ratio, current_ratio)):
            raise ValueError("HP flash 비율은 0~1의 유한한 값이어야 한다.")
        if current_ratio < previous_ratio:
            self._flashes.append((current_ratio, previous_ratio, 0))

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("HP flash 갱신 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        duration = self.attack_seconds + self.hold_seconds + self.fade_seconds
        self._flashes = [(low, high, elapsed + delta_seconds) for low, high, elapsed in self._flashes
                         if elapsed + delta_seconds + 1e-9 < duration]

    @property
    def visuals(self):
        return tuple(HealthFlashVisual(low, high, min(elapsed / self.attack_seconds,
                     1 - max(0, elapsed - self.attack_seconds - self.hold_seconds) / self.fade_seconds))
                     for low, high, elapsed in self._flashes)


@dataclass(frozen=True)
class ScanlineVisual:
    line_offset_pixels: float = 0
    highlight_travel_pixels: float = 0
    elapsed_seconds: float = 0


class ScanlineMotion:
    def __init__(self, spacing_pixels, slow_speed_pixels_per_second, fast_speed_pixels_per_second):
        if (not all(map(isfinite, (spacing_pixels, slow_speed_pixels_per_second, fast_speed_pixels_per_second)))
                or spacing_pixels <= 0 or not 0 <= slow_speed_pixels_per_second < fast_speed_pixels_per_second):
            raise ValueError("Scanline 간격은 양수이며 밝은 띠의 속도가 기본 스크롤보다 커야 한다.")
        self.spacing_pixels = spacing_pixels
        self.slow_speed_pixels_per_second = slow_speed_pixels_per_second
        self.fast_speed_pixels_per_second = fast_speed_pixels_per_second
        self.reset()

    def reset(self):
        self.visual = ScanlineVisual()

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("Scanline 갱신 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        self.visual = ScanlineVisual(
            (self.visual.line_offset_pixels + self.slow_speed_pixels_per_second * delta_seconds) % self.spacing_pixels,
            self.visual.highlight_travel_pixels + self.fast_speed_pixels_per_second * delta_seconds,
            self.visual.elapsed_seconds + delta_seconds)


@dataclass(frozen=True)
class DialoguePanelVisual:
    height_ratio: float = 1
    width_ratio: float = 1
    text_opacity: float = 1
    flash_opacity: float = 0


class DialoguePanelMotion:
    """중앙 세로 펼침 후 글자 표시, TV 종료처럼 면→가로선→점으로 닫는다."""
    def __init__(self, open_seconds=0.2, text_seconds=0, collapse_seconds=0.05,
                 line_seconds=0.03, dot_seconds=0.02):
        durations = (open_seconds, text_seconds, collapse_seconds, line_seconds, dot_seconds)
        if (not all(isfinite(value) and value > 0 for value in (open_seconds, collapse_seconds, line_seconds, dot_seconds))
                or not isfinite(text_seconds) or text_seconds < 0):
            raise ValueError("대화창 펼침·종료 시간은 양수이며 글자 등장 시간은 0 이상의 초 단위 값이어야 한다.")
        self.open_seconds, self.text_seconds, self.collapse_seconds, self.line_seconds, self.dot_seconds = durations
        self.reset()

    def reset(self, opened=False, *, animate=False):
        self.opened = bool(opened)
        self.phase = "open" if opened else "closed"
        self.elapsed_seconds = 0
        self._start = DialoguePanelVisual() if opened else DialoguePanelVisual(0, 0, 0, 0)
        if opened and animate:
            self.phase = "opening"
            self._start = DialoguePanelVisual(0, 1, 0, 0)

    def request(self, opened):
        opened = bool(opened)
        if self.opened == opened:
            return
        self._start = self.visual
        self.opened = opened
        self.elapsed_seconds = 0
        self.phase = "opening" if opened else "closing"

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("대화창 갱신 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        self.elapsed_seconds += delta_seconds
        if self.phase == "opening" and self.elapsed_seconds + 1e-9 >= self.open_seconds + self.text_seconds:
            self.phase = "open"
        elif self.phase == "closing" and self.elapsed_seconds + 1e-9 >= self.collapse_seconds + self.line_seconds + self.dot_seconds:
            self.phase = "closed"

    @property
    def visual(self):
        if self.phase == "closed":
            return DialoguePanelVisual(0, 0, 0, 0)
        if self.phase == "open":
            return DialoguePanelVisual()
        elapsed = self.elapsed_seconds
        if self.phase == "opening":
            amount = 1 - (1 - min(1, elapsed / self.open_seconds)) ** 3
            height = self._start.height_ratio + (1 - self._start.height_ratio) * amount
            start_width = self._start.width_ratio or 1
            width = start_width + (1 - start_width) * amount
            text = (max(0, min(1, (elapsed - self.open_seconds) / self.text_seconds))
                    if self.text_seconds else float(elapsed >= self.open_seconds))
            return DialoguePanelVisual(height, width, text)
        if elapsed < self.collapse_seconds:
            amount = elapsed / self.collapse_seconds
            height = self._start.height_ratio * (1 - amount) ** 2
            return DialoguePanelVisual(height, self._start.width_ratio, 0, 0.85 * amount)
        elapsed -= self.collapse_seconds
        if elapsed < self.line_seconds:
            width = self._start.width_ratio * (1 - elapsed / self.line_seconds) ** 2
            return DialoguePanelVisual(0, width, 0, 0.85)
        opacity = max(0, 1 - (elapsed - self.line_seconds) / self.dot_seconds)
        return DialoguePanelVisual(0, 0, 0, 0.85 * opacity)


def _bezier(points, amount):
    while len(points) > 1:
        points = tuple((a[0] + (b[0] - a[0]) * amount,
                        a[1] + (b[1] - a[1]) * amount)
                       for a, b in zip(points, points[1:]))
    return points[0]


@dataclass
class AbsorptionTrail:
    start: tuple[float, float]
    icon: tuple[float, float]
    destination: tuple[float, float]
    duration_seconds: float
    elapsed_seconds: float = 0.0

    def point(self, amount):
        amount = max(0.0, min(1.0, amount))
        sx, sy = self.start
        ix, iy = self.icon
        dx, dy = self.destination
        if amount <= 0.72:
            return _bezier(((sx, sy), (sx + 90, sy + 100),
                            (ix - 90, iy - 110), (ix, iy)), amount / 0.72)
        return _bezier(((ix, iy), (ix + 55, iy + 55),
                        (dx - 75, dy + 30), (dx, dy)), (amount - 0.72) / 0.28)

    @property
    def progress(self):
        return self.elapsed_seconds / self.duration_seconds


class EnergyAbsorption:
    def __init__(self, duration_seconds=0.85):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("흡수 효과 시간은 양수인 초 단위 값이어야 한다.")
        self.duration_seconds = duration_seconds
        self.trails = []

    def add(self, start, icon, destination):
        if not all(isfinite(value) for point in (start, icon, destination) for value in point):
            raise ValueError("흡수 효과 좌표는 유한한 화면 픽셀이어야 한다.")
        self.trails.append(AbsorptionTrail(tuple(start), tuple(icon), tuple(destination),
                                          self.duration_seconds))
        # 빠른 반복 입력에서도 표시 효과의 수를 제한한다.
        self.trails = self.trails[-24:]

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("효과 갱신 시간은 0 이상의 초 단위 값이어야 한다.")
        for trail in self.trails:
            trail.elapsed_seconds += delta_seconds
        self.trails = [trail for trail in self.trails if trail.progress < 1.3]

    def clear(self):
        self.trails.clear()
