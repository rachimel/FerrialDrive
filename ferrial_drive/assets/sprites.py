"""SSheetCutil의 bottom-left 프레임·피봇·FPS 규격을 읽고 재생한다."""

from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def numbers(value, length, *, integer=False, positive=False):
    return (isinstance(value, list) and len(value) == length
            and all(type(item) in ((int,) if integer else (int, float))
                    and isfinite(item) and (not positive or item > 0) for item in value))


@dataclass(frozen=True)
class SpriteFrame:
    rect: tuple[int, int, int, int]
    pivot: tuple[float, float]


@dataclass(frozen=True)
class SpriteClip:
    fps: float
    frames: tuple[SpriteFrame, ...]


@dataclass(frozen=True)
class SpriteSheet:
    image_path: Path
    size: tuple[int, int]
    clips: dict[str, SpriteClip]

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        data = read_json(path)
        if data.get('version') != 1 or data.get('coordinates') != 'bottom-left':
            raise ValueError('시트 버전·좌표 기준 불일치')
        image = data['image']
        if not numbers(image['size'], 2, integer=True, positive=True):
            raise ValueError('시트 크기는 양수 정수 픽셀이어야 한다.')
        if not isinstance(image['path'], str) or not image['path']:
            raise ValueError('시트 이미지 경로가 필요하다.')
        image_path = (path.parent / image['path']).resolve()
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        clips = {}
        for row in data['animations']:
            name, fps = row['name'], row['fps']
            if (not isinstance(name, str) or not name or name in clips or type(fps) not in (int, float)
                    or not isfinite(fps) or not 0 < fps <= 240 or not row['frames']):
                raise ValueError('동작 이름·FPS·프레임 목록 오류')
            frames = []
            for entry in row['frames']:
                rect, pivot = entry['rect'], entry['pivot']
                if not numbers(rect, 4, integer=True) or not numbers(pivot, 2):
                    raise ValueError('프레임 영역·피봇 오류')
                x, y, width, height = rect
                if (min(x, y) < 0 or min(width, height) <= 0 or x + width > image['size'][0]
                        or y + height > image['size'][1] or not 0 <= pivot[0] <= width
                        or not 0 <= pivot[1] <= height):
                    raise ValueError('프레임·피봇이 이미지 범위를 벗어났다.')
                frames.append(SpriteFrame(tuple(rect), tuple(pivot)))
            clips[name] = SpriteClip(float(fps), tuple(frames))
        if not clips:
            raise ValueError('시트에 동작이 필요하다.')
        return cls(image_path, tuple(image['size']), clips)


@dataclass(frozen=True)
class SpriteBundle:
    asset_id: str
    body: SpriteSheet
    shadow: SpriteSheet
    directions: dict[str, str]
    config_sha256: str

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        data = read_json(path)
        if data.get('version') != 1:
            raise ValueError('지원하지 않는 에셋 번들 버전')
        body = SpriteSheet.load(path.parent / data['body'])
        shadow = SpriteSheet.load(path.parent / data['shadow'])
        if body.size != shadow.size:
            raise ValueError('본체·그림자의 시트 크기가 다르다.')
        directions = data['directions']
        if not isinstance(directions, dict) or not directions:
            raise ValueError('방향별 동작 대응이 필요하다.')
        for direction, name in directions.items():
            if not isinstance(direction, str) or not direction or name not in body.clips or name not in shadow.clips:
                raise ValueError('방향·동작 대응 불일치')
            first, second = body.clips[name], shadow.clips[name]
            if first != second:
                raise ValueError('본체·그림자의 FPS·프레임·피봇이 다르다.')
        return cls(data['asset_id'], body, shadow, directions, data['config_sha256'])


class SpritePlayback:
    def __init__(self, bundle):
        self.bundle = bundle
        self.direction = next(iter(bundle.directions))
        self.elapsed_seconds = 0.0
        self.paused = False

    @property
    def clip(self):
        return self.bundle.body.clips[self.bundle.directions[self.direction]]

    @property
    def frame_index(self):
        return int(self.elapsed_seconds * self.clip.fps + 1e-9) % len(self.clip.frames)

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError('재생 시간은 0 이상의 유한한 초 단위 값이어야 한다.')
        if not self.paused:
            self.elapsed_seconds += delta_seconds

    def select_direction(self, direction):
        if direction not in self.bundle.directions:
            raise ValueError('없는 방향')
        self.direction = direction

    def step(self):
        self.paused = True
        self.elapsed_seconds = (self.frame_index + 1) / self.clip.fps
