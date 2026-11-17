"""둥근 단면의 가상 법선·시선각으로 계산하는 2D 베임선 Rim Lighting."""

from math import isfinite, sqrt


def slash_rim_color(position, material, settings, opacity):
    """중앙은 기본색, 시선과 직각인 가장자리는 재질별 림 색으로 표시한다."""
    power = settings.get("metal_power",settings.get("power",1.4)) if material == "metal" else settings.get("power",1.4)
    feather = settings.get("edge_feather", 0.04)
    strength = settings.get("strength", 1)
    if (not isfinite(position) or not -1 <= position <= 1 or not isfinite(power) or power <= 0
            or not 0 < feather <= 1 or not 0 <= strength <= 1 or not 0 <= opacity <= 1):
        raise ValueError("베임선 림의 위치·곡률·경계·강도·투명도 범위 오류")
    normal_dot_view = sqrt(max(0, 1 - position * position))
    rim = (1 - normal_dot_view) ** power * strength
    body = settings.get("body_color", "#E6F9FF")
    edge = settings.get("metal_color", "#FFD58A") if material == "metal" else settings.get("color", "#BFEFFF")
    rgb = tuple(round(int(body[i:i+2],16) * (1-rim) + int(edge[i:i+2],16) * rim) for i in (1,3,5))
    coverage = min(1, (1 - abs(position)) / feather)
    return (*rgb, round(255 * opacity * coverage))
