"""포인터·입력 판정과 분리된 패널 자동 숨김·전환 상태."""

from math import isfinite

from ..animation import ScalarAnimation


class AutoHidePanel:
    def __init__(self, hide_delay_seconds, duration_seconds, slide_pixels):
        if not all(isfinite(value) and value >= 0 for value in
                   (hide_delay_seconds, duration_seconds, slide_pixels)):
            raise ValueError("패널 대기 시간·전환 시간·이동량은 0 이상의 유한한 값이어야 한다.")
        self.hide_delay_seconds = hide_delay_seconds
        self.duration_seconds = duration_seconds
        self.slide_pixels = slide_pixels
        self.hide()

    def hide(self):
        self.animation = ScalarAnimation(0, 0, 0)
        self.remaining_seconds = 0.0

    @property
    def opacity(self):
        return self.animation.value

    @property
    def offset_y(self):
        return self.slide_pixels * (1 - self.opacity)

    @property
    def interactive(self):
        return self.animation.finished and self.animation.end_value == 1

    def _request(self, value):
        if self.animation.end_value != value:
            start = self.opacity
            self.animation = ScalarAnimation(start, value, self.duration_seconds * abs(value - start))

    def update(self, delta_seconds, engaged):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("패널 갱신 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        if engaged:
            self.remaining_seconds = self.hide_delay_seconds
            self._request(1)
            self.animation.update(delta_seconds)
            return
        # 한 프레임에 대기 만료와 퇴장이 겹쳐도 남은 시간만 퇴장에 사용한다.
        holding_seconds = min(delta_seconds, self.remaining_seconds)
        self.animation.update(holding_seconds)
        self.remaining_seconds = max(0.0, self.remaining_seconds - holding_seconds)
        if self.remaining_seconds == 0:
            self._request(0)
        self.animation.update(delta_seconds - holding_seconds)
