"""포즈 편집 패널의 단일 창 연결·입력·결과 전달 계약."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, Mock, patch
import tempfile

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

    def test_toolbar_launches_native_blender_and_preserves_legacy_session(self):
        self.app.pose_editor = self.panel
        session = self.panel.session
        with patch("Tools.pose_tool.run.launch_native") as launch:
            self.app.action("pose")
            launch.assert_called_once_with(self.app.model_source, sample=False)
        self.assertIsNone(self.app.panel)
        self.assertIs(self.panel.session, session)

    def test_drag_uses_camera_plane_in_world_units(self):
        p = self.panel
        x, y = p.preview.x+p.preview.width*.5, p.preview.y+p.preview.height*.5
        p.content_event(SimpleNamespace(type=1, button=1, x=x, y=y))
        p.content_event(SimpleNamespace(type=2, x=x+28, y=y-56))
        p.session.send.assert_called_with("move", control="hand.R", world=[1.2, 2, 3.4], gesture=ANY)
        p.content_event(SimpleNamespace(type=3, button=1))
        self.assertIsNone(p.drag)

    def test_no_drag_starts_while_model_update_in_progress(self):
        self.panel.session.busy = True
        self.panel.content_event(SimpleNamespace(type=1, button=1, x=592, y=440))
        self.assertIsNone(self.panel.drag)

    def test_new_render_source_replaces_cached_pose_session(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = Path(directory)/"old.blend", Path(directory)/"chosen.blend"
            old.touch()
            new.touch()
            self.panel.loaded_source = old.resolve()
            self.panel.session.close = Mock()
            self.app.pose_editor = self.panel
            replacement = SimpleNamespace(state=None)
            with patch("Tools.asset_loader.pose_panel.PoseSession", return_value=replacement) as start:
                self.app.configure_render(new)
                self.app.configure_pose()
            start.assert_called_once_with(new.resolve(), sample=False, clip=None)
            self.assertIs(self.panel.session, replacement)
            self.assertEqual(self.panel.value("source"), str(new.resolve()))

    def test_file_picker_open_loads_exact_selected_file(self):
        self.panel.open_model = Mock()
        self.panel.load_source("chosen.blend")
        self.panel.open_model.assert_called_once()
        self.assertEqual(self.panel.value("source"), str(Path("chosen.blend").resolve()))

    def test_sample_reopen_does_not_restore_an_older_model(self):
        self.app.model_source = Path("old.blend").resolve()
        self.panel.session.close = Mock()
        replacement = SimpleNamespace(state=None)
        self.app.pose_editor = self.panel
        with patch("Tools.asset_loader.pose_panel.PoseSession", return_value=replacement) as start:
            self.panel.open_model(sample=True)
            self.app.configure_pose()
        start.assert_called_once_with(None, sample=True, clip=None)
        self.assertIsNone(self.app.model_source)
        self.assertEqual(self.panel.value("source"), "")

    def test_unsaved_session_is_preserved_when_another_file_is_requested(self):
        self.panel.session.state["dirty"] = True
        self.panel.open_model = Mock(wraps=self.panel.open_model)
        previous = self.panel.session
        self.app.pose_editor = self.panel
        self.app.configure_pose("new.blend")
        self.assertIs(self.panel.session, previous)
        self.assertIn("저장", self.panel.error)

    def test_preview_update_never_replaces_source_field_with_work_path(self):
        self.panel.fields["source"].text = "selected_model.blend"
        self.panel.session.poll = Mock()
        self.panel.session.error = None
        self.panel.session.revision = 0
        self.panel.session.directory = Path("preview")
        self.panel.session.state["work"] = "generated_work.blend"
        self.panel.session.state["frame"] = 2
        resource = Mock()
        with patch("Tools.asset_loader.pose_panel.read_document"), patch("Tools.asset_loader.pose_panel.PicoAssetBackend") as backend:
            backend.return_value.load.return_value = resource
            self.panel.update(0)
        self.assertEqual(self.panel.value("source"), "selected_model.blend")

    def test_knee_drag_uses_joint_direction_command(self):
        self.panel.session.state["points"] = {"pole.foot.R": {
            "world": [0, 0, 1], "uv": [.5, .5, 1], "pole_world": [-1, 0, 1]}}
        x, y = 592, 440
        self.panel.content_event(SimpleNamespace(type=1, button=1, x=x, y=y))
        self.panel.content_event(SimpleNamespace(type=2, x=x+14, y=y))
        command, = self.panel.session.send.call_args.args
        self.assertEqual(command, "bend")
        self.assertEqual(self.panel.session.send.call_args.kwargs["control"], "pole.foot.R")
        self.assertAlmostEqual(self.panel.session.send.call_args.kwargs["world"][0], .1)

    def test_ctrl_z_reaches_pose_history_even_when_a_field_is_focused(self):
        self.app.pico.SDL_KEYDOWN, self.app.pico.SDLK_z, self.app.pico.KMOD_CTRL = 9, 122, 64
        self.panel.focus = "degrees"
        self.panel.handle_event(SimpleNamespace(type=9, key=122, mod=64))
        self.panel.session.send.assert_called_once_with("undo")

    def test_world_axis_buttons_switch_between_move_and_rotate(self):
        self.panel.axis_step("Z", -1)
        self.panel.session.send.assert_called_with("translate", control="hand.R", axis="Z", amount=-.05)
        self.panel.change_mode("rotate")
        self.panel.axis_step("Y", 1)
        self.panel.session.send.assert_called_with("rotate", control="hand.R", axis="Y", degrees=5)

    def test_independent_parts_replace_attachment_buttons(self):
        self.panel.select("object:Scabbard")
        labels = {label for label, _, _ in self.panel.buttons}
        self.assertNotIn("검 수납/파지", labels)
        self.assertNotIn("보조손 고정", labels)
        self.assertIn("이전 프레임 파츠 복제", labels)
        self.assertIn("칼 → 칼집 자동 정렬", labels)
        self.assertNotIn("손가락 굽히기", labels)

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

    def test_render_submission_keeps_independent_weapon_roots(self):
        from Tools.asset_loader.editors import RenderPanel
        from Tools.asset_loader.production import render_config
        render = RenderPanel(self.app)
        render.sample = True
        render.render_preset = render_config(asset_id="parts", animation_name="idle", frames="1", fps=12,
                                             width=240, height=240, ortho_scale=5, samples=1)
        render.render_preset["extra_root_objects"] = ["Gun", "Sword", "Scabbard"]
        self.app.start_render = Mock()
        render.submit()
        self.assertEqual(self.app.start_render.call_args.args[1]["extra_root_objects"], ["Gun", "Sword", "Scabbard"])

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

    def test_knee_drag_requests_are_coalesced(self):
        session = PoseSession.__new__(PoseSession)
        from collections import deque
        session.queue = deque()
        session.inflight = True
        session.process = SimpleNamespace(poll=lambda: None)
        for index in range(30):
            session.send("bend", control="pole.foot.R", world=[index, 0, 1])
        self.assertEqual(len(session.queue), 1)
        self.assertEqual(session.queue[0]["world"], [29, 0, 1])


if __name__ == "__main__":
    unittest.main()
