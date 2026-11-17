"""휘두른 곡선을 따라 길게 겹쳐 흐르고 양끝이 가늘어지는 검빛 텍스처."""

from math import exp, isfinite, pi, sin
from random import Random


def trail_flow_pixels(width=512, height=128, *, strands=18, softness=0.018):
    if (type(width) is not int or type(height) is not int or min(width, height) < 2
            or type(strands) is not int or strands < 1
            or not isfinite(softness) or not 0 < softness < 0.2):
        raise ValueError("검 Trail 결의 크기·가닥 수·부드러움 오류")
    random = Random(29)
    fibers = [(random.uniform(0.13, 0.87), random.uniform(softness * 0.2, softness),
               random.uniform(0, 0.16), random.uniform(0.82, 1), random.uniform(0, pi * 2))
              for _ in range(strands)]
    pixels = bytearray()
    for y in range(height):
        across = y / (height - 1)
        for x in range(width):
            along = x / (width - 1)
            taper = sin(pi * along) ** 0.7
            center = 0.53 + 0.035 * sin(pi * along)
            spread = 0.16 * (0.12 + 0.88 * taper)
            core = exp(-((across - center) / spread) ** 2 / 2) * taper
            threads = 0
            for position, thickness, start, end, phase in fibers:
                if start < along < end:
                    length = (along - start) / (end - start)
                    # 각 가닥은 진행축에 길게 이어지고 폭 방향으로 부드럽게 번진다.
                    lane = center + (position - 0.5) * (0.18 + 0.82 * taper)
                    lane += 0.012 * sin(pi * along * 2 + phase)
                    thread = exp(-((across - lane) / thickness) ** 2 / 2)
                    threads += thread * sin(pi * length) ** 0.55
            alpha = min(1, core * 0.82 + threads * 0.29)
            if x in (0, width - 1) or y in (0, height - 1):
                alpha = 0
            light = round(210 + 45 * min(1, core + threads * 0.2))
            pixels.extend((light, light, light, round(255 * alpha)))
    return bytes(pixels)
