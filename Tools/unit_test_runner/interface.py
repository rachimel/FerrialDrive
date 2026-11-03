"""테스트 .py가 구현하는 수명 주기와 흐름 전환 요청."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class WindowSpec:
    width: int = 1280
    height: int = 720
    title: str = "Unit Test Runner"
    frames_per_second: float = 60

    def __post_init__(self):
        if not isinstance(self.width, int) or not isinstance(self.height, int):
            raise ValueError("창 크기는 정수 픽셀이어야 한다.")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("창 크기는 양수여야 한다.")
        if not isfinite(self.frames_per_second) or self.frames_per_second <= 0:
            raise ValueError("초당 프레임 수는 양수인 유한한 값이어야 한다.")


class TestProgram(ABC):
    """draw만 필수다. 나머지 동작은 필요한 테스트에서 구현한다."""

    def enter(self) -> None:
        """창이 열린 뒤 리소스를 준비한다."""

    def handle_event(self, event: object) -> FlowRequest | None:
        """테스트가 입력을 해석하고 필요하면 화면 교체·종료를 요청한다."""
        return None

    def update(self, delta_seconds: float) -> FlowRequest | None:
        """경과 시간을 초 단위로 받는다."""
        return None

    @abstractmethod
    def draw(self) -> None:
        """배경 지우기를 포함한 화면 전체를 그린다."""

    def exit(self) -> None:
        """화면 교체·종료 때 창이 닫히기 전에 리소스를 정리한다."""


@dataclass(frozen=True)
class SwitchTo:
    program: TestProgram

    def __post_init__(self):
        if not isinstance(self.program, TestProgram):
            raise TypeError("교체 대상은 TestProgram이어야 한다.")


@dataclass(frozen=True)
class Stop:
    """현재 독립 테스트 실행을 종료한다."""


FlowRequest = SwitchTo | Stop
