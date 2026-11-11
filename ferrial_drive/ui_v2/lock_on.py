"""록온 표시 시간·곡선·외곽 경로. 획득 규칙과 렌더러에는 의존하지 않는다."""

from dataclasses import dataclass
from math import floor, isfinite, pi, sin


def cubic(t, x1, y1, x2, y2):
    if t <= 0 or t >= 1:
        return max(0, min(1, t))
    def sample(u, a, b):
        return 3 * (1 - u) ** 2 * u * a + 3 * (1 - u) * u * u * b + u ** 3
    low, high = 0, 1
    for _ in range(32):
        u = (low + high) / 2
        if sample(u, x1, x2) < t:
            low = u
        else:
            high = u
    return sample((low + high) / 2, y1, y2)


def emphasized(t):
    """Flutter ThreePointCubic의 두 구간을 각각 정규화한다."""
    mx, my = 0.166666, 0.4
    if t < mx:
        return cubic(t / mx, 0.05 / mx, 0, 0.133333 / mx, 0.06 / my) * my
    return my + cubic((t - mx) / (1 - mx), (0.208333 - mx) / (1 - mx),
                      (0.82 - my) / (1 - my), (0.25 - mx) / (1 - mx), 1) * (1 - my)


def elastic_out(t):
    if t <= 0 or t >= 1:
        return max(0, min(1, t))
    return 2 ** (-10 * t) * sin((t - 0.1) * 2 * pi / 0.4) + 1


def outline_point(points, position):
    index = floor(position)
    a, b = points[index % 4], points[(index + 1) % 4]
    amount = position - index
    return tuple(x + (y - x) * amount for x, y in zip(a, b))


def outline_segment(points, start, length=0.65):
    end = start + length
    return (outline_point(points, start),
            *(points[index % 4] for index in range(floor(start) + 1, floor(end) + 1)),
            outline_point(points, end))


@dataclass(frozen=True)
class LockOnVisual:
    target_id: str
    body: object
    angle_degrees: float = 45
    scale: float = 1
    opacity: float = 1
    label_progress: float = 1
    border_position: float = 3.5


@dataclass
class LockOnTrack:
    target_id: str
    body: object
    age: float = 0
    leaving: bool = False
    exit_age: float = 0
    exit_start_angle_degrees: float = 45
    exit_start_scale: float = 1


class LockOnMotion:
    def __init__(self, enter_seconds=0.4, label_seconds=0.2, exit_seconds=0.25,
                 move_seconds=0.4, hold_seconds=0.25, start_scale=0.25, exit_scale=1.5):
        values = (enter_seconds, label_seconds, exit_seconds, move_seconds, hold_seconds, start_scale, exit_scale)
        if not all(isfinite(value) and value > 0 for value in values) or start_scale >= 1 or exit_scale <= 1:
            raise ValueError("록온 시간은 양수이며 등장 배율은 1 미만, 퇴장 배율은 1 초과여야 한다.")
        self.enter_seconds, self.label_seconds, self.exit_seconds = values[:3]
        self.move_seconds, self.hold_seconds, self.start_scale, self.exit_scale = values[3:]
        self.tracks = []
        self.selected_id = None

    def reset(self, target_id, body):
        self.tracks.clear()
        self.selected_id = None
        self.select(target_id, body)

    def select(self, target_id, body):
        if target_id == self.selected_id:
            self.update_body(body)
            return
        for track, visual in zip(self.tracks, self.visuals):
            if not track.leaving:
                track.leaving = True
                track.exit_start_angle_degrees = visual.angle_degrees
                track.exit_start_scale = visual.scale
        self.selected_id = target_id
        if target_id is not None and body is not None:
            self.tracks = [track for track in self.tracks if track.target_id != target_id]
            self.tracks.append(LockOnTrack(target_id, body))

    def update_body(self, body):
        for track in self.tracks:
            if not track.leaving and body is not None:
                track.body = body

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("록온 갱신 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        for track in self.tracks:
            if not track.leaving:
                track.age += delta_seconds
            else:
                track.exit_age += delta_seconds
        self.tracks = [track for track in self.tracks if not track.leaving or
                       track.exit_age + 1e-9 < self.exit_seconds]

    @property
    def visuals(self):
        result = []
        for track in self.tracks:
            progress = max(0, min(1, track.age / self.enter_seconds))
            angle = 45 * elastic_out(progress)
            scale = self.start_scale + (1 - self.start_scale) * emphasized(progress)
            opacity = 1
            label = max(0, min(1, (track.age - self.enter_seconds) / self.label_seconds))
            if track.leaving:
                label = 0
                t = min(1, track.exit_age / self.exit_seconds)
                angle = track.exit_start_angle_degrees * (1 + cubic(t, 0.42, 0, 0.58, 1))
                scale = track.exit_start_scale * (1 + (self.exit_scale - 1) * emphasized(t))
                opacity = 1 - t
            patrol_age = max(0, track.age - self.enter_seconds - self.label_seconds)
            cycle = self.move_seconds + self.hold_seconds
            step, local = divmod(patrol_age, cycle)
            move = cubic(min(1, local / self.move_seconds), 0.42, 0, 0.58, 1)
            result.append(LockOnVisual(track.target_id, track.body, angle, scale, opacity,
                                       label, 3.5 + 2 * (step + move)))
        return tuple(result)
