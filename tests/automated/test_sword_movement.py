"""검 이동의 거리·방향·부스트·전환과 독립 실행 수명을 확인한다."""

from math import hypot
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ferrial_drive.assets.directional import SCREEN_DIRECTIONS
from ferrial_drive.assets.sprites import SpriteClip, SpriteFrame
from ferrial_drive.combat.locomotion import LocomotionController, LocomotionPlayback, LocomotionSettings
from ferrial_drive.combat.movement_application import MovementApplication
from ferrial_drive.combat.training_ground import GroundProjection
from ferrial_drive.runtime import run_application
from Tools.unit_test_runner.entrypoints import inspect_entrypoint, read_test_header, read_test_source

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "samples/sword_movement/movement_config.json"


def sample_clips():
    frames = tuple(SpriteFrame((0, 0, 1, 1), (0, 0)) for _ in range(8))
    motions = [f"{state}_loop" for state in ("idle", "run", "dash", "boost")]
    motions += [f"{a}_to_{b}" for a in ("idle", "run", "dash", "boost")
                for b in ("idle", "run", "dash", "boost") if a != b]
    return {f"{motion}/{direction}": SpriteClip(12, frames) for motion in motions for direction in SCREEN_DIRECTIONS}


class LocomotionTests(unittest.TestCase):
    def test_requested_training_speeds(self):
        controller = LocomotionController(LocomotionSettings(boost_prepare_seconds=0))
        controller.update(0.2, (1, 0), (1, 0))
        self.assertAlmostEqual(controller.movement_speed_mps, 30)
        controller.update(0.1, (1, 0), (1, 0))
        self.assertAlmostEqual(controller.speed_mps, 30)
        controller.update(0.2, (1, 0), (1, 0), dash=True)
        self.assertAlmostEqual(controller.movement_speed_mps, 100)
        controller.update(0.1, (1, 0), (1, 0), dash=True)
        self.assertAlmostEqual(controller.speed_mps, 100)
        controller.request_boost((1, 0), (1, 0))
        controller.update(0.1, (0, 0), (1, 0))
        self.assertAlmostEqual(controller.speed_mps, 203.125)
    def test_diagonal_speed_matches_axis_and_fps(self):
        for fps in (30, 60, 144):
            for vector in ((1, 0), (1, 1), (-1, -1)):
                controller = LocomotionController()
                for _ in range(fps):
                    controller.update(1 / fps, vector, (0, -1))
                self.assertAlmostEqual(hypot(*(v - 500 for v in controller.position_m)), 27)
                self.assertAlmostEqual(controller.distance_m, 27)

    def test_running_faces_movement_and_dash_faces_aim(self):
        controller = LocomotionController()
        controller.update(0.1, (-1, 0), (0, -1))
        self.assertEqual((controller.state, controller.direction), ("run", "w"))
        controller.update(0.1, (-1, 0), (0, -1), dash=True)
        self.assertEqual((controller.state, controller.direction), ("dash", "n"))

    def test_releasing_keys_coasts_then_stops_in_0_2_seconds(self):
        controller = LocomotionController()
        controller.update(1, (1, 0), (1, 0))
        stopped = controller.position_m
        controller.update(0.1, (0, 0), (0, 1))
        self.assertAlmostEqual(controller.movement_speed_mps, 15)
        self.assertAlmostEqual(controller.position_m[0], stopped[0]+2.4375)
        self.assertEqual(controller.state, "run")
        controller.update(0.1, (0, 0), (0, 1))
        self.assertAlmostEqual(controller.position_m[0], stopped[0]+3)
        self.assertEqual(controller.movement_speed_mps, 0)
        stopped = controller.position_m
        controller.update(0.1, (0, 0), (0, 1))
        self.assertEqual(controller.position_m, stopped)
        self.assertEqual((controller.state, controller.speed_mps), ("idle", 0))

    def test_dash_from_idle_and_run_to_dash_to_run_use_smoothstep(self):
        controller = LocomotionController()
        controller.update(0.1, (1, 0), (1, 0), dash=True)
        self.assertAlmostEqual(controller.position_m[0], 501.875)
        self.assertAlmostEqual(controller.movement_speed_mps, 50)
        controller.update(0.1, (1, 0), (1, 0), dash=True)
        self.assertAlmostEqual(controller.position_m[0], 510)
        controller.update(0.1, (1, 0), (1, 0))
        self.assertAlmostEqual(controller.movement_speed_mps, 65)
        controller.update(0.1, (1, 0), (1, 0))
        self.assertAlmostEqual(controller.position_m[0], 523)
        self.assertAlmostEqual(controller.movement_speed_mps, 30)
        controller.update(0.1, (1, 0), (1, 0), dash=True)
        self.assertAlmostEqual(controller.movement_speed_mps, 65)

    def test_acceleration_and_release_distance_match_across_fps(self):
        for fps in (30, 60, 144):
            for dash, distance in ((False, 30), (True, 100)):
                controller = LocomotionController()
                for _ in range(fps):
                    controller.update(1/fps, (1, 1), (1, 0), dash=dash)
                for _ in range(fps):
                    controller.update(1/fps, (0, 0), (1, 0), dash=dash)
                self.assertAlmostEqual(controller.distance_m, distance)
                self.assertEqual(controller.movement_speed_mps, 0)

    def test_new_direction_interrupts_coasting_without_restarting_same_speed_ramp(self):
        controller = LocomotionController()
        controller.update(1, (1, 0), (1, 0))
        controller.update(0.1, (0, 0), (1, 0))
        start = controller.position_m
        controller.update(0.1, (0, -1), (1, 0))
        self.assertAlmostEqual(controller.position_m[0], start[0])
        self.assertLess(controller.position_m[1], start[1])
        self.assertAlmostEqual(controller.movement_speed_mps, 22.5)

    def test_run_dash_run_and_coast_chain_matches_at_different_frame_rates(self):
        for fps in (1, 30, 60, 144):
            controller = LocomotionController()
            for movement, dash in (((1, 0), False), ((1, 0), True), ((1, 0), False), ((0, 0), False)):
                for _ in range(fps):
                    controller.update(1/fps, movement, (1, 0), dash=dash)
            self.assertAlmostEqual(controller.position_m[0], 660)
            self.assertEqual(controller.movement_speed_mps, 0)
            self.assertEqual(controller.state, "idle")

    def test_boost_release_and_aim_change_keep_fixed_direction(self):
        for fps in (30, 60, 144):
            controller = LocomotionController()
            self.assertTrue(controller.request_boost((1, 0), (0, -1)))
            for _ in range(fps):
                controller.update(1 / fps, (0, 0), (-1, 0))
            self.assertAlmostEqual(controller.position_m[0], 525)
            self.assertAlmostEqual(controller.position_m[1], 500)
            self.assertEqual(controller.state, "idle")

    def test_boost_uses_aim_without_movement_and_rejects_reentry(self):
        controller = LocomotionController()
        controller.request_boost((0, 0), (0, -1))
        self.assertFalse(controller.request_boost((1, 0), (1, 0)))
        controller.update(0.28, (0, 0), (1, 0))
        self.assertAlmostEqual(controller.position_m[1], 475)
        self.assertTrue(controller.request_boost((1, 0), (1, 0)))

    def test_boost_end_consumes_remaining_frame_as_run(self):
        controller = LocomotionController(LocomotionSettings(boost_prepare_seconds=0))
        controller.request_boost((1, 0), (1, 0))
        controller.update(0.25, (0, 1), (1, 0))
        self.assertAlmostEqual(controller.position_m[0], 528)
        self.assertAlmostEqual(controller.position_m[1], 500 + 30 * 0.05)
        self.assertEqual((controller.state, controller.direction), ("run", "s"))

    def test_boost_windup_preserves_dash_then_launches_and_eases_to_target(self):
        controller = LocomotionController()
        controller.update(1, (1, 0), (1, 0), dash=True)
        start = controller.position_m[0]
        controller.request_boost((1, 0), (1, 0))
        controller.update(0.04, (1, 0), (1, 0), dash=True)
        self.assertTrue(controller.boost_preparing)
        self.assertAlmostEqual(controller.position_m[0] - start, 4)
        self.assertAlmostEqual(controller.movement_speed_mps, 100)
        controller.update(0.04, (1, 0), (1, 0), dash=True)
        self.assertFalse(controller.boost_preparing)
        self.assertAlmostEqual(controller.movement_speed_mps, 250)
        controller.update(0.2, (1, 0), (1, 0), dash=True)
        self.assertAlmostEqual(controller.position_m[0] - start, 8 + 35)
        self.assertAlmostEqual(controller.movement_speed_mps, 100)

    def test_boost_curve_distance_is_frame_rate_independent(self):
        for steps in (1, 6, 12, 29):
            for movement, dash, expected in (((1, 0), False, 28), ((1, 0), True, 35), ((0, 0), False, 25)):
                controller = LocomotionController(LocomotionSettings(boost_prepare_seconds=0))
                controller.request_boost((1, 0), (1, 0))
                for _ in range(steps):
                    controller.update(0.2 / steps, movement, (1, 0), dash=dash)
                self.assertAlmostEqual(controller.position_m[0] - 500, expected)

    def test_boost_target_change_has_no_instant_speed_jump(self):
        controller = LocomotionController(LocomotionSettings(boost_prepare_seconds=0))
        controller.request_boost((1, 0), (1, 0))
        controller.update(0.1, (1, 0), (1, 0), dash=True)
        speed = controller.movement_speed_mps
        controller.update(0, (1, 0), (1, 0), dash=False)
        self.assertAlmostEqual(controller.movement_speed_mps, speed)
        controller.update(0.1, (1, 0), (1, 0), dash=False)
        self.assertAlmostEqual(controller.movement_speed_mps, 30)

    def test_boundary_respects_radius_for_run_and_boost(self):
        controller = LocomotionController()
        controller.position_m = (997, 3)
        controller.request_boost((1, -1), (0, 1))
        controller.update(0.2, (0, 0), (0, 1))
        self.assertEqual(controller.position_m, (997.5, 2.5))
        controller.update(1, (1, -1), (0, 1))
        self.assertEqual(controller.speed_mps, 0)

    def test_invalid_parameters_and_updates(self):
        for values in ({"map_size_m": 4}, {"boost_duration_seconds": 0}, {"run_speed_mps": float("nan")},
                       {"movement_acceleration_seconds": 0}):
            with self.assertRaises(ValueError):
                LocomotionSettings(**values)
        controller = LocomotionController()
        for dt in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                controller.update(dt, (0, 0), (0, 0))

    def test_reset_clears_boost_and_distance(self):
        controller = LocomotionController()
        controller.request_boost((1, 0), (1, 0))
        controller.update(0.1, (1, 0), (1, 0))
        controller.reset()
        self.assertEqual((controller.position_m, controller.state, controller.distance_m,
                          controller.boost_remaining_seconds), ((500, 500), "idle", 0, 0))


class PlaybackTests(unittest.TestCase):
    def test_faster_run_preserves_transition_time(self):
        playback = LocomotionPlayback(sample_clips())
        playback.update("run", "e", 0.1, loop_speed=2)
        self.assertEqual(playback.motion, "idle_to_run")
        playback.update("run", "e", 0.1, loop_speed=2)
        self.assertEqual(playback.motion, "run_loop")
        self.assertAlmostEqual(playback.elapsed_seconds, 0.16)
    def test_transition_does_not_delay_movement_and_carries_leftover(self):
        controller = LocomotionController()
        playback = LocomotionPlayback(sample_clips())
        controller.update(0.05, (1, 0), (1, 0))
        playback.update(controller.state, controller.direction, 0.05)
        self.assertGreater(controller.position_m[0], 500)
        self.assertEqual(playback.motion, "idle_to_run")
        playback.update("run", "e", 0.1)
        self.assertEqual(playback.motion, "run_loop")
        self.assertAlmostEqual(playback.elapsed_seconds, 0.03)

    def test_rapid_reverse_and_release_interrupt_transition(self):
        playback = LocomotionPlayback(sample_clips())
        playback.update("run", "e", 0.02)
        playback.update("run", "w", 0.03)
        self.assertAlmostEqual(playback.elapsed_seconds, 0.05)
        self.assertEqual(playback.direction, "w")
        playback.update("idle", "n", 0.02)
        self.assertEqual(playback.motion, "run_to_idle")
        self.assertAlmostEqual(playback.elapsed_seconds, 0.02)

    def test_missing_direction_fails_instead_of_substituting(self):
        clips = sample_clips()
        del clips["run_loop/nw"]
        with self.assertRaises(ValueError):
            LocomotionPlayback(clips)


class MovementIntegrationTests(unittest.TestCase):
    def test_wasd_uses_fixed_axes_independent_of_mouse(self):
        program = MovementApplication(CONFIG, demo=True)
        for mouse in ((1600, 540), (300, 540), (960, 100), (960, 900)):
            program.mouse = mouse
            for key, expected in (("w", (0, -1)), ("a", (-1, 0)), ("s", (0, 1)), ("d", (1, 0))):
                program.keys = {key}
                self.assertEqual(program.movement(), expected)
        program.keys = {"w", "d"}
        dx, dy = program.movement()
        self.assertAlmostEqual(hypot(dx, dy), 1)
        self.assertAlmostEqual(dx, -dy)

    def test_vertical_and_horizontal_keep_equal_world_speed(self):
        program = MovementApplication(CONFIG, demo=True)
        distances = []
        screen_distances = []
        for key in ("d", "w"):
            program.controller.reset()
            program.keys = {key}
            start = program.controller.position_m
            program.controller.update(1, program.movement(), program.aim())
            end = program.controller.position_m
            distances.append(hypot(*(b - a for a, b in zip(start, end))))
            screen_start, screen_end = program.projection.project(start), program.projection.project(end)
            screen_distances.append(hypot(*(b - a for a, b in zip(screen_start, screen_end))))
        self.assertEqual(distances, [27, 27])
        self.assertAlmostEqual(screen_distances[1] / screen_distances[0], program.projection.y_scale)
    def test_projection_inverse_for_map_and_camera_coordinates(self):
        projection = GroundProjection(25.6, 0.3209)
        for point in ((0, 0), (500, 500), (1000, 1000)):
            result = projection.unproject(projection.project(point))
            for actual, expected in zip(result, point):
                self.assertAlmostEqual(actual, expected)

    def test_import_is_inert_and_runner_reads_standalone(self):
        script = "import sys; import ferrial_drive.combat.movement_application; assert not any(n.startswith('pico2d') for n in sys.modules)"
        subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, check=True)
        path = ROOT / "tests/sword_movement_test.py"
        self.assertEqual(inspect_entrypoint(path), "standalone")
        self.assertEqual(read_test_header(read_test_source(path))[0], "이동·UI 훈련장")

    def test_pause_freezes_boost_motion_and_camera(self):
        program = MovementApplication(CONFIG, demo=True)
        program.playback = LocomotionPlayback(sample_clips())
        program.controller.request_boost((1, 0), (1, 0))
        program.paused = True
        before = program.controller.position_m, program.controller.boost_remaining_seconds, program.camera.position
        program.update(1)
        self.assertEqual((program.controller.position_m, program.controller.boost_remaining_seconds, program.camera.position), before)
        self.assertEqual(program.playback.elapsed_seconds, 0)

    def test_shift_keys_are_independent_and_focus_clears_input(self):
        import pico2d.pico2d as pico
        program = MovementApplication(CONFIG, demo=True)
        program.pico = pico
        for key in (pico.SDLK_LSHIFT, pico.SDLK_RSHIFT, pico.SDLK_d):
            program.handle_event(SimpleNamespace(type=pico.SDL_KEYDOWN, key=key))
        program.handle_event(SimpleNamespace(type=pico.SDL_KEYUP, key=pico.SDLK_LSHIFT))
        self.assertEqual(program.keys, {"right_shift", "d"})
        program.handle_event(SimpleNamespace(type=pico.SDL_WINDOWEVENT, window_event=pico.SDL_WINDOWEVENT_FOCUS_LOST))
        self.assertEqual(program.keys, set())
        self.assertTrue(program.paused)

    def test_script_aim_is_not_overwritten_by_desktop_mouse(self):
        import pico2d.pico2d as pico
        program = MovementApplication(CONFIG, demo=True, script=ROOT / "samples/sword_movement/smoke_input.json")
        program.pico = pico
        previous = program.mouse
        program.handle_event(SimpleNamespace(type=pico.SDL_MOUSEMOTION, x=10, y=20))
        self.assertEqual(program.mouse, previous)
        program.handle_event(SimpleNamespace(type=pico.SDL_KEYDOWN, key=pico.SDLK_F10))
        self.assertFalse(program.running)

    def test_real_pico_dummy_lifecycle_and_public_demo(self):
        with patch.dict(os.environ, SDL_VIDEODRIVER="dummy"):
            program = MovementApplication(CONFIG, demo=True)
            run_application(program, width=1600, height=900, title="FDrive movement check", frame_limit=2)
            self.assertIsNone(program.ground.texture)
            self.assertEqual(program.renderer.fonts, {})

    def test_body_only_catalog_is_rejected_and_closes_fonts(self):
        program = MovementApplication(CONFIG)
        program.style["asset"] = "movement_config.json"
        catalog = SimpleNamespace(definitions={"body_only": object()})
        document = SimpleNamespace(mech=SimpleNamespace(sheets={"body": object()}))
        with patch.dict(os.environ, SDL_VIDEODRIVER="dummy"), \
                patch("ferrial_drive.combat.movement_application.AssetCatalog.load", return_value=catalog), \
                patch("ferrial_drive.combat.movement_application.read_document", return_value=document):
            with self.assertRaisesRegex(ValueError, "그림자 시트"):
                run_application(program, width=1600, height=900, title="FDrive missing shadow", frame_limit=1)
        self.assertEqual(program.renderer.fonts, {})


if __name__ == "__main__":
    unittest.main()
