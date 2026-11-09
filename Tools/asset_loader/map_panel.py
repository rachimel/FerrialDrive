"""맵 번들 불러오기·레이어 합성·이동 구역 편집·내보내기 패널."""

from copy import deepcopy
from pathlib import Path

from ferrial_drive.assets import AssetDefinition
from ferrial_drive.assets.catalog import AssetDocument
from ferrial_drive.assets.maps import MapBundle
from ferrial_drive.assets.pico_assets import PicoAssetResource
from ferrial_drive.ui.components import Rect
from .file_panel import FilePanel
from .library import ROOT, asset_directory
from .map_export import export_map
from .widgets import Panel


VIEWS = [('background', '배경'), ('ground', '바닥'), ('composite', '합성 결과'), ('walkable', '이동 가능 구역')]


class MapPanel(Panel):
    title = '맵 작업'
    rect = Rect(48, 72, 1184, 656)
    preview = Rect(568, 190, 632, 404)
    error_x, error_y, error_width = 72, 610, 460

    def __init__(self, app):
        super().__init__(app)
        self.resource = None
        self.view = 'walkable'
        self.pending = []
        self.polygons = []
        self.extra = {}
        self.scale, self.origin = 1, (0, 0)
        current = getattr(app.handle.resource, 'map_bundle', None) if app.handle else None
        fields = [('asset_id', '맵 ID', 'map'), ('background', '배경 이미지', ''),
                  ('ground', '바닥 이미지', ''), ('width', '너비 px', '640'),
                  ('height', '높이 px', '360'), ('output', '출력 폴더', '')]
        self.labels = []
        for index, (key, label, value) in enumerate(fields):
            y = 166 + index * 64
            self.labels.append((label, y - 20))
            self.add_field(key, value, Rect(72, y, 360, 32))
        self.button('찾기', Rect(440, 230, 100, 32), lambda: self.browse_image('background'))
        self.button('찾기', Rect(440, 294, 100, 32), lambda: self.browse_image('ground'))
        self.button('맵 불러오기', Rect(72, 112, 160, 32), self.browse_map)
        self.button('미리보기 갱신', Rect(568, 112, 180, 32), self.refresh)
        self.choice('표시 선택', VIEWS, Rect(764, 112, 240, 32), self.select_view)
        self.button('구역 확정', Rect(568, 610, 140, 32), self.commit_polygon)
        self.button('점 취소', Rect(720, 610, 120, 32), self.undo_point)
        self.button('마지막 구역 삭제', Rect(852, 610, 200, 32), self.remove_polygon)
        self.button('내보내기', Rect(1040, 660, 160, 36), self.submit)
        self.button('닫기', Rect(896, 660, 120, 36), self.close)
        if current:
            self.load(app.source)

    def put(self, key, value):
        field = self.fields[key]
        field.text = str(value)
        field.cursor = len(field.text)

    def browse_image(self, key):
        self.app.set_panel(FilePanel(self.app, lambda path: self.select_image(key, path),
            extensions={'.png', '.jpg', '.jpeg', '.bmp'}, initial=self.value(key) or ROOT, parent=self))

    def select_image(self, key, path):
        pico = self.app.pico
        surface = pico.IMG_Load(str(path).encode('utf-8'))
        if not surface:
            raise ValueError('맵 이미지를 읽을 수 없다.')
        try:
            if key == 'background':
                self.put('width', surface.contents.w)
                self.put('height', surface.contents.h)
            self.put(key, path)
        finally:
            pico.SDL_FreeSurface(surface)

    def browse_map(self):
        self.app.set_panel(FilePanel(self.app, self.load, extensions={'.json'},
                                    initial=self.app.source or ROOT, parent=self))

    def load(self, path):
        bundle = MapBundle.load(path)
        # 실패한 불러오기는 현재 편집 내용을 교체하지 않는다.
        candidate = self.make_resource(bundle)
        self.close_resources()
        self.resource = candidate
        self.extra = deepcopy(bundle.data)
        self.polygons = deepcopy(bundle.data['walkable'])
        self.pending = []
        self.put('asset_id', bundle.data['asset_id'])
        for key in ('background', 'ground'):
            self.put(key, bundle.paths[key])
        self.put('width', bundle.size[0])
        self.put('height', bundle.size[1])
        self.put('output', '')

    def data(self):
        data = deepcopy(self.extra)
        data.pop('composite', None)
        data.update(version=1, type='map', asset_id=self.value('asset_id'), coordinates='bottom-left',
                    size=[int(self.value('width')), int(self.value('height'))],
                    background=str(Path(self.value('background')).expanduser().resolve()),
                    ground=str(Path(self.value('ground')).expanduser().resolve()), walkable=deepcopy(self.polygons))
        return data

    def make_resource(self, bundle):
        definition = AssetDefinition(bundle.data['asset_id'], 'map', ROOT / 'preview-map.json')
        document = AssetDocument(definition, bundle.sheets, tuple(bundle.paths.values()),
                                 bundle.data['asset_id'], 'composite', map_bundle=bundle)
        return PicoAssetResource(document, filtering=self.app.filtering)

    def refresh(self):
        bundle = MapBundle.from_data(self.data(), ROOT)
        candidate = self.make_resource(bundle)
        self.close_resources()
        self.resource = candidate

    def select_view(self, view):
        self.view = view

    def commit_polygon(self):
        data = self.data()
        data['walkable'].append(deepcopy(self.pending))
        MapBundle.from_data(data, ROOT)
        previous = self.polygons
        self.polygons = data['walkable']
        try:
            self.refresh()
        except Exception:
            self.polygons = previous
            raise
        self.pending = []

    def undo_point(self):
        if self.pending:
            self.pending.pop()

    def remove_polygon(self):
        if self.polygons:
            previous = self.polygons
            self.polygons = self.polygons[:-1]
            try:
                self.refresh()
            except Exception:
                self.polygons = previous
                raise

    def content_event(self, event):
        pico = self.app.pico
        if (event.type == pico.SDL_MOUSEBUTTONDOWN and event.button == pico.SDL_BUTTON_LEFT
                and self.preview.contains(event.x, event.y) and self.resource and self.view == 'walkable'):
            x = (event.x - self.origin[0]) / self.scale
            y = (800 - event.y - self.origin[1]) / self.scale
            width, height = self.resource.map_bundle.size
            if 0 <= x <= width and 0 <= y <= height:
                self.pending.append([round(x, 2), round(y, 2)])

    def submit(self):
        if self.pending:
            raise ValueError('작성 중인 구역을 확정하거나 점을 취소한다.')
        data = self.data()
        destination = Path(self.value('output')).expanduser().resolve() if self.value('output') else asset_directory(data['asset_id'])
        result = export_map(data, destination, base_dir=ROOT)
        if not self.app.open_source(result, asset_id=data['asset_id']):
            raise ValueError(self.app.message)
        self.app.message = f'맵 내보내기 완료: {result}'
        self.close()

    def close_resources(self):
        if self.resource:
            self.resource.close()
            self.resource = None

    def close(self):
        self.close_resources()
        super().close()

    def draw(self):
        super().draw()
        r, c = self.app.renderer, self.app.theme['colors']
        for label, y in self.labels:
            r.text(label, 72, y, 'small', c['muted'])
        r.text('빈 출력 경로: 에셋 라이브러리에 새 번들 생성', 72, 558, 'small', c['muted'], max_width=468)
        r.text('클릭으로 꼭짓점 추가 → 구역 확정', 568, 162, 'small', c['muted'])
        r.rect(self.preview, c['input'])
        if self.resource:
            width, height = self.resource.map_bundle.size
            self.scale = min((self.preview.width - 24) / width, (self.preview.height - 24) / height)
            self.origin = (self.preview.x + (self.preview.width - width * self.scale) / 2,
                           800 - self.preview.y - (self.preview.height + height * self.scale) / 2)
            with r.clip(self.preview):
                self.resource.draw(self.view, 0, *self.origin, scale=self.scale)
                points = [(self.origin[0] + x * self.scale, 800 - self.origin[1] - y * self.scale)
                          for x, y in self.pending]
                for a, b in zip(points, points[1:]):
                    r.line(*a, *b, c['accent'])
                for x, y in points:
                    r.rect(Rect(x - 3, y - 3, 6, 6), c['accent'])
        r.text(f'{dict(VIEWS)[self.view]} · 구역 {len(self.polygons)}개 · 작성 중 {len(self.pending)}점',
               568, 644, 'small', c['muted'])
        self.draw_choices()
