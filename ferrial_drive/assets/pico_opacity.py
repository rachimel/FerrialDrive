"""공유 텍스처의 그림자 알파를 그리는 동안만 조절하고 원래 상태를 복원한다."""

from contextlib import contextmanager
from ctypes import byref, c_ubyte
from math import isfinite


DEFAULT_SHADOW_OPACITY = 0.5


@contextmanager
def shadow_opacity(pico, texture, opacity):
    if type(opacity) not in (int, float) or not isfinite(opacity) or not 0 <= opacity <= 1:
        raise ValueError("그림자 불투명도는 0~1 범위여야 한다.")
    previous = c_ubyte()
    if pico.SDL_GetTextureAlphaMod(texture, byref(previous)) != 0:
        raise RuntimeError("텍스처 알파 조회 실패")
    if pico.SDL_SetTextureAlphaMod(texture, round(previous.value * opacity)) != 0:
        raise RuntimeError("그림자 알파 설정 실패")
    try:
        yield
    finally:
        pico.SDL_SetTextureAlphaMod(texture, previous.value)
