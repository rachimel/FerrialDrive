"""해상도·알파를 유지하는 본체 샤프닝. 원본 프레임은 덮어쓰지 않는다."""

from array import array
from math import isfinite


def sharpen_rgba(data, width, height, amount=0.35):
    if (type(amount) not in (int, float) or not isfinite(amount) or not 0 <= amount <= 2
            or width <= 0 or height <= 0 or len(data) != width * height * 4):
        raise ValueError('샤프닝 입력 크기·강도 오류')
    if amount == 0:
        return bytes(data)
    premultiplied = array('f', [0]) * len(data)
    horizontal = array('f', [0]) * len(data)
    for i in range(0, len(data), 4):
        alpha = data[i + 3] / 255
        for channel in range(3):
            premultiplied[i + channel] = data[i + channel] * alpha
        premultiplied[i + 3] = alpha
    stride = width * 4
    for y in range(height):
        for x in range(width):
            i = y * stride + x * 4
            left, right = y * stride + max(0, x - 1) * 4, y * stride + min(width - 1, x + 1) * 4
            for channel in range(4):
                horizontal[i + channel] = (premultiplied[left + channel] + 2 * premultiplied[i + channel]
                                           + premultiplied[right + channel]) * 0.25
    output = bytearray(data)
    for y in range(height):
        for x in range(width):
            i = y * stride + x * 4
            if not data[i + 3]:
                output[i:i + 3] = b'\0\0\0'
                continue
            up, down = max(0, y - 1) * stride + x * 4, min(height - 1, y + 1) * stride + x * 4
            blurred_alpha = (horizontal[up + 3] + 2 * horizontal[i + 3] + horizontal[down + 3]) * 0.25
            strength = amount * data[i + 3] / 255
            for channel in range(3):
                blurred = (horizontal[up + channel] + 2 * horizontal[i + channel] + horizontal[down + channel]) * 0.25
                value = data[i + channel] + strength * (data[i + channel] - blurred / blurred_alpha)
                output[i + channel] = max(0, min(255, round(value)))
    return bytes(output)
