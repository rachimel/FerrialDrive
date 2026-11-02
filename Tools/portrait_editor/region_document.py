"""Portable rough region hints. These masks describe intent, not extracted parts."""
from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import tempfile
import uuid
import zipfile

import numpy as np
import pygame

MAX_PIXELS = 16_777_216
MAX_REGIONS = 24
MAX_POINTS = 250_000


def read_image(value):
    image = pygame.image.load(value)
    w, h = image.get_size()
    if max(w, h) > 8192 or w * h > MAX_PIXELS:
        raise ValueError('이미지는 최대 8192px / 1,677만 픽셀까지 열 수 있어.')
    return image


def png_bytes(image):
    stream = io.BytesIO()
    pygame.image.save(image, stream, 'image.png')
    return stream.getvalue()


def overlay(image, mask):
    result = image.copy().convert_alpha()
    tint = pygame.Surface(image.get_size(), pygame.SRCALPHA)
    tint.fill((235, 149, 184, 0))
    alpha = pygame.surfarray.pixels_alpha(tint)
    alpha[:] = (pygame.surfarray.array2d(mask) > 0) * 105
    del alpha
    result.blit(tint, (0, 0))
    return result


class RegionDocument:
    def __init__(self, image, source_name='source.png'):
        self.image = image
        self.source_name = source_name
        self.regions = [self.new_region('영역 1')]
        self.selected = 0
        self.path = None
        self.saved = None
        self.undo_stack = []
        self.redo_stack = []
        self._masks = {}

    @staticmethod
    def new_region(name):
        return {'id': uuid.uuid4().hex[:12], 'name': name, 'strokes': []}

    @property
    def dirty(self):
        return self.saved != self.regions

    @property
    def current(self):
        return self.regions[self.selected]

    def checkpoint(self):
        self.undo_stack.append((copy.deepcopy(self.regions), self.selected))
        self.undo_stack = self.undo_stack[-40:]
        self.redo_stack.clear()

    def undo(self, redo=False):
        source, target = (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        if not source:
            return
        target.append((copy.deepcopy(self.regions), self.selected))
        self.regions, self.selected = source.pop()
        self._masks.clear()

    def add(self):
        if len(self.regions) >= MAX_REGIONS:
            raise ValueError(f'영역은 최대 {MAX_REGIONS}개까지 만들 수 있어.')
        self.checkpoint()
        self.regions.append(self.new_region(f'영역 {len(self.regions) + 1}'))
        self.selected = len(self.regions) - 1

    def remove(self):
        if len(self.regions) == 1:
            raise ValueError('마지막 영역은 삭제 대신 비우기를 사용해 줘.')
        self.checkpoint()
        del self.regions[self.selected]
        self.selected = min(self.selected, len(self.regions) - 1)
        self._masks.clear()

    def rename(self, name):
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError('영역 이름은 1~80자로 입력해 줘.')
        if name != self.current['name']:
            self.checkpoint()
            self.current['name'] = name

    def clear(self):
        self.checkpoint()
        self.current['strokes'].clear()
        self._masks.pop(self.current['id'], None)

    @staticmethod
    def draw_segment(mask, stroke, a, b):
        value = 0 if stroke['erase'] else 255
        radius = stroke['radius']
        pygame.draw.line(mask, value, a, b, radius * 2)
        pygame.draw.circle(mask, value, a, radius)
        pygame.draw.circle(mask, value, b, radius)

    def mask(self, index=None):
        region = self.regions[self.selected if index is None else index]
        if region['id'] not in self._masks:
            mask = pygame.Surface(self.image.get_size(), depth=8)
            mask.set_palette([(i, i, i) for i in range(256)])
            mask.fill(0)
            for stroke in region['strokes']:
                points = stroke['points']
                self.draw_segment(mask, stroke, points[0], points[0])
                for a, b in zip(points, points[1:]):
                    if a is not None and b is not None:
                        self.draw_segment(mask, stroke, a, b)
                    elif b is not None:
                        self.draw_segment(mask, stroke, b, b)
            # Keep just the selected working raster; strokes remain the source of truth.
            self._masks = {region['id']: mask}
        return self._masks[region['id']]

    def start_stroke(self, point, radius, erase):
        if sum(len(s['points']) for r in self.regions for s in r['strokes']) >= MAX_POINTS:
            raise ValueError('마스크 점 수가 한도에 도달했어. 작업을 나눠 줘.')
        self.checkpoint()
        mask = self.mask()
        stroke = {'erase': bool(erase), 'radius': max(1, int(radius)), 'points': [point]}
        self.current['strokes'].append(stroke)
        self.draw_segment(mask, stroke, point, point)

    def extend_stroke(self, point):
        stroke = self.current['strokes'][-1]
        previous = stroke['points'][-1]
        if previous == point:
            return
        if sum(len(s['points']) for r in self.regions for s in r['strokes']) >= MAX_POINTS:
            raise ValueError('마스크 점 수가 한도에 도달했어.')
        stroke['points'].append(point)
        if point is not None:
            self.draw_segment(self.mask(), stroke, previous or point, point)

    def save(self, path):
        path = Path(path)
        if not path.name.lower().endswith('.regions.zip'):
            raise ValueError('원본 이미지를 덮어쓰지 않도록 .regions.zip 이름으로 저장해 줘.')
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {'kind': 'ai-region-hints', 'version': 1, 'source_name': self.source_name,
                   'size': list(self.image.get_size()), 'regions': self.regions}
        fd, temporary = tempfile.mkstemp(prefix='.regions-', suffix='.tmp', dir=path.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('source.png', png_bytes(self.image))
                archive.writestr('regions.json', json.dumps(payload, ensure_ascii=False))
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.path = path
        self.saved = copy.deepcopy(self.regions)

    @classmethod
    def load(cls, path):
        with zipfile.ZipFile(path) as archive:
            if set(archive.namelist()) != {'source.png', 'regions.json'}:
                raise ValueError('영역 작업 파일 형식이 맞지 않아.')
            if any(entry.file_size > 128 * 1024 * 1024 for entry in archive.infolist()):
                raise ValueError('작업 파일이 너무 커.')
            payload = json.loads(archive.read('regions.json'))
            image = read_image(io.BytesIO(archive.read('source.png')))
        if payload.get('kind') != 'ai-region-hints' or payload.get('version') != 1:
            raise ValueError('지원하지 않는 영역 작업 파일이야.')
        if payload.get('size') != list(image.get_size()):
            raise ValueError('원본 크기와 마스크 좌표가 맞지 않아.')
        regions = payload.get('regions')
        if not isinstance(regions, list) or not 1 <= len(regions) <= MAX_REGIONS:
            raise ValueError('영역 개수가 올바르지 않아.')
        ids = set()
        points_count = 0
        for region in regions:
            identity, name = region.get('id'), region.get('name')
            if not isinstance(identity, str) or len(identity) != 12 or any(c not in '0123456789abcdef' for c in identity) or identity in ids:
                raise ValueError('영역 식별자가 올바르지 않아.')
            ids.add(identity)
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise ValueError('영역 이름이 올바르지 않아.')
            if not isinstance(region.get('strokes'), list):
                raise ValueError('마스크 기록이 올바르지 않아.')
            for stroke in region['strokes']:
                if type(stroke.get('erase')) is not bool or type(stroke.get('radius')) is not int or not 1 <= stroke['radius'] <= 8192:
                    raise ValueError('브러시 기록이 올바르지 않아.')
                points = stroke.get('points')
                if not isinstance(points, list) or not points or points[0] is None:
                    raise ValueError('마스크 좌표 기록이 올바르지 않아.')
                points_count += len(points)
                if points_count > MAX_POINTS:
                    raise ValueError('마스크 점 수가 한도를 넘었어.')
                for point in points:
                    if point is None:
                        continue
                    if not isinstance(point, list) or len(point) != 2 or any(type(v) is not int for v in point) or not (0 <= point[0] < image.get_width() and 0 <= point[1] < image.get_height()):
                        raise ValueError('마스크 좌표가 원본 범위를 벗어났어.')
        result = cls(image, str(payload.get('source_name', 'source.png')))
        result.regions = regions
        result.path = Path(path)
        result.saved = copy.deepcopy(regions)
        return result

    def export(self, parent):
        # Validate all regions before creating any output directory.
        bounds = []
        for index, region in enumerate(self.regions):
            values = pygame.surfarray.array2d(self.mask(index))
            x, y = np.nonzero(values)
            if not len(x):
                raise ValueError(f'「{region["name"]}」에 영역을 칠해 줘. 빈 영역은 삭제해도 돼.')
            bounds.append([int(x.min()), int(y.min()), int(x.max()) + 1, int(y.max()) + 1])
        output = Path(parent) / ('ai-regions-' + uuid.uuid4().hex[:12])
        output.mkdir(parents=True, exist_ok=False)
        pygame.image.save(self.image, str(output / 'source.png'))
        entries = []
        for index, region in enumerate(self.regions):
            stem = f'{index + 1:02d}-{region["id"]}'
            mask = self.mask(index)
            pygame.image.save(mask, str(output / f'{stem}.mask.png'))
            pygame.image.save(overlay(self.image, mask), str(output / f'{stem}.guide.png'))
            entries.append({'id': region['id'], 'name': region['name'], 'mask': f'{stem}.mask.png',
                            'guide': f'{stem}.guide.png', 'bounds_xyxy': bounds[index]})
        manifest = {'kind': 'ai-region-hints', 'version': 1, 'source': 'source.png',
                    'size': list(self.image.get_size()), 'origin': 'top-left',
                    'mask_meaning': 'white=rough target region; black=outside; not a precise alpha matte',
                    'regions': entries}
        (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        names = '\n'.join(f'- {r["name"]}: {r["mask"]} / {r["guide"]}' for r in entries)
        request = ('첨부한 source.png가 원본이고, 아래 마스크의 흰색과 분홍 표시가 추출할 영역의 대략적인 위치야.\n'
                   '마스크 경계를 그대로 자르지 말고 실제 그림의 경계를 판단해 줘. 각 영역을 별도 투명 PNG로 추출해 줘.\n'
                   '원본 캔버스 크기와 파츠 위치를 유지하고, 색과 그림체를 보존해 줘.\n'
                   '다른 파츠에 가려진 부분은 리깅할 때 드러날 수 있으니 필요한 범위를 복원해 줘.\n'
                   '분리·복원하기 어려운 부분은 임의로 완료했다고 하지 말고 알려 줘.\n\n' + names + '\n')
        (output / 'request.txt').write_text(request, encoding='utf-8')
        return output
