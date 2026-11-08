"""프리렌더 에셋 불러오기

Blender 기본 도형의 8방향 본체·그림자를 렌더하고 시트로 묶어 재생한다.
방향·프레임·발 기준점과 분리된 그림자의 정렬을 독립적으로 확인한다.
"""

import argparse
from pathlib import Path
import sys
from time import sleep

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ferrial_drive.assets import SpriteBundle, SpritePlayback
from ferrial_drive.assets.pico_sprites import PicoSprite
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.pico_renderer import PicoRenderer
from ferrial_drive.ui.standalone import run_preview
from Tools.blender_pipeline.asset_build import AssetBuild
from Tools.theme_reference import load_theme


UNIT_TEST_ENTRYPOINT = 'standalone'
WINDOW = {'width': 1280, 'height': 720, 'title': 'Ferrial Drive | Asset Load Test'}
DEFAULT_CONFIG = PROJECT_ROOT / 'samples/asset_load_test/render_config.json'
DIRECTION_LABELS = {'e': '동', 'ne': '북동', 'n': '북', 'nw': '북서',
                    'w': '서', 'sw': '남서', 's': '남', 'se': '남동'}


class AssetLoadTest:
    render_driver = 'opengl'
    def __init__(self, *, config=DEFAULT_CONFIG, blender=None, bundle=None, rebuild=False, scene=None):
        self.running = True
        self.build = AssetBuild(config, blender=blender, source_blend=scene)
        self.bundle_path = Path(bundle).resolve() if bundle else None
        self.rebuild = rebuild
        self.renderer = self.sprite = self.playback = None
        self.body_visible = self.shadow_visible = True
        self.message = '렌더 준비'
        self.error = False
        self.selected = 0
        self.buttons = [('재렌더 R', 'render', Rect(28, 618, 142, 38)),
                        ('재생/정지 Space', 'pause', Rect(182, 618, 184, 38)),
                        ('다음 프레임 .', 'step', Rect(378, 618, 166, 38)),
                        ('본체 B', 'body', Rect(556, 618, 112, 38)),
                        ('그림자 S', 'shadow', Rect(680, 618, 124, 38))]
        self.mouse = (-1, -1)

    def enter(self):
        import pico2d.pico2d as pico
        self.pico = pico
        self.theme = load_theme()
        paths = {role: PROJECT_ROOT / 'data/fonts' / entry['path'] for role, entry in self.theme['fonts'].items()}
        sizes = {role: entry['size'] for role, entry in self.theme['fonts'].items()}
        self.renderer = PicoRenderer(paths, sizes)
        try:
            cached = None if self.rebuild else self.bundle_path or self.build.cached_result()
            if cached:
                self.load_bundle(cached)
            else:
                self.start_build()
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            self.fail(error)

    def fail(self, error):
        self.message, self.error = str(error), True
        print(f'ASSET_ERROR {self.message}', file=sys.stderr, flush=True)

    def load_bundle(self, path):
        bundle = SpriteBundle.load(path)
        sprite = PicoSprite(bundle)
        if self.sprite:
            self.sprite.close()
        self.sprite, self.playback = sprite, SpritePlayback(bundle)
        self.selected = 0
        self.bundle_path = Path(path)
        count = len(next(iter(bundle.body.clips.values())).frames)
        self.message = f'렌더 결과 로딩 완료 · {len(bundle.directions)}방향 / {count}프레임 / 본체·그림자 분리'
        self.error = False
        print(f'ASSET_READY {path}', flush=True)

    def start_build(self):
        if self.build.process is not None:
            return
        self.build.start()
        self.message, self.error = self.build.progress_text, False

    def action(self, action):
        if action == 'render':
            try:
                self.start_build()
            except (OSError, ValueError, RuntimeError) as error:
                self.fail(error)
        elif action == 'body':
            self.body_visible = not self.body_visible
        elif action == 'shadow':
            self.shadow_visible = not self.shadow_visible
        elif self.playback:
            if action == 'pause':
                self.playback.paused = not self.playback.paused
            elif action == 'step':
                self.playback.step()

    def handle_event(self, event):
        pico = self.pico
        if event.type in (pico.SDL_MOUSEMOTION, pico.SDL_MOUSEBUTTONDOWN):
            self.mouse = (event.x, event.y)
            if event.type == pico.SDL_MOUSEBUTTONDOWN and event.button == pico.SDL_BUTTON_LEFT:
                for _, action, rect in self.buttons:
                    if rect.contains(*self.mouse):
                        self.action(action)
                if self.playback:
                    for index, _ in enumerate(self.playback.bundle.directions):
                        if Rect(28 + index * 106, 132, 98, 198).contains(*self.mouse):
                            self.select(index)
        elif event.type == pico.SDL_KEYDOWN:
            if event.key == pico.SDLK_ESCAPE:
                self.running = False
            elif event.key in (pico.SDLK_LEFT, pico.SDLK_RIGHT) and self.playback:
                self.select(self.selected + (-1 if event.key == pico.SDLK_LEFT else 1))
            else:
                actions = {pico.SDLK_r: 'render', pico.SDLK_SPACE: 'pause', pico.SDLK_PERIOD: 'step',
                           pico.SDLK_b: 'body', pico.SDLK_s: 'shadow'}
                if event.key in actions:
                    self.action(actions[event.key])

    def select(self, index):
        directions = list(self.playback.bundle.directions)
        self.selected = index % len(directions)
        self.playback.select_direction(directions[self.selected])

    def update(self, delta_seconds):
        result = self.build.poll()
        if result is False:
            self.fail(self.build.error)
        elif result is True:
            try:
                self.load_bundle(self.build.result)
            except (OSError, ValueError, KeyError, RuntimeError) as error:
                self.fail(error)
        elif self.build.process is not None:
            self.message, self.error = self.build.progress_text, False
        if self.playback:
            self.playback.update(delta_seconds)

    def draw(self):
        r, colors = self.renderer, self.theme['colors']
        r.clear(colors['background'])
        r.text('프리렌더 에셋 불러오기', 28, 24, 'title', colors['text'])
        r.text(self.message, 28, 66, 'body', colors['error'] if self.error else colors['accent'], max_width=1216)
        r.text('Blender → 8방향 PNG → 스프라이트 시트 → Pico2D 재생', 28, 100, 'small', colors['muted'])
        if self.playback:
            playback = self.playback
            for index, direction in enumerate(playback.bundle.directions):
                x = 28 + index * 106
                r.rect(Rect(x, 132, 98, 198), colors['selected'] if index == self.selected else colors['panel'])
                r.text(f'{index + 1:02} {DIRECTION_LABELS.get(direction, direction)}', x + 10, 146, 'small', colors['text'])
                self.draw_sprite(direction, playback.frame_index, x + 49, 460, 1)
            direction = playback.direction
            r.text(f'{DIRECTION_LABELS.get(direction, direction)} / 프레임 {playback.frame_index + 1}/{len(playback.clip.frames)}',
                   930, 354, 'body', colors['text'])
            r.text(f'{playback.clip.fps:g} FPS / {"정지" if playback.paused else "재생"}',
                   930, 390, 'small', colors['muted'])
            self.draw_sprite(direction, playback.frame_index, 300, 190, 3)
            r.text('3배 확대 · 발 기준점 고정', 200, 570, 'small', colors['muted'])
            self.draw_sprite(direction, playback.frame_index, 710, 190, 3, body=False, shadow=True)
            r.text('분리 그림자', 650, 570, 'small', colors['muted'])
            r.text('주황색 = 모델 앞쪽', 930, 168, 'small', colors['warning'])
            r.text(f'본체 {"ON" if self.body_visible else "OFF"}', 930, 210, 'body', colors['text'])
            r.text(f'그림자 {"ON" if self.shadow_visible else "OFF"}', 930, 246, 'body', colors['text'])
            r.text(f'시트 {playback.bundle.body.size[0]}×{playback.bundle.body.size[1]}', 930, 294, 'small', colors['muted'])
        else:
            r.text('렌더 결과를 기다리는 중이다. 실패하면 오류와 로그를 확인한다.', 28, 188, 'body', colors['muted'])
        for label, _, rect in self.buttons:
            r.rect(rect, colors['button_hover'] if rect.contains(*self.mouse) else colors['button'])
            r.text(label, rect.x + 10, rect.y + 9, 'small', colors['button_text'])
        if self.build.directory:
            relative = self.build.directory.relative_to(self.build.output_root)
            r.text(f'출력·로그: output/asset_load_test/{relative}/', 28, 594, 'small', colors['muted'], max_width=1216)
        r.text('방향: 카드 클릭 / ← →   ·   Esc: 종료   ·   렌더 중 창을 닫으면 작업도 중단한다.',
               28, 680, 'small', colors['muted'])

    def draw_sprite(self, direction, frame, x, y, scale, **layers):
        colors = self.theme['colors']
        # 지면 피봇은 Pico2D의 왼쪽 아래 좌표다. UI 라인은 위쪽 좌표로 변환한다.
        self.renderer.line(x - 12, 720 - y, x + 12, 720 - y, colors['line'])
        self.renderer.line(x, 720 - y - 5, x, 720 - y + 5, colors['line'])
        self.sprite.draw(direction, frame, x, y, scale=scale,
                         body=layers.get('body', self.body_visible), shadow=layers.get('shadow', self.shadow_visible))

    def exit(self):
        self.build.close()
        if self.sprite:
            self.sprite.close()
            self.sprite = None
        if self.renderer:
            self.renderer.close()
            self.renderer = None


def create_test(**kwargs):
    return AssetLoadTest(**kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames', type=int)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--blender', type=Path)
    parser.add_argument('--bundle', type=Path, help='기존 번들만 불러오며 Blender 없이 재생')
    parser.add_argument('--scene', type=Path, help='샘플 도형 대신 렌더할 저장 Blender 장면')
    parser.add_argument('--rebuild', action='store_true')
    parser.add_argument('--build-only', action='store_true', help='창 없이 렌더·패킹·메타데이터 검증')
    args = parser.parse_args()
    if args.bundle and (args.rebuild or args.build_only or args.scene):
        parser.error('--bundle은 --scene/--rebuild/--build-only와 함께 사용할 수 없다.')
    if args.build_only:
        job = AssetBuild(args.config, blender=args.blender, source_blend=args.scene)
        try:
            job.start()
            while job.process is not None:
                result = job.poll()
                if result is False:
                    raise RuntimeError(job.error)
                sleep(0.05)
            print(f'ASSET_BUILT {job.result}')
        finally:
            job.close()
        return
    program = create_test(config=args.config, blender=args.blender, bundle=args.bundle, rebuild=args.rebuild,
                          scene=args.scene)
    run_preview(program, **WINDOW, frame_limit=args.frames)
    if program.error:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
