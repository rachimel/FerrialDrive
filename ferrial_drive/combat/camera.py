"""플레이어 중심 시선 오프셋과 월드/화면 변환. 입력 장치·렌더러와 독립이다."""

from math import exp, hypot, isfinite
from ferrial_drive.animation import ScalarAnimation


class LookAheadCamera:
    def __init__(self, width_pixels, height_pixels, *, dead_zone_pixels=80,
                 offset_ratio=0.2, max_offset_units=120, response_seconds=0.15, zoom_transition_seconds=0.2):
        values = (width_pixels, height_pixels, dead_zone_pixels, offset_ratio, max_offset_units, response_seconds,
                  zoom_transition_seconds)
        if (not all(map(isfinite, values)) or min(width_pixels, height_pixels, response_seconds) <= 0
                or dead_zone_pixels < 0 or max_offset_units < 0 or zoom_transition_seconds < 0 or not 0 <= offset_ratio < 1):
            raise ValueError("카메라 크기·데드존·오프셋·응답 시간이 유효하지 않다.")
        self.screen_center = width_pixels / 2, height_pixels / 2
        self.dead_zone_pixels, self.offset_ratio = dead_zone_pixels, offset_ratio
        self.max_offset_units, self.response_seconds = max_offset_units, response_seconds
        self.zoom_transition_seconds = zoom_transition_seconds
        self.reset((0, 0))

    def reset(self, player_world):
        self.position = tuple(player_world)
        self.velocity_pixels_per_second = (0, 0)
        self.feedback_offset_pixels = (0, 0)
        self.zoom_animation = ScalarAnimation(1, 1, 0)

    @property
    def zoom(self):
        return self.zoom_animation.value

    def world_to_screen(self, point, *, include_feedback=True):
        """월드 표현은 충격을 포함한다. 고정 HUD 기준점에는 포함하지 않을 수 있다."""
        offset = self.feedback_offset_pixels if include_feedback else (0, 0)
        return tuple((value - camera) * self.zoom + center + shift
                     for value, camera, center, shift in zip(point, self.position, self.screen_center, offset))

    def screen_to_world(self, point, *, include_feedback=True):
        """표시 좌표의 역변환. 조준·표적 선택은 include_feedback=False를 사용한다."""
        offset = self.feedback_offset_pixels if include_feedback else (0, 0)
        return tuple((value - center - shift) / self.zoom + camera
                     for value, camera, center, shift in zip(point, self.position, self.screen_center, offset))

    def update(self, player_world, mouse_screen, delta_seconds, *, target_zoom=1, focus_world=None):
        if (not isfinite(delta_seconds) or delta_seconds < 0
                or not all(map(isfinite, player_world))
                or not isfinite(target_zoom) or target_zoom <= 0
                or (mouse_screen is not None and not all(map(isfinite, mouse_screen)))
                or (focus_world is not None and (len(focus_world) != 2 or not all(map(isfinite, focus_world))))):
            raise ValueError("카메라 좌표와 갱신 시간은 유한해야 한다.")
        if target_zoom != self.zoom_animation.end_value:
            self.zoom_animation = ScalarAnimation(self.zoom, target_zoom, self.zoom_transition_seconds)
        self.zoom_animation.update(delta_seconds)
        dx, dy = (0, 0) if mouse_screen is None else tuple(a - b for a, b in zip(mouse_screen, self.screen_center))
        distance = hypot(dx, dy)
        # 정지 상태에서 마우스-플레이어 변위에 비례하도록 오프셋 자체의 변위를 보정한다.
        amount = min(self.max_offset_units, max(0, distance - self.dead_zone_pixels)
                     / self.zoom * self.offset_ratio / (1 - self.offset_ratio))
        offset = (dx * amount / distance, dy * amount / distance) if distance else (0, 0)
        weight = 1 - exp(-delta_seconds / self.response_seconds)
        desired = tuple(a + b for a, b in zip(player_world, offset))
        if focus_world is not None:
            desired = tuple((a + b) / 2 for a, b in zip(player_world, focus_world))
        previous = self.position
        self.position = tuple(a + (b - a) * weight for a, b in zip(previous, desired))
        self.velocity_pixels_per_second = (tuple((b - a) * self.zoom / delta_seconds for a, b in zip(previous, self.position))
                                          if delta_seconds > 0 else (0, 0))
