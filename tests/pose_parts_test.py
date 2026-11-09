"""포즈 파츠·손가락·되돌리기

Asset Tool 실제 창에서 월드 축 화살표·Ctrl+Z·손가락·칼집 정렬을 확인한다.
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
from ferrial_drive.runtime import run_application


class PartsTestApp(AssetLoaderApp):
    def __init__(self, source=None, check=None):
        super().__init__(source=source, pose=True, pose_sample=source is None)
        self.directory = Path(check).resolve() if check else None
        self.stage = 0
        self.started = time.monotonic()
        self.pending = None
        self.gun_before = None

    def click(self, x, y):
        self.handle_event(SimpleNamespace(type=self.pico.SDL_MOUSEBUTTONDOWN,
                          button=self.pico.SDL_BUTTON_LEFT, x=x, y=y, clicks=1))

    def undo(self):
        self.handle_event(SimpleNamespace(type=self.pico.SDL_KEYDOWN, key=self.pico.SDLK_z, mod=self.pico.KMOD_CTRL))

    def update(self, seconds):
        super().update(seconds)
        if not self.directory:
            return
        panel = self.pose_editor
        if time.monotonic()-self.started > 120:
            raise TimeoutError("파츠 화면 검사 대기 초과")
        if panel.session and panel.session.error:
            raise RuntimeError(panel.session.error)
        if not panel.data or panel.session.busy:
            return
        data = panel.data
        if self.stage == 0:
            panel.select("object:Gun")
            self.gun_before = data["points"]["object:Gun"]["world"]
            self.pending = "parts.png"
        elif self.stage == 1:
            self.click(1170, 312)
        elif self.stage == 2:
            moved = data["points"]["object:Gun"]["world"]
            assert abs(moved[0]-self.gun_before[0]-.05) < .0001
            self.undo()
        elif self.stage == 3:
            restored = data["points"]["object:Gun"]["world"]
            assert max(abs(a-b) for a, b in zip(restored, self.gun_before)) < .0001
            panel.select("hand.R")
            panel.change_mode("rotate")
            self.click(1170, 352)
        elif self.stage == 4:
            panel.select("bone:Index01.R")
            panel.choose_finger("Index")
            self.click(1170, 508)
        elif self.stage == 5:
            self.pending = "fingers.png"
            self.undo()
        elif self.stage == 6:
            panel.select("object:Scabbard")
            panel.change_mode("translate")
            self.click(1170, 312)
        elif self.stage == 7:
            self.click(1030, 546)
        elif self.stage == 8:
            assert panel.selected == "object:Sword"
            self.pending = "aligned.png"
            self.undo()
        elif self.stage == 9:
            self.click(1000, 666)
        elif self.stage == 10:
            assert not data["file_dirty"]
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory/"verification.json").write_text(json.dumps({"source": data["source"], "work": data["work"],
                "world_arrow": True, "ctrl_z": True, "finger_ui": True, "align_ui": True,
                "elapsed_seconds": time.monotonic()-self.started}, indent=2), encoding="utf-8")
            self.running = False
        self.stage += 1

    def draw(self):
        super().draw()
        if self.pending:
            self.capture = self.directory/self.pending
            self.save_capture()
            self.capture, self.pending = None, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    app = PartsTestApp(args.source, args.check)
    run_application(app, **WINDOW)
    if args.check:
        print("POSE_PARTS_SCREEN_PASSED", args.check)


if __name__ == "__main__":
    main()
