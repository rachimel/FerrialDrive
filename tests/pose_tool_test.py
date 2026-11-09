"""Asset Tool 포즈 편집

한 창에서 손바닥·발 목표와 관절 방향을 조절하고 키·작업본·동작을 저장한다.
기본 도형 샘플 또는 지정한 모델을 사용한다.
"""

import argparse
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
UNIT_TEST_ENTRYPOINT = "standalone"

from Tools.asset_loader.app import AssetLoaderApp, WINDOW
from Tools.asset_loader.pose_panel import PosePanel
from ferrial_drive.runtime import run_application


class PoseTestApp(AssetLoaderApp):
    def __init__(self, source=None, check=None):
        super().__init__(source=source, pose=True, pose_sample=source is None)
        self.check_directory = Path(check).resolve() if check else None
        self.stage = 0
        self.started = time.monotonic()
        self.check_error = None
        self.capture_pending = None

    def click(self, x, y):
        self.handle_event(SimpleNamespace(type=self.pico.SDL_MOUSEBUTTONDOWN,
                          button=self.pico.SDL_BUTTON_LEFT, x=x, y=y, clicks=1))

    def update(self, seconds):
        super().update(seconds)
        if not self.check_directory:
            return
        panel = self.pose_editor
        if time.monotonic()-self.started > 90:
            raise TimeoutError("포즈 통합 화면 검사 대기 초과")
        if panel.session and panel.session.error:
            raise RuntimeError(panel.session.error)
        if not panel.data or panel.session.busy:
            return
        data = panel.data
        if self.stage == 0:
            self.capture_pending = "initial.png"
            self.stage = 1
        elif self.stage == 1:
            x, y, _ = data["points"]["hand.R"]["uv"]
            x, y = panel.preview.x+x*640, panel.preview.y+(1-y)*560
            self.click(x, y)
            assert panel.selected == "hand.R", panel.selected
            self.handle_event(SimpleNamespace(type=self.pico.SDL_MOUSEMOTION, x=x+20, y=y-12))
            self.handle_event(SimpleNamespace(type=self.pico.SDL_MOUSEBUTTONUP,
                              button=self.pico.SDL_BUTTON_LEFT, x=x+20, y=y-12))
            self.stage = 2
        elif self.stage == 2:
            assert data["dirty"]
            self.click(980, 626)
            self.stage = 3
        elif self.stage == 3:
            assert not data["dirty"]
            self.click(980, 666)
            self.stage = 4
        elif self.stage == 4:
            assert not data["file_dirty"]
            self.capture_pending = "edited.png"
            self.click(1150, 666)
            self.stage = 5
        elif self.stage == 5:
            assert data["exported"]
            self.click(1080, 704)
            from Tools.asset_loader.editors import RenderPanel
            assert isinstance(self.panel, RenderPanel)
            assert self.panel.value("animation") == data["active"]
            assert self.panel.value("width") == "240"
            assert Path(self.panel.value("source")).is_file()
            self.capture_pending = "render_settings.png"
            self.stage = 6
            self.check_directory.mkdir(parents=True, exist_ok=True)
            (self.check_directory / "verification.json").write_text(json.dumps({
                "work": data["work"], "exported": data["exported"], "drag_key_save_export_render": True,
                "elapsed_seconds": time.monotonic()-self.started}, indent=2), encoding="utf-8")

    def draw(self):
        super().draw()
        if self.capture_pending:
            self.capture = self.check_directory / self.capture_pending
            self.save_capture()
            self.capture = None
            self.capture_pending = None
            if self.stage == 6:
                self.running = False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--check", type=Path, help="실제 창에서 드래그·저장·출력을 검사하고 캡처한다.")
    args = parser.parse_args()
    app = PoseTestApp(args.source, args.check)
    run_application(app, **WINDOW)
    if args.check:
        print("POSE_PANEL_CHECK_PASSED", args.check)


if __name__ == "__main__":
    main()
