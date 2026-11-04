"""로드아웃 전체의 화면 밖 이동·페이드. 진행 중 입력은 최신 목표 하나로 합친다."""

from dataclasses import dataclass
from math import isfinite

from ..animation import ScalarAnimation, ease_in_out_quint, linear


@dataclass(frozen=True)
class LoadoutVisual:
    outgoing_index: int
    incoming_index: int
    elapsed_seconds: float
    duration_seconds: float

    @property
    def moving(self):
        return (self.outgoing_index != self.incoming_index
                and self.elapsed_seconds < self.duration_seconds)

    def progress_before(self, seconds_ago=0):
        if self.duration_seconds == 0:
            return 1.0
        # 시간 진행률은 선형으로 두고 실제 퇴장·진입 구간에서만 easing한다.
        return linear((self.elapsed_seconds - seconds_ago) / self.duration_seconds)

    def pose(self, exit_distance, progress=None):
        """번호·무기 패널을 같은 위치·알파로 내보낸 뒤 세트를 바꿔 되돌린다."""
        if not self.moving:
            return 0.0, 1.0, self.incoming_index
        progress = self.progress_before() if progress is None else max(0.0, min(1.0, progress))
        leaving = progress < 0.5
        travel = ease_in_out_quint(2 * progress if leaving else 2 * (1 - progress))
        index = self.outgoing_index if leaving else self.incoming_index
        return exit_distance * travel, 1 - travel, index


class LoadoutSlide:
    def __init__(self, initial_index, duration_seconds):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("로드아웃 전환 시간은 양수인 유한한 초 단위 값이어야 한다.")
        self.duration_seconds = duration_seconds
        self.reset(initial_index)

    @staticmethod
    def _validate_index(index):
        if type(index) is not int or index not in (0, 1):
            raise ValueError("로드아웃 표시 번호는 0 또는 1이어야 한다.")

    def reset(self, index):
        self._validate_index(index)
        self.outgoing_index = self.incoming_index = self.latest_index = index
        self.animation = ScalarAnimation(0, 1, self.duration_seconds, easing=linear,
                                         elapsed_seconds=self.duration_seconds)

    def _begin(self, index):
        self.outgoing_index, self.incoming_index = self.incoming_index, index
        self.animation = ScalarAnimation(0, 1, self.duration_seconds, easing=linear)

    def request(self, index):
        self._validate_index(index)
        self.latest_index = index
        if self.animation.finished and index != self.incoming_index:
            self._begin(index)

    def update(self, delta_seconds):
        remaining = self.duration_seconds - self.animation.elapsed_seconds
        self.animation.update(delta_seconds)
        if self.animation.finished and self.latest_index != self.incoming_index:
            self._begin(self.latest_index)
            self.animation.update(max(0.0, delta_seconds - remaining))

    @property
    def visual(self):
        incoming = self.incoming_index
        outgoing = incoming if self.animation.finished else self.outgoing_index
        return LoadoutVisual(outgoing, incoming, self.animation.elapsed_seconds, self.duration_seconds)
