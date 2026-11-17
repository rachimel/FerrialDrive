"""이동·UI 공유 좌표·명중·입력·정지·초기화 연결을 검사한다."""

from pathlib import Path
from types import SimpleNamespace
import json
from tempfile import TemporaryDirectory
from unittest.mock import Mock
import unittest

from ferrial_drive.combat.geometry import Vec2
from ferrial_drive.combat.movement_application import MovementApplication
from ferrial_drive.combat.sword_effects import SwordTarget
from ferrial_drive.combat.training_ground import GroundProjection
from ferrial_drive.animation import ScalarAnimation
from ferrial_drive.ui.energy import EnergyCharge
from ferrial_drive.ui_v2.movement_hud import MovementHud


ROOT = Path(__file__).resolve().parents[2]


class MovementHudIntegrationTests(unittest.TestCase):
    def test_overdrive_does_not_shorten_accumulation_window_but_keeps_existing_popup_speed(self):
        from ferrial_drive.ui_v2.preview import HudPreview
        hud = self.hud
        hud.scene = 'combat'
        hud.transition.update(1)
        hud.apply_target('A')
        hud.perform('overdrive')
        hud.damage_target('A', 25)
        HudPreview.update(hud, .05)
        self.assertFalse(hud.damage_numbers.visuals)
        self.assertAlmostEqual(hud.damage_numbers.elapsed_seconds, .05)
        hud.damage_target('A', 13)
        HudPreview.update(hud, .05)
        self.assertEqual([v.amount for v in hud.damage_numbers.visuals], [38])
        self.assertAlmostEqual(hud.damage_numbers.popups[0].animation.elapsed_seconds, 0)
        HudPreview.update(hud, .01)
        self.assertAlmostEqual(hud.damage_numbers.popups[0].animation.elapsed_seconds, .02)

    def test_instant_damage_updates_gameplay_now_but_shows_one_sum_after_window_and_freezes_on_pause(self):
        from ferrial_drive.ui_v2.preview import HudPreview
        hud = self.hud
        hud.scene = 'combat'
        hud.transition.update(1)
        hud.apply_target('A')
        before = hud.enemies['A']['health'].current
        hud.damage_target('A', 25)
        hud.damage_target('A', 13)
        self.assertEqual(hud.enemies['A']['health'].current, before - 38)
        self.assertEqual(hud.state.hud.total_damage_dealt, 38)
        self.assertEqual(hud.state.hud.combo_count, 2)
        self.assertTrue(hud.particle_system.commands)
        self.assertFalse(hud.damage_numbers.visuals)
        hud.pause.request(True)
        HudPreview.update(hud, .5)
        self.assertEqual(hud.damage_numbers.elapsed_seconds, 0)
        self.assertFalse(hud.damage_numbers.visuals)
        hud.pause.reset()
        HudPreview.update(hud, .1)
        self.assertEqual([(v.owner, v.amount) for v in hud.damage_numbers.visuals], [('A', 38)])
        hud.damage_target('A', 5)
        self.assertTrue(hud.damage_numbers.pending)
        hud.reset_training()
        self.assertFalse(hud.damage_numbers.pending)
        self.assertFalse(hud.damage_numbers.visuals)

    def place_range_target(self, offset_m, height_pixels=80):
        position_m = tuple(a + b for a, b in zip(self.app.controller.position_m, offset_m))
        ground = Vec2(*self.app.projection.project(position_m))
        self.app.sword_targets = [SwordTarget("A", ground + Vec2(0, -height_pixels), 26, position_m=position_m)]
        self.app.bind_hud_world()
        self.hud.mouse = self.app.camera.world_to_screen((ground.x, ground.y - height_pixels))

    def test_acquisition_uses_visible_body_and_zoom_instead_of_distance_or_aiming(self):
        px, py = self.hud.player_world
        half_width, _ = self.app.camera.screen_center
        for zoom in (.5, 1, 2):
            self.app.camera.zoom_animation = ScalarAnimation(zoom, zoom, 0)
            for aiming in (False, True):
                self.hud.aiming = aiming
                for beyond, expected in ((25, "A"), (27, None)):
                    self.hud.apply_target(None)
                    self.hud.auto_target.reset()
                    center = Vec2(px + half_width / zoom + beyond, py)
                    self.app.sword_targets = [SwordTarget("A", center, 26, position_m=(1e6, 1e6))]
                    self.app.bind_hud_world()
                    self.hud.update_world_view(0)
                    self.assertEqual(self.hud.selected_target_id, expected)

    def test_visible_acquisition_and_unlimited_retention_survive_aim_release_and_reset(self):
        self.place_range_target((10, 0))
        self.hud.update_world_view(0)
        self.assertEqual(self.hud.selected_target_id, "A")
        self.hud.aiming = True
        self.hud.update_world_view(0)
        self.assertEqual(self.hud.selected_target_id, "A")
        self.hud.aiming = False
        self.place_range_target((0, 300))
        self.hud.update_world_view(0)
        self.assertEqual(self.hud.selected_target_id, "A")
        self.place_range_target((0, 300.001))
        self.hud.update_world_view(0)
        self.assertEqual(self.hud.selected_target_id, "A")
        self.place_range_target((0, 1000))
        self.hud.update_world_view(0)
        self.assertEqual(self.hud.selected_target_id, "A")
        self.hud.reset_training()
        self.assertTrue(self.hud.auto_target.retain_outside_range)
        self.assertFalse(self.hud.visibility_released_ids)

    def test_release_only_when_body_fully_outside_and_ignore_camera_shake(self):
        self.hud.update_world_view(0)
        self.assertEqual(self.hud.selected_target_id, "A")
        half_width, half_height = self.app.camera.screen_center
        self.app.camera.position = (0, 0)
        self.app.camera.zoom_animation = ScalarAnimation(1, 1, 0)
        self.app.camera.feedback_offset_pixels = (-10000, -10000)
        # 화면 네 가장자리에서 중심이 밖이어도 기체가 1px 보이면 유지한다.
        for left, top in ((-half_width - 19, 0), (half_width - 1, 0),
                          (0, -half_height - 19), (0, half_height - 1)):
            self.hud.player_world_bounds = (left, top, 20, 20)
            self.hud.update_world_view(0)
            self.assertEqual(self.hud.selected_target_id, "A")
        self.hud.player_world_bounds = (half_width, 0, 20, 20)
        self.hud.update_world_view(0)
        self.assertIsNone(self.hud.selected_target_id)
        self.assertIsNone(self.hud.auto_target.pending_id)

    def test_offscreen_released_target_does_not_repeat_acquisition_before_it_fits(self):
        self.place_range_target((10, 0))
        self.hud.update_world_view(0)
        self.assertEqual(self.hud.selected_target_id, "A")
        self.place_range_target((200, 0))
        px, py = self.hud.player_world
        self.app.camera.position = (px + 4000, py)
        self.hud.update_world_view(0)
        self.assertIsNone(self.hud.selected_target_id)
        self.app.camera.position = (px, py)
        for _ in range(3):
            self.hud.update_world_view(1)
            self.assertIsNone(self.hud.selected_target_id)
        self.place_range_target((10, 0))
        self.hud.update_world_view(0)
        self.assertEqual(self.hud.selected_target_id, "A")

    def test_camera_does_not_reacquire_on_changing_pose_at_release_edge(self):
        from math import sin
        root = self.hud.player_world
        self.app.sword_targets = [SwordTarget("A", Vec2(root[0] + 2000, root[1]), 26),
                                  SwordTarget("B", Vec2(root[0] + 2010, root[1]), 26)]
        self.app.bind_hud_world()
        self.hud.auto_target.reset("A")
        self.hud.apply_target("A")
        previous, transitions, released = None, [], False
        for frame in range(900):
            self.app.bind_hud_world()
            self.hud.player_world_bounds = (root[0] - 38, root[1] - 100, 80 + 12 * sin(frame / 20), 110)
            self.hud.update_world_view(1 / 60)
            selected = self.hud.selected_target_id
            if selected != previous:
                transitions.append(selected)
                previous = selected
            before = self.app.camera.position[0]
            self.app.camera.update(root, None, 1 / 60,
                                   focus_world=(root[0] + 2000, root[1]) if selected else None)
            if selected is None:
                released = True
            if released:
                self.assertLessEqual(self.app.camera.position[0], before)
        self.assertEqual(transitions, ["A", None])

    def test_player_visibility_follows_zoom_at_the_screen_edge(self):
        px, py = self.hud.player_world
        self.app.camera.position = (px, py)
        half_width, _ = self.app.camera.screen_center
        for zoom in (.5, 1, 2):
            self.app.camera.zoom_animation = ScalarAnimation(zoom, zoom, 0)
            self.hud.player_world_bounds = (px + (half_width - 1) / zoom, py, 20, 20)
            self.assertTrue(self.hud.player_intersects_view())
            self.hud.player_world_bounds = (px + (half_width + 1) / zoom, py, 20, 20)
            self.assertFalse(self.hud.player_intersects_view())

    def prepare_screen_switch(self, second_ratio=.3):
        self.hud.distance_switch["enabled"] = True
        px, py = self.hud.player_world
        half_width, _ = self.app.camera.screen_center
        self.app.sword_targets = [SwordTarget("A", Vec2(px + .85 * half_width, py), 26),
                                  SwordTarget("B", Vec2(px + second_ratio * half_width, py), 26)]
        self.app.bind_hud_world()
        self.hud.auto_target.reset("A")
        self.hud.apply_target("A")
        self.app.mouse = self.hud.mouse = self.app.camera.world_to_screen((px + .85 * half_width, py))

    def test_far_target_switches_to_closer_after_delay_without_cursor_switching_back(self):
        self.prepare_screen_switch()
        self.hud.update_world_view(0)
        self.hud.update_world_view(.249)
        self.assertEqual(self.hud.selected_target_id, "A")
        self.hud.update_world_view(.001)
        self.assertEqual(self.hud.selected_target_id, "B")
        for _ in range(180):
            self.hud.update_world_view(1 / 60)
            self.assertEqual(self.hud.selected_target_id, "B")

    def test_screen_switch_keeps_current_without_sufficiently_closer_candidate(self):
        self.prepare_screen_switch(.7)
        self.hud.update_world_view(0)
        self.hud.update_world_view(2)
        self.assertEqual(self.hud.selected_target_id, "A")
        self.hud.enemies.pop("B")
        self.hud.update_world_view(2)
        self.assertEqual(self.hud.selected_target_id, "A")

    def test_q_selects_mouse_nearest_immediately_and_protects_it_from_auto_switch(self):
        import pico2d.pico2d as pico
        self.prepare_screen_switch()
        self.hud.auto_target.reset("B")
        self.hud.apply_target("B")
        self.app.pico, self.app.running = pico, True
        key = SimpleNamespace(type=pico.SDL_KEYDOWN, key=pico.SDLK_q, repeat=False)
        self.app.handle_event(key)
        self.assertTrue(self.app.running)
        self.assertEqual(self.hud.selected_target_id, "A")
        self.hud.update_world_view(.99)
        self.assertEqual(self.hud.selected_target_id, "A")
        self.hud.update_world_view(.01)
        self.hud.update_world_view(.25)
        self.assertEqual(self.hud.selected_target_id, "B")
        key.repeat = True
        self.app.handle_event(key)
        self.assertEqual(self.hud.selected_target_id, "B")
        key.repeat = False
        self.app.paused = True
        self.app.handle_event(key)
        self.assertEqual(self.hud.selected_target_id, "B")
        key.key = pico.SDLK_F10
        self.app.handle_event(key)
        self.assertFalse(self.app.running)

    def test_overdrive_does_not_accelerate_target_switch_timer(self):
        self.hud.set_energy_charge(EnergyCharge(3.5))
        self.hud.perform("overdrive")
        self.hud.update_world_view = Mock()
        self.hud.update(self.app.controller, .1, paused=False, interpolation=False)
        self.hud.update_world_view.assert_called_once_with(.1)

    def setUp(self):
        self.app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json", demo=True)
        self.hud = MovementHud(ROOT / "samples/ui_unit_test_v2/ui_config.json",
                               ROOT / "samples/ui_unit_test_v2/hud_sample.json")
        self.app.hud = self.hud
        position = self.app.projection.project((505, 500))
        self.target = SwordTarget("A", Vec2(position[0], position[1] - 80), 26)
        self.app.sword_targets = [self.target]
        self.app.mouse = self.app.camera.world_to_screen((self.target.center.x, self.target.center.y))
        self.app.bind_hud_world()

    def test_hud_preserves_camera_position_and_velocity_and_uses_target_projection(self):
        self.app.camera.velocity_pixels_per_second = (90, 30)
        before = self.app.camera.position
        self.hud.update_world_view(0)
        self.hud.update_world_view(1.1)
        self.assertEqual(self.app.camera.position, before)
        self.assertEqual(self.app.camera.velocity_pixels_per_second, (90, 30))
        self.assertEqual(self.hud.selected_target_id, "A")
        body = self.hud.state.target_body
        expected = self.app.camera.world_to_screen((self.target.center.x, self.target.center.y))
        self.assertEqual((body.x + body.width / 2, body.y + body.height / 2), expected)

    def test_actual_target_hit_drives_health_counters_damage_popup_and_absorption(self):
        self.hud.apply_target("A")
        before = self.hud.enemies["A"]["health"].current
        self.hud.damage_target("A")
        hud = self.hud.state.hud
        self.assertLess(hud.target.health.current, before)
        self.assertEqual(hud.combo_count, 1)
        self.assertEqual(hud.total_damage_dealt, before - hud.target.health.current)
        self.assertFalse(self.hud.damage_numbers.popups)
        self.hud.damage_numbers.update(.1)
        self.assertEqual(len(self.hud.damage_numbers.popups), 1)
        self.assertTrue(self.hud.particle_system.commands)
        total = hud.total_damage_dealt
        self.hud.perform("damage_player")
        self.assertEqual(self.hud.state.hud.total_damage_dealt, total)

    def test_unselected_hit_keeps_lock_and_pending_switch_and_damage_owner(self):
        self.hud.enemies["B"] = {**self.hud.enemies["A"], "position": (300, 200), "name": "B"}
        self.hud.apply_target("A")
        self.hud.auto_target.pending_id = "B"
        self.hud.auto_target.pending_seconds = 0.4
        selected_health = self.hud.state.hud.target.health
        before = self.hud.enemies["B"]["health"].current
        self.hud.damage_target("B", 9)
        self.assertEqual(self.hud.enemies["B"]["health"].current, before - 9)
        self.assertEqual(self.hud.selected_target_id, "A")
        self.assertEqual(self.hud.state.hud.target.health, selected_health)
        self.assertEqual(self.hud.auto_target.pending_id, "B")
        self.assertEqual(self.hud.auto_target.pending_seconds, 0.4)
        self.hud.damage_numbers.update(.1)
        self.assertEqual(self.hud.damage_numbers.popups[0].owner, "B")

    def test_hit_without_lock_does_not_acquire_target(self):
        self.hud.damage_target("A", 9)
        self.assertIsNone(self.hud.selected_target_id)
        self.assertIsNone(self.hud.state.hud.target)
        self.assertEqual(self.hud.state.hud.total_damage_dealt, 9)

    def test_recovery_and_overdrive_are_not_overwritten_by_movement_updates(self):
        self.hud.set_energy_charge(EnergyCharge(3.5))
        self.app.update_hud(0.05)
        self.assertEqual(EnergyCharge.from_state(self.hud.state).total, 3.5)
        self.hud.perform("overdrive")
        self.app.update_hud(0.05)
        self.assertTrue(self.hud.state.overdrive)
        self.assertEqual(self.app.energy_level, 3)

    def test_sword_hits_apply_energy_damage_to_health_popup_and_total(self):
        self.app.playback = Mock()
        self.app.current_energy_color = Mock(return_value="#9DDFEA")
        self.app.sword_effects = SimpleNamespace(hits=[(1, "A")], update=Mock())
        for level, damage in ((1, 60), (2, 80), (3, 100)):
            with self.subTest(level=level):
                self.hud.reset_training()
                self.app.bind_hud_world()
                self.app.set_energy_level(level)
                self.app.target_hits = {"A": 0}
                before = self.hud.enemies["A"]["health"].current
                self.app.update(1 / 60)
                self.assertEqual(before - self.hud.enemies["A"]["health"].current, damage)
                self.assertEqual(self.hud.state.hud.total_damage_dealt, damage)
                self.assertEqual(self.hud.state.hud.combo_count, 1)
                self.hud.damage_numbers.update(.1)
                self.assertEqual(self.hud.damage_numbers.popups[0].amount, damage)
                self.assertEqual(self.app.target_hits["A"], 1)

    def test_explicit_damage_clamps_to_remaining_health_without_changing_debug_damage(self):
        debug_damage = self.hud.config.data["sample_actions"]["damage_target"]
        before = self.hud.enemies["A"]["health"].current
        self.hud.damage_target("A", before + 40)
        self.assertEqual(self.hud.enemies["A"]["health"].current, 0)
        self.assertEqual(self.hud.state.hud.total_damage_dealt, before)
        self.hud.damage_numbers.update(.1)
        self.assertEqual(self.hud.damage_numbers.popups[0].amount, before)
        self.assertEqual(self.hud.config.data["sample_actions"]["damage_target"], debug_damage)
        self.hud.damage_target("A", 120)
        self.assertEqual(self.hud.state.hud.combo_count, 1)

    def test_pause_freezes_damage_and_energy_effect_times(self):
        self.hud.damage_target("A")
        self.hud.perform("overdrive")
        before = self.hud.damage_numbers.visuals
        particle_time = list(self.hud.particle_system.commands)
        self.hud.update(self.app.controller, 0.4, paused=True, interpolation=True)
        self.assertEqual(self.hud.damage_numbers.visuals, before)
        self.assertEqual(self.hud.particle_system.commands, particle_time)
        self.assertTrue(self.hud.blocking)

    def test_reset_restores_targets_and_clears_effects_without_detaching_world_camera(self):
        self.hud.damage_target("A")
        self.hud.perform("overdrive")
        self.hud.reset_training()
        self.app.bind_hud_world()
        self.hud.update_world_view(0)
        self.hud.update_world_view(1.1)
        self.assertIs(self.hud.camera, self.app.camera)
        self.assertEqual(self.hud.state.hud.combo_count, 0)
        self.assertEqual(self.hud.state.hud.total_damage_dealt, 0)
        self.assertFalse(self.hud.state.overdrive)
        self.assertFalse(self.hud.damage_numbers.popups)
        health = self.hud.enemies["A"]["health"]
        self.assertEqual(health.current, health.maximum)

    def test_debug_and_movement_keys_are_distinct_and_scene_blocks_input(self):
        import pico2d.pico2d as p
        self.app.pico = p
        self.app.handle_event(SimpleNamespace(type=p.SDL_KEYDOWN, key=p.SDLK_d, repeat=False))
        self.assertIn("d", self.app.keys)
        opened = self.hud.dialogue_motion.opened
        self.app.handle_event(SimpleNamespace(type=p.SDL_KEYDOWN, key=p.SDLK_b, repeat=False))
        self.assertEqual(self.hud.dialogue_motion.opened, not opened)
        before = self.hud.state.hud.player_health.current
        self.app.handle_event(SimpleNamespace(type=p.SDL_KEYDOWN, key=p.SDLK_F2, repeat=False))
        self.assertLess(self.hud.state.hud.player_health.current, before)
        self.hud.scene = "menu"
        before = self.hud.state.hud.player_health
        self.app.handle_event(SimpleNamespace(type=p.SDL_KEYDOWN, key=p.SDLK_F2, repeat=False))
        self.assertEqual(self.hud.state.hud.player_health, before)
        self.assertFalse(self.app.keys)

    def test_local_icon_paths_survive_training_reset_and_cover_both_loadouts(self):
        icon = ROOT / "samples/ui_unit_test_v2/icons/counter_slot.png"
        with TemporaryDirectory() as directory:
            manifest = Path(directory) / "icons.json"
            manifest.write_text(json.dumps({"version": 1,
                "slot_images": {"counter": str(icon)},
                "weapon_images": {"도검": str(icon), "PDW": str(icon)}}, ensure_ascii=False), encoding="utf-8")
            self.hud.load_icon_manifest(manifest)
            self.hud.reset_training()
        for loadout in self.hud.state.hud.loadouts:
            self.assertEqual(loadout.melee.image_path, str(icon))
            self.assertEqual(loadout.ranged.image_path, str(icon))
        self.assertEqual(self.hud.config.data["v2"]["style"]["shared_swap_slot"]["images"]["counter"], str(icon))

    def test_preview_controls_are_limited_and_not_repeated_every_frame(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "control.json"
            self.app.preview_control_path = path
            self.app.perform_hud_action = Mock()
            path.write_text(json.dumps({"action": "swap"}), encoding="utf-8")
            self.app.apply_preview_control()
            self.app.apply_preview_control()
            self.app.perform_hud_action.assert_called_once_with("swap")
            path.write_text(json.dumps({"action": "unknown_action"}), encoding="utf-8")
            self.app.apply_preview_control()
            self.app.perform_hud_action.assert_called_once()
            path.write_text("[]", encoding="utf-8")
            self.app.apply_preview_control()


if __name__ == "__main__":
    unittest.main()
