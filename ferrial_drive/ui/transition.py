"""두 화면의 이동·투명도 값. 재입력 정책은 사용하는 쪽에서 결정한다."""

from dataclasses import dataclass

from ..animation import ScalarAnimation


@dataclass(frozen=True)
class ScenePose:
    opacity: float
    offset_x: float


class SceneTransition:
    def __init__(self, first: str, second: str, initial: str,
                 duration_seconds: float, slide_pixels: float):
        if first == second or initial not in (first, second):
            raise ValueError("서로 다른 두 장면과 유효한 최초 장면이 필요하다.")
        self.first, self.second = first, second
        self.duration_seconds = duration_seconds
        self.slide_pixels = slide_pixels
        value = 0.0 if initial == first else 1.0
        self.animation = ScalarAnimation(value, value, 0)

    @property
    def active(self):
        return not self.animation.finished

    @property
    def target(self):
        return self.first if self.animation.end_value == 0 else self.second

    def request(self, scene: str):
        if scene not in (self.first, self.second):
            raise ValueError(f"전환 대상 장면 없음: {scene}")
        value = 0.0 if scene == self.first else 1.0
        if scene == self.target:
            return
        start = self.animation.value
        self.animation = ScalarAnimation(start, value, self.duration_seconds * abs(value - start))

    def update(self, delta_seconds):
        self.animation.update(delta_seconds)

    def pose(self, scene: str) -> ScenePose:
        amount = self.animation.value
        if scene == self.first:
            return ScenePose(1 - amount, -self.slide_pixels * amount)
        if scene == self.second:
            return ScenePose(amount, self.slide_pixels * (1 - amount))
        raise ValueError(f"장면 없음: {scene}")
