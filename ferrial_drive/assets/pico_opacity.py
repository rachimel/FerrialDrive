"""공유 텍스처의 그림자 알파를 그리는 동안만 조절하고 원래 상태를 복원한다."""

from contextlib import contextmanager
from ctypes import byref, c_ubyte, c_void_p, cast
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


@contextmanager
def texture_tint(pico, textures, tint, tint_mix, brightness=1):
    """기본 SDL 경로의 에너지색 곱셈 근사. 공유 텍스처 색은 사용 후 복구한다."""
    if len(tint) != 3 or any(not isfinite(v) or not 0 <= v <= 1 for v in (*tint, tint_mix, brightness)):
        raise ValueError("혼합 색상과 비율은 0~1의 유한값이어야 한다.")
    previous = {}
    try:
        for texture in textures:
            key = cast(texture, c_void_p).value
            if key in previous:
                continue
            rgb = [c_ubyte() for _ in range(3)]
            if pico.SDL_GetTextureColorMod(texture, *(byref(v) for v in rgb)):
                raise RuntimeError("텍스처 색상 조회 실패")
            previous[key] = (texture, tuple(v.value for v in rgb))
            mixed = [round(v.value * (1 - tint_mix + tint_mix * c) * brightness) for v, c in zip(rgb, tint)]
            if pico.SDL_SetTextureColorMod(texture, *mixed):
                raise RuntimeError("텍스처 색상 설정 실패")
        yield
    finally:
        for texture, rgb in previous.values():
            pico.SDL_SetTextureColorMod(texture, *rgb)
