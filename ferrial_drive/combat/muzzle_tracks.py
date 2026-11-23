"""Unreal 총구를 카메라별 root 상대 픽셀로 읽는다. 모션·키를 작성하지 않는다."""

from bisect import bisect_right
from math import isfinite

from .geometry import Vec2
from ferrial_drive.assets.directional import SCREEN_DIRECTIONS
from ferrial_drive.rendering.part_metadata import PackedTrackRows
from ferrial_drive.rendering.part_metadata_archive import read_track_metadata


class MuzzleTracks:
    def __init__(self, tracks):
        if not tracks:
            raise ValueError("총구 추적 자료가 필요하다.")
        self.tracks = tracks
        for rows in tracks.values():
            if (len(rows) < 2 or any(len(row) != 3 or not all(map(isfinite, row)) for row in rows)
                    or rows[0][0] != 0 or any(a[0] >= b[0] for a, b in zip(rows, rows[1:]))):
                raise ValueError("총구 표본은 0초부터 시작하는 시간순 픽셀 좌표다.")

    @classmethod
    def load(cls, path):
        data = read_track_metadata(path)
        if data.get("version") != 1 or data.get("space") != "root_relative_top_left_px":
            raise ValueError("총구 추적의 좌표계·버전이 다르다.")
        return cls(data["tracks"])

    def sample(self, clip_name, seconds, *, loop=False):
        rows = self.tracks[clip_name]
        seconds = seconds % rows[-1][0] if loop else min(rows[-1][0], max(0, seconds))
        if isinstance(rows, PackedTrackRows):
            next_index = bisect_right(range(len(rows)), seconds, key=rows.time_at)
        else:
            next_index = bisect_right(rows, seconds, key=lambda row: row[0])
        index = min(len(rows)-1, max(1, next_index))
        a, b = rows[index-1], rows[index]
        ratio = (seconds-a[0])/(b[0]-a[0])
        return Vec2(*(a[i]+(b[i]-a[i])*ratio for i in (1, 2)))

    def aim_plane_offset(self, motion, seconds, *, loop=False):
        """같은 높이의 8방향 카메라 평균으로 총구 평면의 높이를 구한다."""
        points = [self.sample(motion + '/' + direction, seconds, loop=loop) for direction in SCREEN_DIRECTIONS]
        return Vec2(sum(p.x for p in points)/len(points), sum(p.y for p in points)/len(points))
