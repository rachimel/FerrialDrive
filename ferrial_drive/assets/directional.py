"""8방향 클립의 방향 선택과 재생 시간. 창과 렌더링은 실행하는 쪽이 관리한다."""

from math import atan2, floor, isfinite, pi


SCREEN_DIRECTIONS = ("e", "se", "s", "sw", "w", "nw", "n", "ne")


class DirectionalPlayback:
    def __init__(self, clips, *, motion="equipped_idle", direction="se"):
        self.clips = clips
        self.motion = motion
        self.initial_direction = direction
        if direction not in SCREEN_DIRECTIONS or any(
                f"{motion}/{value}" not in clips for value in SCREEN_DIRECTIONS):
            raise ValueError("기본 방향과 8방향 클립이 필요하다.")
        self.reset()

    def reset(self):
        self.direction = self.initial_direction
        self.elapsed_seconds = 0.0

    @property
    def clip_name(self):
        return f"{self.motion}/{self.direction}"

    @property
    def frame_index(self):
        return self.clips[self.clip_name].frame_at(self.elapsed_seconds)

    def face(self, dx, dy):
        """화면 기준 +X 오른쪽, +Y 아래. 방향을 바꿔도 재생 위상은 유지한다."""
        if not isfinite(dx) or not isfinite(dy):
            raise ValueError("방향 벡터는 유한한 값이어야 한다.")
        if dx * dx + dy * dy > 1e-12:
            self.direction = SCREEN_DIRECTIONS[floor(atan2(dy, dx) * 4 / pi + 0.5) % 8]

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("재생 시간은 0 이상의 유한한 초 단위다.")
        self.elapsed_seconds += delta_seconds
