"""흡수 Trail·패널 스캔·대화창 개폐의 시간 상태. 입력·렌더러와 분리한다."""

from dataclasses import dataclass, field
from math import cos, exp, hypot, isfinite, sin, tau
from random import Random

from ferrial_drive.animation import ScalarAnimation


def subtle_flicker(elapsed_seconds, *, minimum_opacity=0.9, period_seconds=0.12,
                   dim_seconds=0.06, transition_seconds=0.06):
    """공통 주기로 밝기를 교대하고 전환 구간만 부드럽게 보간한다."""
    if (not all(map(isfinite, (elapsed_seconds, minimum_opacity, period_seconds, dim_seconds, transition_seconds)))
            or elapsed_seconds < 0 or not 0 <= minimum_opacity <= 1
            or not 0 < dim_seconds < period_seconds
            or not 0 < transition_seconds <= min(dim_seconds, period_seconds - dim_seconds)):
        raise ValueError("밝기 시간·범위·주기가 유효하지 않다.")
    position = elapsed_seconds % period_seconds
    bright_seconds = period_seconds - dim_seconds
    dimming = position < bright_seconds
    end_seconds = bright_seconds if dimming else period_seconds
    progress = max(0, (position - end_seconds + transition_seconds) / transition_seconds)
    progress = progress * progress * (3 - 2 * progress)
    change = (1 - minimum_opacity) * progress
    return 1 - change if dimming else minimum_opacity + change


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
class HealthHitVisual:
    offset_pixels: tuple[float, float] = (0, 0)
    velocity_pixels_per_second: tuple[float, float] = (0, 0)


def damped_oscillation(time, duration, frequency_hz, damping):
    """진폭 상한 안의 지수 감쇠와 정확한 속도. 종료점은 위치·속도 모두 0이다."""
    if time >= duration:
        return 0, 0
    t = time / duration
    decay, remaining = exp(-damping * t), 1 - t
    envelope = decay * remaining ** 2
    derivative = -decay * (damping * remaining ** 2 + 2 * remaining) / duration
    angle, omega = tau * frequency_hz * time, tau * frequency_hz
    return envelope * sin(angle), derivative * sin(angle) + envelope * omega * cos(angle)


class HealthHitMotion:
    """피격마다 제한된 진폭으로 재시작하는 감쇠 진동. 좌표는 화면 px다."""
    def __init__(self, duration_seconds=0.28, frequency_hz=18, max_offset_pixels=(0, 4), damping=1.8):
        if (not all(isfinite(value) and value > 0 for value in (duration_seconds, frequency_hz))
                or len(max_offset_pixels) != 2
                or not all(isfinite(value) and value >= 0 for value in max_offset_pixels)):
            raise ValueError("피격 시간·진동수는 양수이며 최대 오프셋은 0 이상의 화면 px여야 한다.")
        self.duration_seconds, self.frequency_hz = duration_seconds, frequency_hz
        self.max_offset_pixels = tuple(max_offset_pixels)
        if not isfinite(damping) or damping < 0:
            raise ValueError('피격 감쇠 계수는 0 이상의 유한한 값이어야 한다.')
        self.damping = damping
        self.clear()

    def clear(self):
        self.elapsed_seconds = self.duration_seconds

    def trigger(self):
        self.elapsed_seconds = 0

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("피격 갱신 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        self.elapsed_seconds = min(self.duration_seconds, self.elapsed_seconds + delta_seconds)

    @property
    def visual(self):
        if self.elapsed_seconds >= self.duration_seconds:
            return HealthHitVisual()
        offset, velocity = damped_oscillation(self.elapsed_seconds, self.duration_seconds,
                                             self.frequency_hz, self.damping)
        return HealthHitVisual(tuple(limit * offset for limit in self.max_offset_pixels),
                               tuple(limit * velocity for limit in self.max_offset_pixels))


class EnergyTintMotion:
    """논리 충전량을 바꾸지 않고 표시 색의 비율만 시간 보간한다."""
    def __init__(self, duration_seconds=0.24):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError('에너지 색 전환 시간은 양수여야 한다.')
        self.duration_seconds = duration_seconds
        self.reset(0)

    def reset(self, ratio):
        if not isfinite(ratio) or not 0 <= ratio <= 1:
            raise ValueError('에너지 색 비율은 0~1이어야 한다.')
        self.animation = ScalarAnimation(ratio, ratio, self.duration_seconds)

    def request(self, ratio):
        if not isfinite(ratio) or not 0 <= ratio <= 1:
            raise ValueError('에너지 색 비율은 0~1이어야 한다.')
        if ratio != self.animation.end_value:
            self.animation = ScalarAnimation(self.ratio, ratio, self.duration_seconds)

    def update(self, delta_seconds):
        self.animation.update(delta_seconds)

    @property
    def ratio(self):
        return self.animation.value


class EnergyRecoveryFlash:
    def __init__(self, duration_seconds=0.16):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError('회복 flash 시간은 양수여야 한다.')
        self.duration_seconds = duration_seconds
        self.elapsed_seconds = duration_seconds

    def trigger(self):
        self.elapsed_seconds = 0

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError('회복 flash 갱신 시간은 0 이상이어야 한다.')
        self.elapsed_seconds = min(self.duration_seconds, self.elapsed_seconds + delta_seconds)

    @property
    def opacity(self):
        return (1 - self.elapsed_seconds / self.duration_seconds) ** 2


@dataclass(frozen=True)
class OverdriveVisual:
    opacity: float = 0
    spread: float = 1
    flash: float = 0
    entry_seconds: float = 1


class OverdriveMotion:
    """글자 확산과 등장 반짝임. 퇴장 때 위치는 유지하고 투명도만 줄인다."""
    def __init__(self, enter_seconds=0.42, exit_seconds=0.18, fade_in_seconds=0.065):
        if not all(isfinite(v) and v > 0 for v in (enter_seconds, exit_seconds, fade_in_seconds)):
            raise ValueError('Overdrive 등장·퇴장 시간은 양수여야 한다.')
        self.enter_seconds, self.exit_seconds = enter_seconds, exit_seconds
        self.fade_in_seconds = fade_in_seconds
        self.reset(False)

    def reset(self, visible):
        self.visible = bool(visible)
        self.age = self.enter_seconds
        self.animation = ScalarAnimation(float(visible), float(visible), self.enter_seconds)

    def request(self, visible):
        if bool(visible) == self.visible:
            return
        self.visible = bool(visible)
        duration = self.fade_in_seconds if visible else self.exit_seconds
        self.animation = ScalarAnimation(self.animation.value, float(visible), duration)
        if visible:
            self.age = 0

    def update(self, delta_seconds):
        self.animation.update(delta_seconds)
        if self.visible:
            self.age = min(self.enter_seconds, self.age + delta_seconds)

    @property
    def visual(self):
        t = min(1, self.age / self.enter_seconds)
        spread = 0.16 + 0.84 * (1 - (1 - t) ** 3)
        flash = (1 - t) * (0.35 + 0.65 * sin(tau * t * 2.5) ** 2) if self.visible else 0
        return OverdriveVisual(self.animation.value, spread, flash, self.age)


@dataclass(frozen=True)
class UltimateReadyVisual:
    age: float = 0
    opacity: float = 1
    flash: float = 0


class UltimateReadyMotion:
    """준비 상태 진입 때 한 번 flash하고 강조선 시간을 유지한다."""
    def __init__(self, flash_seconds=0.28):
        self.flash = EnergyRecoveryFlash(flash_seconds)
        self.reset(False)

    def reset(self, ready):
        self.ready, self.age = bool(ready), 0
        self.flash.elapsed_seconds = self.flash.duration_seconds

    def request(self, ready):
        if ready and not self.ready:
            self.age = 0
            self.flash.trigger()
        if not ready:
            self.flash.elapsed_seconds = self.flash.duration_seconds
        self.ready = bool(ready)

    def update(self, delta_seconds):
        self.flash.update(delta_seconds)
        if self.ready:
            self.age += delta_seconds

    @property
    def visual(self):
        return UltimateReadyVisual(self.age, float(self.ready), self.flash.opacity)


class BoundaryParticleEmitter:
    """CPU에는 생성 요청의 주기만 보관한다. 입자별 상태는 GPU가 소유한다."""
    def __init__(self, rate_per_second=32):
        if not isfinite(rate_per_second) or rate_per_second <= 0:
            raise ValueError('경계 입자 발생률은 양수여야 한다.')
        self.rate_per_second, self.elapsed_seconds = rate_per_second, 0

    def update(self, delta_seconds, enabled):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError('경계 입자 갱신 시간은 0 이상이어야 한다.')
        if not enabled:
            self.elapsed_seconds = 0
            return 0
        # 긴 프레임 뒤 과도한 생성 요청이 한꺼번에 쌓이지 않도록 제한한다.
        self.elapsed_seconds += min(delta_seconds, 0.15)
        count = int(self.elapsed_seconds * self.rate_per_second)
        self.elapsed_seconds -= count / self.rate_per_second
        return count


@dataclass(frozen=True)
class DefeatedTargetVisual:
    target_id: str
    body: object
    opacity: float
    trailing_ratio: float
    current_ratio: float = 0


class DefeatedTargetMotion:
    """처치·선택 해제 후에도 HP바의 퇴장을 독립적으로 유지한다."""
    def __init__(self, duration_seconds=0.32):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError('처치 HP바 퇴장 시간은 양수여야 한다.')
        self.duration_seconds = duration_seconds
        self.tracks = []

    def trigger(self, target_id, body, trailing_ratio, current_ratio=0):
        if body is None:
            return
        self.tracks = [track for track in self.tracks if track['target_id'] != target_id]
        self.tracks.append(dict(target_id=target_id, body=body, trailing_ratio=trailing_ratio,
                                current_ratio=current_ratio, age=0))

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError('처치 HP바 갱신 시간은 0 이상이어야 한다.')
        for track in self.tracks:
            track['age'] += delta_seconds
        self.tracks = [track for track in self.tracks if track['age'] < self.duration_seconds]

    @property
    def visuals(self):
        result = []
        for track in self.tracks:
            t = min(1, track['age'] / self.duration_seconds)
            opacity = 1 - t * t * (3 - 2 * t)
            result.append(DefeatedTargetVisual(track['target_id'], track['body'], opacity,
                                               track['trailing_ratio'] * (1 - t * t), track['current_ratio']))
        return tuple(result)


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
    route_offsets: tuple[tuple[float, float], ...] = ()
    approach_side: int = -1
    path_points: tuple[tuple[float, float], ...] = field(init=False, repr=False)

    def __post_init__(self):
        # 생성 때만 곡선을 계산하고 매 프레임에는 고정 경로를 선형 조회한다.
        # 0.72 경유점은 200분할의 144번째 점으로 정확히 보존한다.
        self.path_points = tuple(self._curve_point(index / 200) for index in range(201))

    def point(self, amount):
        position = max(0.0, min(1.0, amount)) * 200
        index = min(199, int(position))
        a, b = self.path_points[index:index + 2]
        t = position - index
        return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t

    def _curve_point(self, amount):
        amount = max(0.0, min(1.0, amount))
        sx, sy = self.start
        ix, iy = self.icon
        dx, dy = self.destination
        first_leg = amount <= 0.72
        local = amount / 0.72 if first_leg else (amount - 0.72) / 0.28
        side = self.approach_side
        controls = (((sx, sy), (sx - side * 90, sy + 100), (ix + side * 90, iy - 110), (ix, iy))
                    if first_leg else ((ix, iy), (ix - side * 55, iy - 55), (dx + side * 75, dy - 30), (dx, dy)))
        x, y = _bezier(controls, local)
        if not self.route_offsets:
            return x, y
        offsets = self.route_offsets[:4] if first_leg else self.route_offsets[4:]
        # 사전 지정한 제어점을 사용한다. 생성 시 경로 번호만 무작위로 선택한다.
        dx, dy = _bezier(offsets, local)
        return x + dx, y + dy

    def ribbon(self, tail_fraction=0.3, samples=40):
        """꼬리→오브 순 좌표와 오브까지의 실제 거리에 따른 필압을 반환한다."""
        head = min(1, self.progress)
        tail = max(0, self.progress - tail_fraction)
        if tail >= head:
            return ()
        points = tuple(self.point(tail + (head - tail) * i / samples) for i in range(samples + 1))
        lengths = [0.0]
        for a, b in zip(points, points[1:]):
            lengths.append(lengths[-1] + hypot(b[0] - a[0], b[1] - a[1]))
        if lengths[-1] <= 1e-9:
            return ()
        fade = max(0, 1 - max(0, self.progress - 1) / tail_fraction)
        return tuple((point, (distance / lengths[-1]) ** 1.5 * fade)
                     for point, distance in zip(points, lengths))

    @property
    def progress(self):
        return self.elapsed_seconds / self.duration_seconds


DEFAULT_ABSORPTION_PROFILES = (
    ((30, -45), (-30, 30), (15, -15), (-15, -5)),
    ((-45, -20), (35, -50), (25, -30), (-10, -10)),
    ((55, 30), (20, -55), (-15, -20), (20, -5)),
    ((-30, 50), (-55, -15), (30, -10), (-20, -20)),
    ((65, -25), (-10, 45), (10, -35), (-25, -5)),
    ((-60, 5), (55, 25), (-20, -25), (15, -15)),
)


class EnergyAbsorption:
    def __init__(self, duration_seconds=0.85, *, paths_by_side=None, seed=None, tail_fraction=0.3):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("흡수 효과 시간은 양수인 초 단위 값이어야 한다.")
        self.duration_seconds = duration_seconds
        if not isfinite(tail_fraction) or not 0 < tail_fraction <= 1:
            raise ValueError("흡수 꼬리 비율은 0 초과 1 이하여야 한다.")
        self.tail_fraction = tail_fraction
        self.random = Random(seed)
        profiles = paths_by_side or {
            "left": DEFAULT_ABSORPTION_PROFILES,
            "right": tuple(tuple((-x, y) for x, y in profile) for profile in DEFAULT_ABSORPTION_PROFILES),
        }
        self.routes = {}
        for side, key in ((-1, "left"), (1, "right")):
            entries = profiles[key]
            if len(entries) != 6 or any(len(entry) != 4 or any(len(point) != 2
                    or not all(map(isfinite, point)) for point in entry) for entry in entries):
                raise ValueError("좌우 흡수 경로는 각각 6개이며 후보마다 유한한 제어점 4개가 필요하다.")
            self.routes[side] = tuple(((0, 0), tuple(a), tuple(b), (0, 0),
                                      (0, 0), tuple(c), tuple(d), (0, 0)) for a, b, c, d in entries)
        self.trails = []

    def add(self, start, icon, destination, *, approach_side=-1):
        if not all(isfinite(value) for point in (start, icon, destination) for value in point):
            raise ValueError("흡수 효과 좌표는 유한한 화면 픽셀이어야 한다.")
        if approach_side not in (-1, 1):
            raise ValueError("흡수 진입 방향은 왼쪽 -1 또는 오른쪽 1이어야 한다.")
        candidates = self.routes[approach_side]
        route = self.random.choice(candidates)
        if self.trails and route == self.trails[-1].route_offsets:
            route = candidates[(candidates.index(route) + 1) % len(candidates)]
        self.trails.append(AbsorptionTrail(tuple(start), tuple(icon), tuple(destination),
                                          self.duration_seconds, route_offsets=route, approach_side=approach_side))
        # 빠른 반복 입력에서도 표시 효과의 수를 제한한다.
        self.trails = self.trails[-24:]

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("효과 갱신 시간은 0 이상의 초 단위 값이어야 한다.")
        for trail in self.trails:
            trail.elapsed_seconds += delta_seconds
        self.trails = [trail for trail in self.trails if trail.progress < 1 + self.tail_fraction]

    def clear(self):
        self.trails.clear()
