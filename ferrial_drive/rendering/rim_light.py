"""Standby의 붉은 림 호흡. 시간 갱신과 일시정지는 호출자가 소유한다."""

from math import cos, isfinite, tau


def standby_rim(settings, elapsed_seconds, active):
    period = settings.get("breath_seconds", 1.8)
    minimum = settings.get("minimum_strength_ratio", 0.65)
    strength = settings.get("strength", 1)
    if (not isfinite(period) or period <= 0 or not isfinite(elapsed_seconds) or elapsed_seconds < 0
            or not 0 <= minimum <= 1 or not 0 <= strength <= 1):
        raise ValueError("림 호흡의 시간·강도 오류")
    color = settings.get("color", "#FF263D")
    rgb = tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    pulse = minimum + (1 - minimum) * (0.5 + 0.5 * cos(tau * elapsed_seconds / period))
    return (*rgb, strength * pulse if active else 0)
