"""배경·바닥·이동 가능 다각형을 같은 bottom-left 픽셀 좌표로 읽는다."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re

from .sprites import SpriteClip, SpriteFrame, SpriteSheet, numbers, read_json


@dataclass(frozen=True)
class MapBundle:
    data: dict
    paths: dict

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        return cls.from_data(read_json(path), path.parent)

    @classmethod
    def from_data(cls, data, base):
        try:
            if (data.get('version') != 1 or data.get('type') != 'map'
                    or data.get('coordinates') != 'bottom-left'):
                raise ValueError('맵 type·version·좌표 기준 오류')
            if not isinstance(data['asset_id'], str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', data['asset_id']):
                raise ValueError('맵 에셋 ID 오류')
            if not numbers(data['size'], 2, integer=True, positive=True):
                raise ValueError('맵 크기는 양수 정수 픽셀이다.')
            paths = {}
            for key in ('background', 'ground', 'composite'):
                if key == 'composite' and key not in data:
                    continue
                value = data[key]
                if not isinstance(value, str) or not value.strip():
                    raise ValueError('맵 레이어 이미지 경로가 필요하다.')
                paths[key] = (Path(base) / value).resolve()
                if not paths[key].is_file():
                    raise FileNotFoundError(paths[key])
            polygons = data['walkable']
            if not isinstance(polygons, list):
                raise ValueError('walkable은 다각형 목록이다.')
            width, height = data['size']
            for polygon in polygons:
                if (not isinstance(polygon, list) or len(polygon) < 3
                        or any(not numbers(point, 2) or not 0 <= point[0] <= width
                               or not 0 <= point[1] <= height for point in polygon)):
                    raise ValueError('이동 구역은 맵 범위 안의 꼭짓점 3개 이상이다.')
                area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(polygon, polygon[1:] + polygon[:1]))
                if abs(area) < 1e-6:
                    raise ValueError('이동 구역의 면적이 0이다.')
            return cls(deepcopy(data), paths)
        except (KeyError, TypeError, AttributeError, IndexError) as error:
            raise ValueError('맵 번들의 필수 항목·형식 오류') from error

    @property
    def size(self):
        return tuple(self.data['size'])

    @property
    def sheets(self):
        width, height = self.size
        clip = SpriteClip(1, (SpriteFrame((0, 0, width, height), (0, 0), 1000),))
        return {('body' if key == 'background' else key): SpriteSheet(path, self.size, {'map': clip})
                for key, path in self.paths.items()}

    @property
    def clips(self):
        clip = next(iter(self.sheets.values())).clips['map']
        return {key: clip for key in ('background', 'ground', 'composite', 'walkable')}

    def contains(self, x, y):
        """다각형들의 합집합. 경계도 이동 가능 구역에 포함한다."""
        for polygon in self.data['walkable']:
            inside = False
            for a, b in zip(polygon, polygon[1:] + polygon[:1]):
                cross = (x - a[0]) * (b[1] - a[1]) - (y - a[1]) * (b[0] - a[0])
                if (abs(cross) < 1e-7 and min(a[0], b[0]) <= x <= max(a[0], b[0])
                        and min(a[1], b[1]) <= y <= max(a[1], b[1])):
                    return True
                if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
                    inside = not inside
            if inside:
                return True
        return False
