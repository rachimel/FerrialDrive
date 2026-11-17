"""글자 자간과 가벼운 획 축소를 텍스처 생성 시 한 번 적용한다."""

from ctypes import byref, c_int, memmove, string_at
from math import ceil, isfinite


def validate_text_style(letter_spacing_pixels, stroke_inset_pixels=0):
    if not isfinite(letter_spacing_pixels) or letter_spacing_pixels < 0:
        raise ValueError("자간은 0 이상의 유한한 픽셀 값이어야 한다.")
    if not isfinite(stroke_inset_pixels) or not 0 <= stroke_inset_pixels <= 1:
        raise ValueError("획 축소량은 0~1 픽셀이어야 한다.")


def styled_text_surface(pico, font, text, color, letter_spacing_pixels, stroke_inset_pixels, gradient_bottom_ratio=1):
    """원본 글꼴·글자 높이·내부 불투명도를 유지하며 표시 마스크를 만든다."""
    validate_text_style(letter_spacing_pixels, stroke_inset_pixels)
    if not isfinite(gradient_bottom_ratio) or not 0 <= gradient_bottom_ratio <= 1:
        raise ValueError("글자 그라데이션 밝기는 0~1이어야 한다.")
    glyphs = []
    cursor, height = 0.0, 0
    for index, token in enumerate(text if letter_spacing_pixels else (text,)):
        original = pico.TTF_RenderUTF8_Blended(font, token.encode("utf-8"), color)
        if not original:
            raise RuntimeError("표시용 글자 렌더링 실패")
        try:
            surface = pico.SDL_ConvertSurfaceFormat(original, pico.SDL_PIXELFORMAT_RGBA32, 0)
        finally:
            pico.SDL_FreeSurface(original)
        if not surface:
            raise RuntimeError("표시용 글자 형식 변환 실패")
        try:
            if pico.SDL_LockSurface(surface) != 0:
                raise RuntimeError("표시용 글자 읽기 실패")
            try:
                glyph_width, glyph_height = surface.contents.w, surface.contents.h
                rows = tuple(string_at(surface.contents.pixels + row * surface.contents.pitch, glyph_width * 4)
                             for row in range(glyph_height))
            finally:
                pico.SDL_UnlockSurface(surface)
        finally:
            pico.SDL_FreeSurface(surface)
        prefix_width, prefix_height = c_int(), c_int()
        prefix = text[:index + 1] if letter_spacing_pixels else text
        if pico.TTF_SizeUTF8(font, prefix.encode("utf-8"), byref(prefix_width), byref(prefix_height)) != 0:
            raise RuntimeError("표시용 글자 크기 계산 실패")
        # 원래 글꼴의 커닝을 보존하고 글자 사이에만 요청한 간격을 더한다.
        left = max(0, prefix_width.value - glyph_width) + index * letter_spacing_pixels
        glyphs.append((round(left), glyph_width, rows))
        cursor = prefix_width.value + index * letter_spacing_pixels
        height = max(height, glyph_height)
    width = max(1, ceil(cursor))
    mask = bytearray(width * height)
    for left, glyph_width, rows in glyphs:
        for y, row in enumerate(rows):
            if len(glyphs) == 1 and left == 0 and glyph_width == width:
                # 커닝을 포함해 한 번에 렌더한 문자열은 알파 채널을 그대로 복사한다.
                mask[y * width:(y + 1) * width] = row[3::4]
                continue
            for x in range(glyph_width):
                index = y * width + left + x
                if left + x < width:
                    mask[index] = max(mask[index], row[x * 4 + 3])
    if stroke_inset_pixels:
        source = mask[:]
        for y in range(height):
            for x in range(width):
                index = y * width + x
                edge = min(source[index - 1] if x else 0,
                           source[index + 1] if x + 1 < width else 0,
                           source[index - width] if y else 0,
                           source[index + width] if y + 1 < height else 0)
                mask[index] = round(source[index] + (min(source[index], edge) - source[index]) * stroke_inset_pixels)
    result = pico.SDL_CreateRGBSurfaceWithFormat(0, width, height, 32, pico.SDL_PIXELFORMAT_RGBA32)
    if not result:
        raise RuntimeError("표시용 글자 surface 생성 실패")
    try:
        if pico.SDL_LockSurface(result) != 0:
            raise RuntimeError("표시용 글자 쓰기 실패")
        try:
            for y in range(height):
                brightness = 1 + (gradient_bottom_ratio - 1) * y / max(1, height - 1)
                rgb = bytes((round(color.r * brightness), round(color.g * brightness), round(color.b * brightness), 0))
                row = bytearray(rgb * width)
                row[3::4] = mask[y * width:(y + 1) * width]
                memmove(result.contents.pixels + y * result.contents.pitch, bytes(row), width * 4)
        finally:
            pico.SDL_UnlockSurface(result)
    except BaseException:
        pico.SDL_FreeSurface(result)
        raise
    return result
