"""v2가 프레임 번호 대신 연속 시간·화면 중심·불투명도를 보간기로 전달하는지 검사한다."""

from types import SimpleNamespace
from pathlib import Path
import ctypes as ct
import os
import hashlib
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from ferrial_drive.assets.combo import ComboPlayback
from ferrial_drive.assets.directional import DirectionalPlayback, SCREEN_DIRECTIONS
from ferrial_drive.assets.sprites import SpriteClip, SpriteFrame
from ferrial_drive.rendering.pico_motion_sprite import validate_source_assets
from ferrial_drive.ui_v2.preview import HudPreview


def playback_clips():
    frame = SpriteFrame((0, 0, 10, 10), (5, 5))
    counts = {"equipped_idle": 12, "combo_01": 6, "combo_02": 6, "combo_03": 6, "combo_04": 8}
    return {f"{motion}/{direction}": SpriteClip(12, (frame,) * count)
            for motion, count in counts.items() for direction in SCREEN_DIRECTIONS}


class UiV2InterpolationTests(unittest.TestCase):
    def setUp(self):
        self.program = HudPreview(initial_scene="combat")
        clips = playback_clips()
        self.program.player_idle = DirectionalPlayback(clips)
        self.program.player_combo = ComboPlayback(clips)
        self.program.player_interpolator = SimpleNamespace(draw=Mock(), close=Mock())

    def test_subframe_time_camera_center_scale_and_opacity_reach_renderer(self):
        p = self.program
        p.camera.position = (p.player_world[0] + 25, p.player_world[1] - 15)
        p.player_idle.update(0.03125)
        p.actor("player", 0.4)
        args, kwargs = p.player_interpolator.draw.call_args
        self.assertEqual(args[:2], ("equipped_idle/se", 0.03125))
        self.assertEqual(args[2:], p.camera.world_to_screen(p.player_world))
        self.assertEqual(kwargs, {"scale": p.config.data["v2"]["player_asset"]["scale"], "opacity": 0.4})

    def test_combo_holds_next_entry_and_pause_freezes_subframe_time(self):
        p = self.program
        p.player_combo.request("nw")
        p.update(0.31)
        p.actor("player", 1)
        self.assertEqual(p.player_interpolator.draw.call_args.args[:2], ("combo_01/nw", 0.3875))
        self.assertEqual(p.player_interpolator.draw.call_args.kwargs["easing"], "accelerate")
        self.assertEqual(p.player_interpolator.draw.call_args.kwargs["playback_speed"], 1.25)
        p.pause.request(True)
        p.update(0.4)
        self.assertEqual(p.player_combo.elapsed_seconds, 0.3875)
        p.pause.reset()
        p.update(0.09)
        self.assertTrue(p.player_combo.waiting_for_input)
        p.actor("player", 1)
        self.assertEqual(p.player_interpolator.draw.call_args.args[:2], ("combo_02/nw", 0))
        p.player_combo.request("e")
        p.update(0.021)
        p.actor("player", 1)
        self.assertEqual(p.player_interpolator.draw.call_args.args[0], "combo_02/nw")
        self.assertAlmostEqual(p.player_interpolator.draw.call_args.args[1], 0.02625)

    def test_reset_and_exit_release_interpolator(self):
        p = self.program
        resource = p.player_interpolator
        p.player_combo.request("s")
        p.player_idle.update(0.42)
        p.reset()
        self.assertFalse(p.player_combo.active)
        self.assertEqual(p.player_idle.elapsed_seconds, 0)
        p.exit()
        resource.close.assert_called_once()
        self.assertIsNone(p.player_interpolator)
        p.exit()


class SourceAssetBindingTests(unittest.TestCase):
    def test_changed_metadata_or_different_active_asset_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "mech.json"
            source.write_bytes(b'{"candidate":"current"}')
            data = {"source_assets": [{"path": "mech.json", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]}
            validate_source_assets(data, directory, (source,))
            with self.assertRaisesRegex(ValueError, "제작 대상"):
                validate_source_assets(data, directory, (source.with_name("other.json"),))
            source.write_bytes(b'{"candidate":"changed"}')
            with self.assertRaisesRegex(ValueError, "메타데이터"):
                validate_source_assets(data, directory, (source,))


@unittest.skipUnless(os.environ.get("FDRIVE_NATIVE_INTERPOLATION_TESTS") == "1",
                     "로컬 8방향 벡터·실제 OpenGL 검사는 선택 실행한다.")
class UiV2NativeInterpolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pico2d.pico2d as pico
        from ferrial_drive.rendering import PicoCanvas

        cls.pico = pico
        create_window = pico.SDL_CreateWindow
        cls.program = HudPreview(initial_scene="combat")
        cls.width = cls.program.config.window["width"]
        cls.height = cls.program.config.window["height"]
        cls.canvas = PicoCanvas(cls.width, cls.height, "UI v2 interpolation check")
        with patch.object(pico, "SDL_CreateWindow", side_effect=lambda title, x, y, w, h, flags:
                          create_window(title, x, y, w, h, (flags & ~pico.SDL_WINDOW_SHOWN) | pico.SDL_WINDOW_HIDDEN)):
            cls.canvas.open()
        try:
            cls.program.enter()
            if cls.program.player_interpolator is None:
                raise RuntimeError("로컬 8방향 보간 카탈로그가 필요하다.")
        except BaseException:
            cls.program.exit()
            cls.canvas.close()
            raise

    @classmethod
    def tearDownClass(cls):
        resource = cls.program.player_interpolator
        cls.program.exit()
        assert resource.closed and not resource.interpolator.clip_cache
        cls.canvas.close()

    def setUp(self):
        self.program.reset()

    def test_all_40_clips_reuse_prepared_textures(self):
        p, resource = self.pico, self.program.player_interpolator
        before = {key: tuple(ct.cast(t, ct.c_void_p).value for t in value[1])
                  for key, value in resource.interpolator.clip_cache.items()}
        self.assertEqual(len(before), 40)
        for name, clip in resource.clips.items():
            p.SDL_SetRenderDrawColor(p.renderer, 0, 0, 0, 0)
            p.SDL_RenderClear(p.renderer)
            resource.draw(name, clip.duration_ms / 1000 * 0.43, 640, 360, scale=128 / 202, opacity=0.5)
        after = {key: tuple(ct.cast(t, ct.c_void_p).value for t in value[1])
                 for key, value in resource.interpolator.clip_cache.items()}
        self.assertEqual(before, after)

    def test_same_source_frame_has_distinct_intermediate_pixels(self):
        program, p = self.program, self.pico
        program.player_combo.request("se")
        frames, pixels = [], []
        for elapsed in (0.20, 0.22):
            program.player_combo.elapsed_seconds = elapsed
            frames.append(program.player_combo.frame_index)
            p.SDL_SetRenderDrawColor(p.renderer, 0, 0, 0, 0)
            p.SDL_RenderClear(p.renderer)
            program.actor("player", 1)
            buffer = (ct.c_ubyte * (self.width * self.height * 4))()
            self.assertEqual(p.SDL_RenderReadPixels(p.renderer, None, p.SDL_PIXELFORMAT_RGBA32, buffer, self.width * 4), 0)
            pixels.append(bytes(buffer))
        self.assertEqual(frames, [2, 2])
        self.assertNotEqual(pixels[0], pixels[1])
        output = Path(__file__).resolve().parents[2] / "output/ui_unit_test_v2/interpolation_fix"
        output.mkdir(parents=True, exist_ok=True)
        program.update(0)
        program.draw()
        program.renderer.save_frame(output / "combo_subframe.png", self.width, self.height)

    def test_source_frame_bounds_match_parts_on_transparent_target(self):
        from ferrial_drive.assets.catalog import AssetDefinition, read_document
        from ferrial_drive.assets.pico_assets import PicoAssetResource

        p, program = self.pico, self.program
        resource = program.player_interpolator
        previous = p.SDL_GetRenderTarget(p.renderer)
        target = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_TARGET, 512, 512)
        self.assertTrue(target)
        original_settings = resource.easing, resource.shutter_seconds
        rows = []

        def bounds(draw):
            p.SDL_SetRenderDrawColor(p.renderer, 0, 0, 0, 0)
            p.SDL_RenderClear(p.renderer)
            draw()
            buffer = (ct.c_ubyte * (512 * 512 * 4))()
            self.assertEqual(p.SDL_RenderReadPixels(p.renderer, None, p.SDL_PIXELFORMAT_RGBA32, buffer, 512 * 4), 0)
            opaque = [i for i, alpha in enumerate(bytes(buffer)[3::4]) if alpha > 20]
            self.assertTrue(opaque)
            result = (min(i % 512 for i in opaque), opaque[0] // 512,
                      max(i % 512 for i in opaque) + 1, opaque[-1] // 512 + 1)
            self.assertNotEqual(result, (0, 0, 512, 512))
            return result

        try:
            self.assertEqual(p.SDL_SetRenderTarget(p.renderer, target), 0)
            resource.easing, resource.shutter_seconds = "linear", 0
            settings = program.config.data["v2"]["player_asset"]
            scale = settings["scale"]
            for setting in ("source", "combo_source"):
                source = (program.config.path.parent / settings[setting]).resolve()
                parts = PicoAssetResource(read_document(AssetDefinition("comparison", "mech", source)))
                try:
                    for name, clip in parts.clips.items():
                        elapsed = 0
                        for index, duration_ms in enumerate(clip.durations_ms):
                            a = bounds(lambda: parts.draw(name, index, 256, p.get_canvas_height() - 256, scale=scale))
                            b = bounds(lambda: resource.draw(name, elapsed, 256, 256, scale=scale))
                            rows.append({"clip": name, "frame": index, "parts_bbox": a, "motion_bbox": b,
                                         "max_delta_pixels": max(abs(x-y) for x, y in zip(a, b))})
                            elapsed += duration_ms / 1000
                finally:
                    parts.close()
        finally:
            resource.easing, resource.shutter_seconds = original_settings
            p.SDL_SetRenderTarget(p.renderer, previous)
            p.SDL_DestroyTexture(target)
        output = Path(__file__).resolve().parents[2] / "output/ui_unit_test_v2/interpolation_fix"
        output.mkdir(parents=True, exist_ok=True)
        (output / "all_source_bounds.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        self.assertEqual(len(rows), 304)
        worst = max(rows, key=lambda row: row["max_delta_pixels"])
        self.assertLessEqual(worst["max_delta_pixels"], 2, str(worst))


if __name__ == "__main__":
    unittest.main()
