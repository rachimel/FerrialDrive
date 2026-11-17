"""선택 슬롯의 백웨폰 장착 여부에 따른 전개 위상. 장착·스왑 입력은 호출자가 소유한다."""

from math import isfinite


class BackWeaponDeployment:
    def __init__(self, *, duration_seconds):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("전개 시간은 양의 초 단위여야 한다.")
        self.duration_seconds = duration_seconds
        self.phase = self.target = 0.0
        self.selected_slot = None

    def swap(self, slot, *, back_weapon_equipped):
        if type(back_weapon_equipped) is not bool:
            raise ValueError("백웨폰 장착 여부는 bool이어야 한다.")
        self.selected_slot = slot
        self.target = float(back_weapon_equipped)

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("경과 시간은 음수가 아닌 초 단위여야 한다.")
        distance = delta_seconds / self.duration_seconds
        self.phase += max(-distance, min(distance, self.target - self.phase))

    def frame_position(self, frame_count):
        if type(frame_count) is not int or frame_count < 1:
            raise ValueError("전개 프레임 수는 양의 정수여야 한다.")
        return self.phase * (frame_count - 1)
