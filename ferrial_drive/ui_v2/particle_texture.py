"""오브·필압 Trail의 공용 알파 아틀라스. 외부 이미지 없이 한 번 생성한다."""

from math import exp


CELL_SIZE = 64
ATLAS_SIZE = (CELL_SIZE * 2, CELL_SIZE)


def build_particle_atlas():
    """왼쪽은 방사형 오브, 오른쪽은 가로로 늘릴 수 있는 펜 단면이다."""
    pixels = bytearray()
    for y in range(CELL_SIZE):
        across = (y + 0.5) / CELL_SIZE * 2 - 1
        for x in range(CELL_SIZE * 2):
            along = (x % CELL_SIZE + 0.5) / CELL_SIZE * 2 - 1
            if x < CELL_SIZE:
                radius_squared = across * across + along * along
                alpha = max(0, 1 - radius_squared) ** 3
            else:
                alpha = max(0, 1 - across * across) ** 2 * exp(-4 * across * across)
            pixels.extend((255, 255, 255, round(alpha * 255)))
    return bytes(pixels)
