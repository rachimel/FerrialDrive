"""게임 코드에 의존하지 않는 독립 테스트 실행 규약."""

from .interface import Stop, SwitchTo, TestProgram, WindowSpec
from .runner import run

__all__ = ["Stop", "SwitchTo", "TestProgram", "WindowSpec", "run"]
