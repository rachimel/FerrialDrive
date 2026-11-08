"""FDrive 공통 OpenGL 렌더링

공개 도형 에셋을 배치로 표시하고 SDL 도형과의 합성을 확인한다.
1/2/3으로 Nearest/Linear/Bicubic을 바꾸고 Esc로 종료한다.
"""

import argparse
from importlib.resources import files
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ferrial_drive.assets import AssetCatalog, AssetManager
from ferrial_drive.assets.pico_assets import PicoAssetBackend
from ferrial_drive.rendering import renderer_info
from ferrial_drive.runtime import run_application


UNIT_TEST_ENTRYPOINT = 'standalone'


class RenderingTest:
    def __init__(self):
        self.running = True
        self.elapsed_seconds = 0.0
        self.manager = self.font = None

    def enter(self):
        import pico2d.pico2d as pico
        self.pico = pico
        self.driver = renderer_info(pico).name
        self.manager = AssetManager(AssetCatalog.load(ROOT / 'samples/asset_loader/catalog.json'), PicoAssetBackend())
        self.handle = self.manager.acquire('sample_mech')
        self.font = pico.load_font(str(files('pico2d').joinpath('data', 'ConsolaMalgun.ttf')), 18)

    def handle_event(self, event):
        p = self.pico
        if event.type == p.SDL_WINDOWEVENT and event.window_event == p.SDL_WINDOWEVENT_CLOSE:
            self.running = False
        if event.type != p.SDL_KEYDOWN:
            return
        if event.key == p.SDLK_ESCAPE:
            self.running = False
        modes = {p.SDLK_1: 'nearest', p.SDLK_2: 'linear', p.SDLK_3: 'bicubic'}
        if event.key in modes:
            self.handle.resource.set_filtering(modes[event.key])

    def update(self, delta_seconds):
        self.elapsed_seconds += delta_seconds

    def draw(self):
        p = self.pico
        p.SDL_SetRenderDrawColor(p.renderer, 10, 20, 27, 255)
        p.SDL_RenderClear(p.renderer)
        resource = self.handle.resource
        clip = resource.clips['idle/s']
        frame = int(self.elapsed_seconds * clip.fps) % len(clip.frames)
        with resource.render_batch():
            for y in range(3):
                for x in range(5):
                    resource.draw('idle/s', frame, 80 + x * 155, 90 + y * 150, scale=0.8)
        # 배치 밖의 SDL 그리기도 정상적으로 이어져야 한다.
        p.SDL_SetRenderDrawColor(p.renderer, 60, 125, 145, 255)
        p.SDL_RenderDrawLine(p.renderer, 24, 86, 876, 86)
        self.font.draw(24, 565, f'FDrive | {self.driver} | {resource.filtering}', (210, 225, 230))
        self.font.draw(24, 535, '1 Nearest / 2 Linear / 3 Bicubic / Esc 종료', (140, 165, 175))

    def exit(self):
        if self.manager is not None:
            self.manager.close()
        if self.font is not None:
            self.pico.TTF_CloseFont(self.font.font)
            self.font = None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames', type=int)
    args = parser.parse_args()
    run_application(RenderingTest(), width=900, height=600, title='FDrive | Rendering', frame_limit=args.frames)
