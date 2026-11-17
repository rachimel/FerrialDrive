"""입력·렌더링과 독립된 방향별 단발 콤보 재생 상태."""

from math import isfinite

from .directional import SCREEN_DIRECTIONS


class ComboPlayback:
    def __init__(self, clips, *, motions=("combo_01", "combo_02", "combo_03", "combo_04")):
        self.clips = clips
        self.motions = tuple(motions)
        if not self.motions or any(f"{motion}/{direction}" not in clips
                                   for motion in self.motions for direction in SCREEN_DIRECTIONS):
            raise ValueError("모든 타격의 8방향 클립이 필요하다.")
        self.direction = "se"
        self.reset()

    def reset(self):
        self.attack_index = None
        self.elapsed_seconds = 0.0
        self.waiting_for_input = False
        self.queued = False

    @property
    def active(self):
        return self.attack_index is not None

    @property
    def clip_name(self):
        if not self.active:
            return None
        index = self.attack_index + int(self.waiting_for_input)
        return f"{self.motions[index]}/{self.direction}"

    @property
    def frame_index(self):
        if not self.active or self.waiting_for_input:
            return 0
        return self.clips[self.clip_name].frame_at(self.elapsed_seconds)

    def request(self, direction):
        """타격을 시작하거나 다음 타격 하나를 예약한다. 방향 갱신은 호출자가 지정한다."""
        if direction not in SCREEN_DIRECTIONS:
            raise ValueError("8방향 중 하나가 필요하다.")
        if not self.active:
            self.direction = direction
            self.attack_index = 0
        elif self.waiting_for_input:
            self.attack_index += 1
            self.waiting_for_input = False
            self.elapsed_seconds = 0.0
        elif self.attack_index < len(self.motions) - 1:
            self.queued = True
        else:
            return False
        return True

    def clear_buffer(self):
        self.queued = False

    def update(self, delta_seconds, *, next_direction=None):
        if next_direction is not None and next_direction not in SCREEN_DIRECTIONS:
            raise ValueError("다음 타격 방향은 8방향 중 하나다.")
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("재생 시간은 0 이상의 유한한 초 단위다.")
        while self.active and not self.waiting_for_input:
            duration = self.clips[self.clip_name].duration_ms / 1000
            remaining = duration - self.elapsed_seconds
            if delta_seconds + 1e-9 < remaining:
                self.elapsed_seconds += delta_seconds
                break
            delta_seconds = max(0.0, delta_seconds - remaining)
            self.elapsed_seconds = 0.0
            if self.attack_index == len(self.motions) - 1:
                self.reset()
            elif self.queued:
                self.attack_index += 1
                self.queued = False
                if next_direction is not None:
                    self.direction = next_direction
            else:
                # 다음 타격의 첫 프레임은 현재 타격의 연결 끝점이다.
                self.waiting_for_input = True
