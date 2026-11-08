"""정사영 카메라 축으로 투영한 경계의 공통 중심·배율을 구한다."""

from math import isfinite


def orthographic_fit(points, unit_width, unit_height, minimum_scale, *, padding=0.08):
    if (not all(isfinite(value) and value > 0 for value in (unit_width, unit_height, minimum_scale))
            or not isfinite(padding) or not 0 <= padding < 0.5):
        raise ValueError('카메라 범위·배율·여백 설정 오류')
    low, high = [float('inf')] * 3, [float('-inf')] * 3
    count = 0
    for point in points:
        if len(point) != 3 or not all(isfinite(value) for value in point):
            raise ValueError('모델 경계에 유효하지 않은 좌표가 있다.')
        for axis in range(3):
            low[axis] = min(low[axis], point[axis])
            high[axis] = max(high[axis], point[axis])
        count += 1
    if not count:
        raise ValueError('카메라에 맞출 모델 경계가 없다.')
    usable = 1 - 2 * padding
    scale = max(minimum_scale, (high[0] - low[0]) / (unit_width * usable),
                (high[1] - low[1]) / (unit_height * usable))
    return ((low[0] + high[0]) / 2, (low[1] + high[1]) / 2), scale, (low[2], high[2])
