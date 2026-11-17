"""2D 조립 작업본의 경로와 원본 프레임 번호 입력 규칙."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = Path(__file__).with_name("workspace")

def frame_numbers(text):
    try:
        frames = [int(value.strip()) for value in text.split(",")]
    except ValueError as error:
        raise ValueError("프레임은 쉼표로 구분한 정수 목록이어야 한다.") from error
    if not frames or len(frames) > 256 or any(value < 0 for value in frames):
        raise ValueError("프레임은 0 이상의 정수로 최대 256개 지정한다.")
    if len(set(frames)) != len(frames):
        raise ValueError("원본 프레임은 중복 없이 지정한다. 반복은 조립 단계에서 설정한다.")
    return frames
