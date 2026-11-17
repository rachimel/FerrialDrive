"""프레임 사이 픽셀 변위의 입력 계약. 창·게임 상태·샘플에 의존하지 않는다."""

from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path


VECTOR_SCALE = 64
VECTOR_BIAS = 32768
EASING_CODES = {"linear": 0, "smoothstep": 1, "accelerate": 2, "quint_in": 3}


def encode_vector(dx_pixels, dy_pixels):
    """X·Y를 각각 부호 있는 16비트 고정소수점으로 RG/BA에 저장한다."""
    channels = []
    for value in (dx_pixels, dy_pixels):
        if not isfinite(value):
            raise ValueError("모션 벡터는 유한한 픽셀 변위여야 한다.")
        encoded = round(value * VECTOR_SCALE) + VECTOR_BIAS
        if not 0 <= encoded <= 65535:
            raise ValueError("모션 벡터의 표현 범위를 초과했다.")
        channels.extend(divmod(encoded, 256))
    return bytes(channels)


def decode_vector(channels):
    r, g, b, a = channels
    return ((r * 256 + g - VECTOR_BIAS) / VECTOR_SCALE,
            (b * 256 + a - VECTOR_BIAS) / VECTOR_SCALE)


def validate_phase(phase):
    if isinstance(phase, bool) or not isfinite(phase) or not 0 <= phase <= 1:
        raise ValueError("보간 위상은 0~1 범위여야 한다.")
    return float(phase)


def target_phase(progress, *, easing="smoothstep", start=0.0, end=1.0):
    """첫/끝 KeyFrame의 목표 위상을 잇는다. 개별 원본 프레임에 반복 적용하지 않는다."""
    progress, start, end = (validate_phase(value) for value in (progress, start, end))
    if easing not in EASING_CODES:
        raise ValueError("지원하지 않는 위상 곡선이다.")
    if easing == "quint_in":
        value = progress**5
    elif easing == "accelerate":
        # SmoothStep 속도를 누적한 위상을 0~1로 정규화한다.
        value = progress**3 * (2-progress)
    else:
        value = progress if easing == "linear" else progress * progress * (3 - 2 * progress)
    return start + (end - start) * value


def frame_interval(phase, count):
    phase = validate_phase(phase)
    if type(count) is not int or count < 1:
        raise ValueError("프레임 구간이 하나 이상 필요하다.")
    value = phase * count
    index = min(int(value), count - 1)
    return index, value - index


def advance_combo_phase(index, phase, delta_seconds, durations, *, boundary="zero"):
    """연계 경계에서 남은 시간 이월과 첫 위상 출력 후보를 명시적으로 구분한다."""
    phase = validate_phase(phase)
    if (not durations or any(not isfinite(value) or value <= 0 for value in durations)
            or type(index) is not int or not 0 <= index < len(durations)
            or not isfinite(delta_seconds) or delta_seconds < 0 or boundary not in ("carry", "zero")):
        raise ValueError("콤보 위상 갱신 입력 오류")
    seconds = phase * durations[index] + delta_seconds
    if boundary == "zero" and seconds >= durations[index]:
        return (index + 1) % len(durations), 0.0
    if boundary == "carry":
        seconds %= sum(durations)
        while seconds >= durations[index]:
            seconds -= durations[index]
            index = (index + 1) % len(durations)
    return index, seconds / durations[index]


def premultiply_rgba(pixels):
    result = bytearray(pixels)
    for index in range(0, len(result), 4):
        alpha = result[index + 3]
        if alpha == 255:
            continue
        if alpha == 0:
            result[index:index + 3] = b"\0\0\0"
            continue
        for channel in range(3):
            result[index + channel] = (result[index + channel] * alpha + 127) // 255
    return bytes(result)


@dataclass(frozen=True)
class MotionPair:
    width: int
    height: int
    rgba_a: bytes
    rgba_b: bytes
    forward: bytes
    backward: bytes
    duration_seconds: float
    label: str = "외부 프레임"

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in (self.width, self.height)):
            raise ValueError("프레임 크기는 양수 정수여야 한다.")
        if (isinstance(self.duration_seconds, bool) or not isfinite(self.duration_seconds)
                or self.duration_seconds <= 0):
            raise ValueError("프레임 간격은 양수 초 단위여야 한다.")
        size = self.width * self.height * 4
        for name in ("rgba_a", "rgba_b", "forward", "backward"):
            if not isinstance(getattr(self, name), bytes) or len(getattr(self, name)) != size:
                raise ValueError(f"{name}의 RGBA 바이트 수가 프레임 크기와 다르다.")


@dataclass(frozen=True)
class MotionClip:
    pairs: tuple[MotionPair, ...]

    def __post_init__(self):
        if not self.pairs:
            raise ValueError("원본 프레임 구간이 필요하다.")
        first = self.pairs[0]
        for pair in self.pairs:
            if (pair.width, pair.height, pair.duration_seconds) != (first.width, first.height, first.duration_seconds):
                raise ValueError("현재 보간기는 같은 크기·같은 시간 간격의 프레임을 사용한다.")
        for left, right in zip(self.pairs, self.pairs[1:]):
            if left.rgba_b != right.rgba_a:
                raise ValueError("인접 프레임 구간의 경계 이미지가 다르다.")

    @property
    def duration_seconds(self):
        return self.pairs[0].duration_seconds * len(self.pairs)


def load_clip(manifest, read_image):
    manifest = Path(manifest).resolve()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if "pairs" not in data:
        return MotionClip((load_pair(manifest, read_image),))
    if data.get("schema_version") != 1:
        raise ValueError("지원하지 않는 클립 계약이다.")
    return MotionClip(tuple(load_pair(manifest.parent / name, read_image) for name in data["pairs"]))


def load_pair(manifest, read_image):
    """이미지 디코더는 실행부가 주입한다. 벡터는 색 보정 없는 RGBA 원시 바이트다."""
    manifest = Path(manifest).resolve()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if (data.get("schema_version") != 1 or data.get("vector_encoding") != "signed16_rgba_x64"
            or data.get("vector_units") != "pixels_per_pair" or data.get("origin") != "top_left"):
        raise ValueError("지원하지 않는 모션 벡터 계약이다.")
    width, height = data["size_pixels"]
    colors = []
    for field in ("image_a", "image_b"):
        image_width, image_height, pixels = read_image(manifest.parent / data[field])
        if (image_width, image_height) != (width, height):
            raise ValueError("두 원본과 벡터의 크롭·크기를 일치시켜야 한다.")
        colors.append(pixels)
    return MotionPair(width, height, *colors,
                      (manifest.parent / data["forward_a_to_b"]).read_bytes(),
                      (manifest.parent / data["backward_b_to_a"]).read_bytes(),
                      data["duration_seconds"], data.get("label", manifest.stem))
