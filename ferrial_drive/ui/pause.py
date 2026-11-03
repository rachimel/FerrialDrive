"""일시정지의 표시 수명. 게임 시간과 입력 차단은 실행부에서 연결한다."""

from math import isfinite

from ..animation import ScalarAnimation


class PauseState:
    def __init__(self, duration_seconds):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("일시정지 전환 시간은 양수인 유한한 초 단위 값이어야 한다.")
        self.duration_seconds = duration_seconds
        self.reset()

    def reset(self):
        self.opened = False
        self.animation = ScalarAnimation(0, 0, 0)

    @property
    def transitioning(self):
        return not self.animation.finished

    @property
    def blocking(self):
        return self.opened or self.transitioning

    @property
    def opacity(self):
        return self.animation.value

    def request(self, opened):
        if self.transitioning or self.opened == opened:
            return
        self.opened = opened
        self.animation = ScalarAnimation(self.opacity, float(opened), self.duration_seconds)

    def update(self, delta_seconds):
        self.animation.update(delta_seconds)
