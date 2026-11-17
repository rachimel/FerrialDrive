"""공격 중 이동·4타 복귀·캔슬과 그림자 위상·UI 상태 공급을 검사한다."""

from contextlib import nullcontext
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from ferrial_drive.assets.directional import SCREEN_DIRECTIONS
from ferrial_drive.assets.sprites import SpriteClip, SpriteFrame
from ferrial_drive.combat.locomotion import LocomotionController, LocomotionSettings
from ferrial_drive.combat.movement_combat import MovementCombat
from ferrial_drive.rendering.pico_shadow_blend import frame_blend_indices
from ferrial_drive.ui_v2.movement_hud import MovementHud
from ferrial_drive.ui_v2.view import UiV2View

ROOT = Path(__file__).resolve().parents[2]


def combat(*, acceleration="smoothstep"):
    frames = tuple(SpriteFrame((0, 0, 1, 1), (0, 0)) for _ in range(8))
    clips = {f"combo_{index:02}/{direction}": SpriteClip(12, frames[:count])
             for index, count in enumerate((6, 6, 6, 8), 1) for direction in SCREEN_DIRECTIONS}
    return MovementCombat(LocomotionController(), clips, acceleration=acceleration)


class MovementCombatTests(unittest.TestCase):
    def test_attack_steps_split_strikes_and_keep_dash_and_world_positions(self):
        bridge = combat()
        bridge.request_attack((1, 0))
        first_id = bridge.strike_id
        bridge.request_attack((1, 0))
        bridge.update(0.5, (0, 0), (1, 0), dash=True)
        self.assertEqual(len(bridge.attack_steps), 2)
        first, second = bridge.attack_steps
        self.assertEqual((first.strike_id, second.strike_id), (first_id, first_id + 1))
        self.assertEqual((first.clip_name, second.clip_name), ("combo_01/e", "combo_02/e"))
        self.assertTrue(first.dash and second.dash)
        self.assertEqual(first.end_position_m, second.start_position_m)
        self.assertAlmostEqual(first.real_seconds + second.real_seconds, 0.5)
        bridge.request_boost((1, 0), (1, 0))
        bridge.update(0.01, (0, 0), (1, 0))
        self.assertTrue(bridge.attack_steps)
        self.assertEqual(bridge.attack_steps[0].clip_name, "combo_02/e")
        self.assertTrue(bridge.attack_steps[0].boosting)

    def test_attack_step_keeps_boost_state_even_when_boost_ends_in_frame(self):
        bridge = combat()
        bridge.controller = LocomotionController(LocomotionSettings(boost_prepare_seconds=0, boost_duration_seconds=.1))
        bridge.request_attack((1, 0))
        bridge.request_boost((1, 0), (1, 0))
        bridge.update(.2, (0, 0), (1, 0))
        self.assertEqual(bridge.controller.boost_remaining_seconds, 0)
        self.assertTrue(bridge.attack_steps[0].boosting)
        bridge.update(.01, (0, 0), (1, 0))
        self.assertFalse(bridge.attack_steps[0].boosting)

    def test_reviewed_training_speeds_and_strike_distance_at_multiple_frame_rates(self):
        config = json.loads((ROOT / "samples/sword_movement/movement_config.json").read_text(encoding="utf-8"))
        for dash in (False, True):
            for index in range(4):
                for fps in (30, 60, 144):
                    with self.subTest(dash=dash, strike=index + 1, fps=fps):
                        bridge = combat()
                        bridge.controller = LocomotionController(LocomotionSettings(**config["movement"]))
                        bridge.speed = config["combat"]["playback_speed"]
                        bridge.acceleration = config["combat"]["acceleration"]
                        self.assertEqual(bridge.speed, 1.5)
                        self.assertEqual(bridge.acceleration, "constant")
                        bridge.request_attack((1, 0))
                        bridge.combo.attack_index = index
                        duration = bridge.combo.clips[bridge.combo.clip_name].duration_ms / 1000 / bridge.speed
                        speed = ((90, 90, 120, 90) if dash else (50, 50, 70, 50))[index]
                        for _ in range(fps):
                            bridge.update(1 / fps, (0, 0), (1, 0), dash=dash)
                        self.assertAlmostEqual(bridge.controller.distance_m, speed * duration)

    def test_held_attack_repeats_all_four_strikes(self):
        bridge = combat()
        sequence = []
        for _ in range(240):
            bridge.update(1 / 60, (0, 0), (1, 0), auto_swing=True)
            index = bridge.combo.attack_index
            if not sequence or sequence[-1] != index:
                sequence.append(index)
        self.assertEqual(sequence[:9], [0, 1, 2, 3, 0, 1, 2, 3, 0])

    def test_release_cancels_only_the_automatic_queue(self):
        bridge = combat()
        bridge.update(0.1, (0, 0), (1, 0), auto_swing=True)
        bridge.update(0.31, (0, 0), (1, 0), auto_swing=False)
        self.assertEqual(bridge.combo.attack_index, 0)
        self.assertTrue(bridge.combo.waiting_for_input)
        bridge = combat()
        bridge.update(0.1, (0, 0), (1, 0), auto_swing=True)
        bridge.request_attack((1, 0))
        bridge.update(0.31, (0, 0), (1, 0), auto_swing=False)
        self.assertEqual(bridge.combo.attack_index, 1)
        self.assertFalse(bridge.combo.waiting_for_input)

    def test_held_attack_keeps_running_and_chains_during_boost(self):
        bridge = combat()
        bridge.update(0.1, (0, 0), (1, 0), auto_swing=True)
        bridge.request_boost((1, 0), (1, 0))
        bridge.update(0.1, (1, 0), (1, 0), auto_swing=True)
        self.assertTrue(bridge.active)
        self.assertAlmostEqual(bridge.combo.elapsed_seconds, 0.25)
        self.assertTrue(bridge.combo.queued)
        self.assertEqual(bridge.controller.state, "boost")
        bridge.update(0.21, (1, 0), (1, 0), auto_swing=True)
        bridge.update(0.01, (0, 0), (1, 0), auto_swing=True)
        self.assertTrue(bridge.active)
        self.assertEqual(bridge.combo.attack_index, 1)

    def test_attack_auto_accelerates_toward_mouse_and_direction_locks(self):
        bridge = combat()
        bridge.update(0.1, (1, 0), (1, 0))
        position = bridge.controller.position_m
        bridge.request_attack((0, -1))
        bridge.update(0.1, (1, 0), (1, 0))
        self.assertAlmostEqual(bridge.controller.position_m[0], position[0])
        self.assertAlmostEqual(bridge.controller.position_m[1], position[1]-0.14765625)
        self.assertAlmostEqual(bridge.controller.speed_mps, 1.4765625)
        self.assertEqual(bridge.controller.direction, "n")
        bridge.request_attack((-1, 0))
        self.assertEqual(bridge.combo.direction, "n")

    def test_one_buffered_strike_and_movement_resumes_after_it(self):
        bridge = combat()
        bridge.request_attack((1, 0))
        bridge.request_attack((1, 0))
        bridge.request_attack((1, 0))
        bridge.update(0.4, (1, 0), (1, 0))
        self.assertEqual(bridge.combo.attack_index, 1)
        bridge.update(0.4, (1, 0), (1, 0))
        self.assertFalse(bridge.active)
        self.assertAlmostEqual(bridge.controller.position_m[0], 510.8)
        bridge.update(0.1, (1, 0), (1, 0))
        self.assertAlmostEqual(bridge.controller.position_m[0], 513.55625)

    def test_waiting_link_pose_releases_when_movement_arrives(self):
        bridge = combat()
        bridge.request_attack((1, 0))
        bridge.update(0.4, (0, 0), (1, 0))
        self.assertTrue(bridge.combo.waiting_for_input)
        bridge.update(0.1, (0, 0), (1, 0))
        self.assertTrue(bridge.active)
        bridge.update(0.1, (0, -1), (1, 0))
        self.assertFalse(bridge.active)
        self.assertAlmostEqual(bridge.controller.position_m[1], 499.4375)

    def test_fourth_strike_returns_leftover_time_to_running(self):
        bridge = combat()
        bridge.request_attack((1, 0))
        bridge.combo.attack_index = 3
        bridge.combo.elapsed_seconds = 0.65
        bridge.update(0.1, (1, 0), (1, 0))
        available = 0.1 - ((8 / 12 - 0.65) / bridge.speed)
        self.assertFalse(bridge.active)
        self.assertAlmostEqual(bridge.controller.position_m[0], 501.9528281712963)

    def test_shift_changes_attack_target_speed_on_the_same_acceleration_curve(self):
        bridge = combat()
        bridge.request_attack((0, -1))
        bridge.update(0.1, (1, 0), (1, 0), dash=True)
        self.assertAlmostEqual(bridge.controller.position_m[1], 499.5078125)
        self.assertAlmostEqual(bridge.controller.speed_mps, 4.921875)
        bridge.update(0.1, (1, 0), (1, 0), dash=False)
        self.assertAlmostEqual(bridge.controller.position_m[1], 498.64296875)
        self.assertEqual(bridge.controller.direction, "n")

    def test_wasd_does_not_steer_or_stop_auto_attack_and_link_wait_stops(self):
        bridge = combat()
        bridge.request_attack((1, 0))
        bridge.update(0.1, (0, -1), (1, 0))
        self.assertAlmostEqual(bridge.controller.position_m[0], 500.14765625)
        self.assertAlmostEqual(bridge.controller.position_m[1], 500)
        bridge.update(0.1, (0, 1), (1, 0))
        self.assertAlmostEqual(bridge.controller.position_m[0], 501.0125)
        bridge.update(0.1, (0, 0), (1, 0))
        self.assertAlmostEqual(bridge.controller.position_m[0], 502.84765625)
        bridge.update(0.2, (0, 0), (1, 0))
        self.assertAlmostEqual(bridge.controller.position_m[0], 505.4)
        self.assertEqual(bridge.controller.speed_mps, 0)

    def test_diagonal_attack_speed_is_normalized(self):
        from math import hypot
        for dash, speed in ((False, 27), (True, 90)):
            bridge = combat()
            bridge.request_attack((1, 1))
            bridge.update(0.1, (0, 0), (1, 0), dash=dash)
            self.assertAlmostEqual(hypot(*(axis-500 for axis in bridge.controller.position_m)), speed*0.00546875)

    def test_each_strike_reaches_its_target_speed_and_moves_half_constant_speed_distance(self):
        for index in range(4):
            for dash in (False, True):
                with self.subTest(strike=index+1, dash=dash):
                    bridge = combat()
                    bridge.request_attack((1, 0))
                    bridge.combo.attack_index = index
                    speed = ((90, 90, 120, 60) if dash else (27, 27, 36, 18))[index]
                    duration = (0.4, 0.4, 0.4, 8/15)[index]
                    bridge.update(duration-0.002, (0, 0), (0, -1), dash=dash)
                    bridge.update(0.001, (0, 0), (0, -1), dash=dash)
                    self.assertGreater(bridge.controller.speed_mps, speed*0.999)
                    self.assertLess(bridge.controller.speed_mps, speed)
                    self.assertEqual(bridge.controller.direction, "e")
                    bridge.update(0.001, (0, 0), (0, -1), dash=dash)
                    self.assertAlmostEqual(bridge.controller.position_m[0], 500+speed*duration/2)

    def test_second_to_third_boundary_splits_distance_and_samples_new_direction(self):
        for dash in (False, True):
            bridge = combat()
            bridge.request_attack((1, 0))
            bridge.combo.attack_index = 1
            bridge.combo.elapsed_seconds = 0.375
            bridge.request_attack((0, 1))
            bridge.update(0.2, (0, 0), (0, -1), dash=dash)
            factor = 2 if dash else 0.6
            self.assertEqual(bridge.combo.attack_index, 2)
            self.assertAlmostEqual(bridge.controller.position_m[0], 500+4.25390625*factor)
            self.assertAlmostEqual(bridge.controller.position_m[1], 500-0.328125*factor)
            self.assertEqual(bridge.controller.direction, "n")

    def test_whole_strike_distance_matches_at_30_60_144_fps(self):
        for curve, distances in (("smoothstep", (5.4, 5.4, 7.2, 4.8)),
                                 ("quint_in", (1.8, 1.8, 2.4, 1.6)), ("constant", (10.8, 10.8, 14.4, 9.6))):
            for fps in (30, 60, 144):
                for index, distance in enumerate(distances):
                    with self.subTest(curve=curve, fps=fps, strike=index+1):
                        bridge = combat(acceleration=curve)
                        bridge.request_attack((1, 0))
                        bridge.combo.attack_index = index
                        for _ in range(fps):
                            bridge.update(1/fps, (0, 0), (1, 0))
                        self.assertAlmostEqual(bridge.controller.position_m[0], 500+distance)
                        self.assertEqual(bridge.controller.speed_mps, 0)

    def test_next_strike_samples_mouse_at_start_not_at_buffer_click(self):
        bridge = combat()
        bridge.request_attack((1, 0))
        bridge.update(0.1, (1, 0), (0, -1))
        self.assertEqual(bridge.combo.direction, "e")
        bridge.request_attack((0, -1))
        bridge.update(0.1, (1, 0), (0, 1))
        self.assertEqual(bridge.combo.direction, "e")
        bridge.update(0.2, (1, 0), (-1, 0))
        self.assertEqual(bridge.combo.attack_index, 1)
        self.assertEqual(bridge.combo.direction, "w")
        self.assertEqual(bridge.controller.direction, "w")
        bridge.update(0.1, (0, -1), (0, -1))
        self.assertEqual(bridge.combo.direction, "w")
        self.assertEqual(bridge.controller.direction, "w")

    def test_click_after_wait_uses_new_mouse_direction(self):
        bridge = combat()
        bridge.request_attack((1, 0))
        bridge.update(0.4, (0, 0), (1, 0))
        self.assertTrue(bridge.combo.waiting_for_input)
        bridge.request_attack((0, -1))
        bridge.update(0.1, (1, 0), (0, 1))
        self.assertEqual(bridge.combo.direction, "n")
        self.assertEqual(bridge.controller.direction, "n")

    def test_boost_preserves_attack_phase_queue_and_direction(self):
        for elapsed in (0.01, 0.25, 0.49):
            bridge = combat()
            bridge.request_attack((1, 0))
            bridge.combo.elapsed_seconds = elapsed
            bridge.request_attack((1, 0))
            strike_id = bridge.strike_id
            self.assertTrue(bridge.request_boost((1, 0), (-1, 0)))
            self.assertTrue(bridge.active)
            self.assertEqual(bridge.combo.elapsed_seconds, elapsed)
            self.assertTrue(bridge.combo.queued)
            bridge.update(0.1, (0, 0), (-1, 0))
            expected = elapsed + 0.1 * bridge.speed
            if expected < 0.5:
                self.assertEqual(bridge.combo.attack_index, 0)
                self.assertAlmostEqual(bridge.combo.elapsed_seconds, expected)
                self.assertEqual(bridge.strike_id, strike_id)
                self.assertEqual(bridge.combo.direction, "e")
            else:
                self.assertEqual(bridge.combo.attack_index, 1)
                self.assertAlmostEqual(bridge.combo.elapsed_seconds, expected - 0.5)
                self.assertEqual(bridge.strike_id, strike_id + 1)
                self.assertEqual(bridge.combo.direction, "w")
            self.assertEqual(bridge.controller.state, "boost")
            self.assertAlmostEqual(bridge.controller.boost_remaining_seconds, 0.18)

    def test_boost_keeps_manual_link_wait_and_accepts_next_attack(self):
        bridge = combat()
        bridge.request_attack((1, 0))
        bridge.update(0.4, (0, 0), (1, 0))
        self.assertTrue(bridge.combo.waiting_for_input)
        bridge.request_boost((0, -1), (1, 0))
        bridge.update(0.1, (0, -1), (1, 0))
        self.assertTrue(bridge.combo.waiting_for_input)
        self.assertEqual(bridge.combo.attack_index, 0)
        bridge.request_attack((1, 0))
        bridge.update(0.05, (0, -1), (1, 0))
        self.assertEqual(bridge.combo.attack_index, 1)
        self.assertAlmostEqual(bridge.combo.elapsed_seconds, 0.0625)
        self.assertEqual(bridge.controller.state, "boost")

    def test_boost_translation_has_priority_while_attack_time_advances(self):
        bridge = combat()
        bridge.request_attack((1, 0))
        bridge.request_boost((0, 1), (1, 0))
        bridge.update(0.08, (0, 0), (1, 0))
        x, y = bridge.controller.position_m
        elapsed = bridge.combo.elapsed_seconds
        bridge.update(0.1, (0, 0), (1, 0))
        self.assertAlmostEqual(bridge.controller.position_m[0], x)
        self.assertGreater(bridge.controller.position_m[1] - y, 10)
        self.assertAlmostEqual(bridge.combo.elapsed_seconds, elapsed + 0.125)
        self.assertTrue(bridge.attack_steps)

    def test_held_fourth_strike_restarts_combo_even_during_boost(self):
        bridge = combat()
        bridge.request_attack((1, 0))
        bridge.combo.attack_index = 3
        bridge.combo.elapsed_seconds = 0.65
        bridge.request_boost((1, 0), (1, 0))
        bridge.update(0.1, (0, 0), (1, 0), auto_swing=True)
        self.assertTrue(bridge.active)
        self.assertEqual(bridge.combo.attack_index, 0)
        self.assertGreater(bridge.combo.elapsed_seconds, 0)
        self.assertTrue(bridge.boosting)

    def test_rejected_boost_does_not_clear_attack_or_queue(self):
        bridge = combat()
        bridge.request_attack((1, 0))
        bridge.request_attack((1, 0))
        self.assertTrue(bridge.request_boost((1, 0), (1, 0)))
        self.assertFalse(bridge.request_boost((0, 1), (0, 1)))
        self.assertTrue(bridge.active)
        self.assertTrue(bridge.combo.queued)

    def test_constant_training_attack_reaches_speed_on_first_frame(self):
        config = json.loads((ROOT / "samples/sword_movement/movement_config.json").read_text(encoding="utf-8"))
        for dash, speeds in ((False, (50, 50, 70, 50)), (True, (90, 90, 120, 90))):
            for index, speed in enumerate(speeds):
                with self.subTest(dash=dash, strike=index + 1):
                    bridge = combat(acceleration="constant")
                    bridge.controller = LocomotionController(LocomotionSettings(**config["movement"]))
                    bridge.request_attack((1, 0))
                    bridge.combo.attack_index = index
                    bridge.update(1 / 60, (0, 0), (1, 0), dash=dash)
                    self.assertAlmostEqual(bridge.controller.speed_mps, speed)
                    self.assertAlmostEqual(bridge.controller.distance_m, speed / 60)

    def test_boost_attack_progress_and_position_match_across_frame_rates(self):
        results = []
        for fps in (30, 60, 144):
            bridge = combat(acceleration="constant")
            bridge.update(0.1, (0, 0), (1, 0), auto_swing=True)
            bridge.request_boost((0, 1), (1, 0))
            remaining = 0.4
            while remaining > 1e-10:
                seconds = min(remaining, 1 / fps)
                bridge.update(seconds, (0, 0), (1, 0), auto_swing=True)
                remaining -= seconds
            results.append((*bridge.controller.position_m, bridge.combo.elapsed_seconds))
            self.assertEqual(bridge.combo.attack_index, 1)
        for actual in results[1:]:
            for value, expected in zip(actual, results[0]):
                self.assertAlmostEqual(value, expected)


class MovementPresentationTests(unittest.TestCase):
    def test_mouse_release_and_focus_loss_stop_automatic_swing(self):
        import pico2d.pico2d as pico
        from ferrial_drive.combat.movement_application import MovementApplication
        app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json", demo=True)
        app.pico, app.combat, app.playback = pico, combat(), Mock()
        press = SimpleNamespace(type=pico.SDL_MOUSEBUTTONDOWN, button=pico.SDL_BUTTON_LEFT)
        app.handle_event(press)
        self.assertTrue(app.attack_held)
        app.combat.update(0.1, (0, 0), (1, 0), auto_swing=app.attack_held)
        app.handle_event(SimpleNamespace(type=pico.SDL_MOUSEBUTTONUP, button=pico.SDL_BUTTON_LEFT))
        self.assertFalse(app.attack_held)
        self.assertFalse(app.combat.combo.queued)
        app.combat.combo.reset()
        app.handle_event(press)
        app.combat.update(0.1, (0, 0), (1, 0), auto_swing=app.attack_held)
        app.handle_event(SimpleNamespace(type=pico.SDL_WINDOWEVENT, window_event=pico.SDL_WINDOWEVENT_FOCUS_LOST))
        self.assertFalse(app.attack_held)
        self.assertFalse(app.combat.combo.queued)
        self.assertTrue(app.paused)

    def test_transition_shadow_resolves_endpoint_from_another_bundle(self):
        from ferrial_drive.combat.movement_application import MovementApplication
        app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json")
        clip = SpriteClip(12, (SpriteFrame((0, 0, 1, 1), (0, 0)),))
        current = SimpleNamespace(clips={"run_to_dash/e": clip},
                                  mech=SimpleNamespace(layer_rows={"shadow": 0}))
        following = SimpleNamespace(clips={"dash_loop/e": clip})
        app.sprites = [current, following]
        app.clip_resources = {"run_to_dash/e": current, "dash_loop/e": following}
        app.playback = SimpleNamespace(clip_name="run_to_dash/e", elapsed_seconds=0.1,
                                       transition_seconds=0.12, motion="run_to_dash",
                                       state="dash", direction="e", frame_index=0)
        app.renderer = app.ground = Mock()
        app.motion_sprite, app.shadow_blend = Mock(), Mock()
        app.draw_world()
        self.assertIs(app.shadow_blend.draw.call_args.kwargs["endpoint_resource"], following)
        self.assertNotIn("dash_loop/e", current.clips)

    def test_attack_body_shadow_and_non_interpolated_frame_share_accelerated_time(self):
        from ferrial_drive.combat.movement_application import MovementApplication
        app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json")
        app.config["combat"]["easing"] = "accelerate"
        app.combat = combat()
        app.combat.request_attack((1, 0))
        app.combat.combo.elapsed_seconds = 0.25
        resource = SimpleNamespace(clips=app.combat.combo.clips,
                                   mech=SimpleNamespace(layer_rows={"shadow": 0}),
                                   opacity=lambda value: nullcontext(), draw=Mock())
        app.sprites = [resource]
        app.attack_resources = {app.combat.combo.clip_name: resource}
        app.renderer = app.ground = Mock()
        app.attack_sprite = Mock()
        app.shadow_blend = Mock()
        app.draw_world()
        self.assertAlmostEqual(app.shadow_blend.draw.call_args.args[2], 1.125)
        self.assertEqual(app.attack_sprite.draw.call_args.args[1], 0.25)
        self.assertEqual(app.attack_sprite.draw.call_args.kwargs["easing"], "accelerate")
        app.interpolation_enabled = False
        app.draw_world()
        self.assertEqual(len(resource.draw.call_args_list), 1)
        self.assertEqual(resource.draw.call_args.args[1], 1)
        self.assertEqual(resource.draw.call_args.kwargs["part_visibility"], {"shadow": False})
        self.assertEqual(app.shadow_blend.draw.call_count, 2)
        self.assertEqual(app.shadow_blend.draw.call_args.args[2], 1)

    def test_shadow_loop_wrap_preserves_subframe_fraction(self):
        self.assertEqual(frame_blend_indices(16.5, 8, loop=True), (0, 1, 0.5))
        self.assertEqual(frame_blend_indices(7.25, 8, loop=True), (7, 0, 0.25))

    def test_shadow_one_shot_holds_last_frame(self):
        self.assertEqual(frame_blend_indices(8, 8, loop=False), (7, 7, 1))
        self.assertEqual(frame_blend_indices(6.5, 8, loop=False), (6, 7, 0.5))

    def test_ui_v2_receives_world_position_and_boost_readiness(self):
        hud = MovementHud(ROOT / "samples/ui_unit_test_v2/ui_config.json", ROOT / "samples/ui_unit_test_v2/hud_sample.json")
        controller = LocomotionController()
        controller.position_m = (250, 750)
        controller.request_boost((1, 0), (1, 0))
        hud.update(controller, 1 / 60, paused=False, interpolation=True)
        self.assertEqual(hud.map_position, (0.25, 0.75))
        self.assertFalse(hud.state.dash_ready)
        self.assertEqual(hud.state.hud.active_weapon_kind, "melee")
        self.assertIsNone(hud.state.hud.target)
        self.assertEqual(hud.config.data["v2"]["map_walls"], [])

    def test_v2_minimap_draws_player_at_supplied_map_position(self):
        hud = MovementHud(ROOT / "samples/ui_unit_test_v2/ui_config.json", ROOT / "samples/ui_unit_test_v2/hud_sample.json")
        renderer = Mock()
        renderer.clip.return_value = nullcontext()
        view = UiV2View(hud.config, renderer)
        view.framed_panel = Mock()
        view.minimap(hud.state.hud, 1, player_position=(0.25, 0.75))
        self.assertEqual(renderer.filled_triangle.call_args.args[:3], ((80, 134), (76, 144), (84, 144)))


if __name__ == "__main__":
    unittest.main()
