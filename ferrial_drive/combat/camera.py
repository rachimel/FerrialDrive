"""플레이어 중심 시선 오프셋과 월드/화면 변환. 입력 장치·렌더러와 독립이다."""

from math import exp, hypot, isfinite


class LookAheadCamera:
    def __init__(self, width_pixels, height_pixels, *, dead_zone_pixels=80,
                 offset_ratio=0.2, max_offset_units=120, response_seconds=0.15):
        values = (width_pixels, height_pixels, dead_zone_pixels, offset_ratio, max_offset_units, response_seconds)
        if (not all(map(isfinite, values)) or min(width_pixels, height_pixels, response_seconds) <= 0
                or dead_zone_pixels < 0 or max_offset_units < 0 or not 0 <= offset_ratio < 1):
            raise ValueError("카메라 크기·데드존·오프셋·응답 시간이 유효하지 않다.")
        self.screen_center = width_pixels / 2, height_pixels / 2
        self.dead_zone_pixels, self.offset_ratio = dead_zone_pixels, offset_ratio
        self.max_offset_units, self.response_seconds = max_offset_units, response_seconds
        self.reset((0, 0))

    def reset(self, player_world):
        self.position = tuple(player_world)

    def world_to_screen(self, point):
        return tuple(value - camera + center for value, camera, center in zip(point, self.position, self.screen_center))

    def screen_to_world(self, point):
        return tuple(value + camera - center for value, camera, center in zip(point, self.position, self.screen_center))

    def update(self, player_world, mouse_screen, delta_seconds):
        if (not isfinite(delta_seconds) or delta_seconds < 0
                or not all(map(isfinite, player_world))
                or (mouse_screen is not None and not all(map(isfinite, mouse_screen)))):
            raise ValueError("카메라 좌표와 갱신 시간은 유한해야 한다.")
        dx, dy = (0, 0) if mouse_screen is None else tuple(a - b for a, b in zip(mouse_screen, self.screen_center))
        distance = hypot(dx, dy)
        # 정지 상태에서 마우스-플레이어 변위에 비례하도록 오프셋 자체의 변위를 보정한다.
        amount = min(self.max_offset_units, max(0, distance - self.dead_zone_pixels)
                     * self.offset_ratio / (1 - self.offset_ratio))
        offset = (dx * amount / distance, dy * amount / distance) if distance else (0, 0)
        weight = 1 - exp(-delta_seconds / self.response_seconds)
        desired = tuple(a + b for a, b in zip(player_world, offset))
        self.position = tuple(a + (b - a) * weight for a, b in zip(self.position, desired))
