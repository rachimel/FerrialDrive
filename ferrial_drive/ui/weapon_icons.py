"""임시 무기 실루엣의 고정 비율과 겹침 없는 래스터 마스크."""

from .components import Rect


WEAPON_ASPECTS = {"melee": 6.25, "ranged": 3.2}
WEAPON_SHAPES = {
    "melee": ((0.02, 0.42, 0.23, 0.18), (0.23, 0.1, 0.05, 0.8),
              (0.28, 0.38, 0.68, 0.26)),
    "ranged": ((0.02, 0.24, 0.15, 0.38), (0.17, 0.34, 0.07, 0.14),
               (0.24, 0.18, 0.4, 0.4), (0.64, 0.22, 0.18, 0.34),
               (0.82, 0.29, 0.09, 0.14), (0.91, 0.25, 0.04, 0.22),
               (0.31, 0.58, 0.1, 0.3), (0.49, 0.58, 0.14, 0.38),
               (0.29, 0.1, 0.05, 0.08), (0.74, 0.12, 0.04, 0.1))
}


def fit_weapon_icon(kind, rect, vertical_scale=1.0):
    """카드 전환 중에도 같은 비율로만 확대·축소한다."""
    aspect = WEAPON_ASPECTS[kind]
    width = min(rect.width, rect.height / vertical_scale * aspect)
    height = width / aspect * vertical_scale
    return Rect(rect.x + (rect.width - width) / 2,
                rect.y + (rect.height - height) / 2, width, height)


def weapon_icon_pixels(kind, fill_rgb, outline_rgb, outline_width):
    """100px 기준 높이의 원본 하나를 만들고, 외곽은 합친 마스크에만 적용한다."""
    height = 100
    width = round(height * WEAPON_ASPECTS[kind])
    fill_mask, outline_mask = bytearray(width * height), bytearray(width * height)

    def paint(mask, left, top, right, bottom):
        left, right = max(0, left), min(width, right)
        top, bottom = max(0, top), min(height, bottom)
        row = b"\x01" * max(0, right - left)
        for y in range(top, bottom):
            mask[y * width + left:y * width + right] = row

    for x, y, w, h in WEAPON_SHAPES[kind]:
        left, top = round(x * width), round(y * height)
        right, bottom = round((x + w) * width), round((y + h) * height)
        paint(fill_mask, left, top, right, bottom)
        paint(outline_mask, left - outline_width, top - outline_width,
              right + outline_width, bottom + outline_width)
    pixels = bytearray(width * height * 4)
    fill, outline = bytes((*fill_rgb, 255)), bytes((*outline_rgb, 255))
    for index, (inside, edge) in enumerate(zip(fill_mask, outline_mask)):
        if inside or edge:
            pixels[index * 4:index * 4 + 4] = fill if inside else outline
    return width, height, pixels
