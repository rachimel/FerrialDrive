"""포즈 편집 패널의 단일 창 연결·입력·결과 전달 계약."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from Tools.asset_loader.app import AssetLoaderApp
from Tools.asset_loader.pose_panel import PosePanel
from Tools.pose_tool.session import PoseSession


def fake_state():
    return {"frame": 1, "start": 1, "end": 24, "active": "idle", "dirty": False,
            "file_dirty": False, "points": {"hand.R": {"uv": [.5, .5, 1], "world": [1, 2, 3]}},
            "right": [1, 0, 0], "up": [0, 0, 1], "scale": 4,
            "equipment": {"gun_stowed": 1}, "exported": None,
            "clips": [{"name": "idle", "label": "대기"}], "errors": {}}


class PosePanelTests(unittest.TestCase):
    def setUp(self):
        self.app = AssetLoaderApp(catalog=Path("unused.json"))
        self.app.pico = SimpleNamespace(SDL_MOUSEBUTTONDOWN=1, SDL_MOUSEMOTION=2, SDL_MOUSEBUTTONUP=3,
            SDL_MOUSEWHEEL=4, SDL_BUTTON_LEFT=1, SDL_StartTextInput=lambda: None, SDL_StopTextInput=lambda: None)
        self.panel = PosePanel(self.app)
        self.panel.session = SimpleNamespace(state=fake_state(), busy=False, send=Mock())

    def test_toolbar_opens_same_pose_panel_and_preserves_session(self):
        self.app.pose_editor = self.panel
        session = self.panel.session
        self.app.action("pose")
        self.assertIs(self.app.panel, self.panel)
        self.panel.close()
        self.app.action("pose")
        self.assertIs(self.panel.session, session)

    def test_drag_uses_camera_plane_in_world_units(self):
        p = self.panel
        x, y = p.preview.x+p.preview.width*.5, p.preview.y+p.preview.height*.5
        p.content_event(SimpleNamespace(type=1, button=1, x=x, y=y))
        p.content_event(SimpleNamespace(type=2, x=x+28, y=y-56))
        p.session.send.assert_called_with("move", control="hand.R", world=[1.2, 2, 3.4])
        p.content_event(SimpleNamespace(type=3, button=1))
        self.assertIsNone(p.drag)

    def test_no_drag_starts_while_model_update_in_progress(self):
        self.panel.session.busy = True
        self.panel.content_event(SimpleNamespace(type=1, button=1, x=592, y=440))
        self.assertIsNone(self.panel.drag)

    def test_rotation_and_equipment_use_explicit_commands(self):
        self.panel.rotate("Z", -1)
        self.panel.session.send.assert_called_with("rotate", control="hand.R", axis="Z", degrees=-5)
        self.panel.toggle_equipment("gun_stowed")
        self.panel.session.send.assert_called_with("equipment", property="gun_stowed", value=0)

    def test_render_transfer_requires_current_finished_export(self):
        with self.assertRaises(ValueError):
            self.panel.to_render()
        self.panel.session.state["exported"] = "example.json"
        self.panel.session.state["file_dirty"] = True
        with self.assertRaises(ValueError):
            self.panel.to_render()

    def test_only_consecutive_moves_are_coalesced_and_key_keeps_order(self):
        session = PoseSession.__new__(PoseSession)
        from collections import deque
        session.queue = deque()
        session.inflight = True
        session.process = SimpleNamespace(poll=lambda: None)
        session.send("move", control="hand.R", world=[1, 2, 3])
        session.send("move", control="hand.R", world=[2, 3, 4])
        session.send("key")
        session.send("move", control="hand.R", world=[3, 4, 5])
        self.assertEqual([row["command"] for row in session.queue], ["move", "key", "move"])
        self.assertEqual(session.queue[0]["world"], [2, 3, 4])


if __name__ == "__main__":
    unittest.main()
