"""v2 독립 실행 계약·표시 데이터·흡수 경로·일시정지 경계 검사."""

from dataclasses import replace
from contextlib import nullcontext
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("ui_v2_sample", ROOT / "tests/ui_unit_test_v2.py")
SAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLE)

from ferrial_drive.ui_v2.effects import AbsorptionTrail, EnergyAbsorption, ScanlineMotion, ScanlineVisual
from ferrial_drive.ui_v2.geometry import (PerspectivePlane, body_diamond, counter_plaque,
                                         resource_geometry, scaled_point, slanted_meter, tapered_stroke_mesh)
from ferrial_drive.ui.counter import CounterVisual
from ferrial_drive.ui_v2.view import UiV2View
from ferrial_drive.ui_v2.panels import build_panel_geometry, build_scanlines


class UiV2Tests(unittest.TestCase):
    def setUp(self):
        self.program = SAMPLE.create_test()

    def test_runner_reads_standalone_header_without_execution(self):
        from Tools.unit_test_runner.entrypoints import inspect_entrypoint, read_test_header, read_test_source

        path = ROOT / "tests/ui_unit_test_v2.py"
        self.assertEqual(inspect_entrypoint(path), "standalone")
        self.assertEqual(read_test_header(read_test_source(path))[0], "ui-unit-test-v2")

    def test_import_and_construction_from_other_directory_do_not_load_pico(self):
        code = ("import runpy,sys; "
                f"m=runpy.run_path({str(ROOT / 'tests/ui_unit_test_v2.py')!r}); "
                "m['create_test'](); "
                "assert not any(n == 'pico2d' or n.startswith('pico2d.') for n in sys.modules)")
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT.parent,
                                 capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_energy_and_level_reject_invalid_values(self):
        for energy in (-1, 1.1, float("nan")):
            with self.assertRaises(ValueError):
                replace(self.program.state, energy_ratio=energy)
        for level in (0, 4, True):
            with self.assertRaises(ValueError):
                replace(self.program.state, energy_level=level)

    def test_absorption_passes_through_icon_then_reaches_bar(self):
        trail = AbsorptionTrail((600, 360), (300, 660), (650, 680), 1)
        self.assertEqual(trail.point(0), (600, 360))
        self.assertEqual(trail.point(0.72), (300, 660))
        self.assertEqual(trail.point(1), (650, 680))
        effect = EnergyAbsorption(0.8)
        effect.add(trail.start, trail.icon, trail.destination)
        effect.update(0.8)
        self.assertTrue(effect.trails)
        effect.update(0.25)
        self.assertFalse(effect.trails)

    def test_pause_freezes_trail_and_resumes_from_same_time(self):
        self.program.absorb()
        self.program.pause.request(True)
        self.program.update(1)
        self.assertEqual(self.program.absorption.trails[0].elapsed_seconds, 0)
        self.program.perform("resume")
        self.program.update(1)
        self.assertEqual(self.program.absorption.trails[0].elapsed_seconds, 0)
        self.program.update(0.1)
        self.assertAlmostEqual(self.program.absorption.trails[0].elapsed_seconds, 0.1)

    def test_player_damage_does_not_increment_attack_counters(self):
        before = self.program.state.hud
        self.program.perform("damage_player")
        after = self.program.state.hud
        self.assertLess(after.player_health.current, before.player_health.current)
        self.assertEqual(after.combo_count, before.combo_count)
        self.assertEqual(after.total_damage_dealt, before.total_damage_dealt)

    def test_target_switch_and_reset_do_not_share_v1_state(self):
        before = self.program.state
        self.program.perform("next_target")
        self.assertNotEqual(self.program.state.hud.target.name, before.hud.target.name)
        self.program.perform("energy_up")
        self.assertTrue(self.program.absorption.trails)
        self.program.perform("reset")
        self.assertEqual(self.program.state, before)
        self.assertFalse(self.program.absorption.trails)

    def test_three_enemies_have_separate_health_and_selected_body_positions(self):
        self.assertEqual(len(self.program.enemies), 3)
        self.assertEqual(len(self.program.state.hud.radar_contacts), 3)
        self.program.perform("damage_target")
        damaged = self.program.state.hud.target.health
        self.program.perform("next_target")
        self.assertEqual(self.program.selected_target_id, "enemy_b")
        body = self.program.state.target_body
        self.assertEqual(body.x + body.width / 2, 920)
        self.assertEqual(self.program.state.hud.target.health.current, 680)
        for _ in range(4):
            self.program.perform("next_target")
        self.assertEqual(self.program.selected_target_id, "enemy_a")
        self.assertEqual(self.program.state.hud.target.health, damaged)

    def test_empty_candidate_toggle_clears_history_and_reacquires_from_cursor(self):
        self.program.perform("toggle_target")
        self.assertIsNone(self.program.state.hud.target)
        self.assertIsNone(self.program.state.target_body)
        self.assertFalse(self.program.acquisition.acquired_ids)
        self.program.mouse = (640, 0)
        self.program.perform("toggle_target")
        self.assertEqual(self.program.selected_target_id, "enemy_c")

    def test_right_mouse_aiming_range_and_release(self):
        p = SimpleNamespace(SDL_WINDOWEVENT=1, SDL_KEYDOWN=2, SDL_MOUSEMOTION=3,
                            SDL_MOUSEBUTTONDOWN=4, SDL_MOUSEBUTTONUP=5, SDL_BUTTON_RIGHT=3)
        self.program.pico = p
        self.program.enemies["enemy_b"]["position"] = (1050, 360)
        self.program.mouse = (1050, 360)
        self.program.perform("next_target")
        self.assertEqual(self.program.selected_target_id, "enemy_c")
        self.program.handle_event(SimpleNamespace(type=4, button=3, x=1050, y=360))
        self.assertTrue(self.program.aiming)
        self.program.perform("next_target")
        self.assertEqual(self.program.selected_target_id, "enemy_b")
        self.program.handle_event(SimpleNamespace(type=5, button=3, x=1050, y=360))
        self.assertFalse(self.program.aiming)

    def test_dialogue_toggle_preserves_selection_and_three_enemy_drawing(self):
        self.program.mouse = (640, 0)
        self.program.perform("next_target")
        self.assertEqual(self.program.selected_target_id, "enemy_c")
        self.program.renderer = Mock()
        self.program.view = Mock()
        self.program.draw()
        self.assertEqual(self.program.renderer.rect.call_count, 24)  # 플레이어와 적 3기, 각 6부품.
        self.program.perform("dialogue")
        self.assertIsNone(self.program.state.dialogue)
        self.assertEqual(self.program.selected_target_id, "enemy_c")

    def test_corner_stroke_tapers_and_shares_join_cross_sections(self):
        quads = tapered_stroke_mesh(((0, 100), (0, 0), (100, 0)), (1,), 1, 5, 20)
        self.assertAlmostEqual(abs(quads[0][0][0] - quads[0][3][0]), 1)
        self.assertAlmostEqual(abs(quads[-1][1][1] - quads[-1][2][1]), 1)
        # 앞뒤 선분은 같은 꼭짓점 단면을 공유한다.
        join = len(quads) // 2
        self.assertEqual(quads[join - 1][1], quads[join][0])
        self.assertEqual(quads[join - 1][2], quads[join][3])
        self.assertGreater(abs(quads[join - 1][1][0] - quads[join - 1][2][0]), 1)
        # 가늘어지는 구간의 양 끝을 이은 직선은 5px 지점에서 4px 두께다.
        first, last = quads[1][0], quads[1][1]
        first_back, last_back = quads[1][3], quads[1][2]
        self.assertAlmostEqual((first[0] - first_back[0]) * 0.25
                               + (last[0] - last_back[0]) * 0.75, 4)
        plateau = tapered_stroke_mesh(((0, 100), (0, 0), (100, 0)), (1,), 1, 5, 20, corner_hold_pixels=3)
        section = next(quad for quad in plateau if abs((quad[1][1] + quad[2][1]) / 2 - 3) < 1e-8)
        self.assertAlmostEqual(abs(section[1][0] - section[2][0]), 5)

    def test_weapon_panels_use_flat_text_and_horizontal_edges(self):
        renderer = SimpleNamespace(text_size=lambda text, role: (len(text) * 16, 24),
                                   scaled=lambda *args: nullcontext(), text=Mock(), warped_text=Mock())
        view = UiV2View(self.program.config, renderer)
        with patch.object(view, "polygon") as polygon, patch.object(view, "stroke"), patch.object(view, "weapon_image"):
            view.weapons(self.program.state.hud, 1, 0)
        renderer.warped_text.assert_not_called()
        self.assertEqual([call.args[0] for call in renderer.text.call_args_list],
                         ["01", "02", "MELEE", "RANGED", "45"])
        for call in polygon.call_args_list[-2:]:
            a, b, c, d = call.args[0]
            self.assertEqual(a[1], b[1])
            self.assertEqual(c[1], d[1])

    def test_panel_surface_and_individual_border_parts_draw_independently(self):
        style = self.program.config.data["v2"]["style"]
        geometry = build_panel_geometry((360, 28, 560, 130), style["panel_cut_pixels"],
                                        style["panel_frame"], style["panel_border"])
        renderer = SimpleNamespace(filtered_polygons=Mock())
        view = UiV2View(self.program.config, renderer)
        view.panel_surface(geometry, 0.5)
        self.assertEqual(renderer.filtered_polygons.call_count, 1)
        self.assertEqual(renderer.filtered_polygons.call_args.args[0], (geometry.surface,))
        renderer.filtered_polygons.reset_mock()
        visibility = {part.part_id: 0 for part in geometry.border_parts}
        visibility["upper_corner"] = 0.25
        view.panel_border(geometry.border_parts, 0.5, part_opacities=visibility)
        self.assertEqual(renderer.filtered_polygons.call_count, 1)
        call = renderer.filtered_polygons.call_args
        self.assertEqual(call.args[0], geometry.border_parts[0].polygons)
        self.assertAlmostEqual(call.args[2], 0.5 * 0.8 * 0.25)

    def test_reference_frame_has_short_side_brackets_and_detached_fragments(self):
        style = self.program.config.data["v2"]["style"]
        for rect in ((360, 28, 560, 130), (20, 20, 240, 160)):
            geometry = build_panel_geometry(rect, style["panel_cut_pixels"],
                                            style["panel_frame"], style["panel_border"])
            parts = {part.part_id: part for part in geometry.border_parts}
            upper_y = [y for polygon in parts["upper_corner"].polygons for _, y in polygon]
            lower_y = [y for polygon in parts["lower_corner"].polygons for _, y in polygon]
            self.assertLess(max(upper_y), rect[1] + rect[3] * 0.4)
            self.assertGreater(min(lower_y), rect[1] + rect[3] * 0.5)
            rail_x = [x for polygon in parts["upper_rail"].polygons for x, _ in polygon]
            fragment_x = [x for polygon in parts["upper_fragment_0"].polygons for x, _ in polygon]
            self.assertGreater(min(fragment_x), max(rail_x))

    def test_scanlines_are_clipped_to_slanted_panel_surface(self):
        style = self.program.config.data["v2"]["style"]
        geometry = build_panel_geometry((20, 20, 240, 160), style["panel_cut_pixels"],
                                        style["panel_frame"], style["panel_border"])
        strips = build_scanlines(geometry.surface, 4, 1)
        self.assertTrue(strips)
        for strip in strips:
            self.assertLessEqual(max(y for _, y in strip) - min(y for _, y in strip), 1)
            for x, y in strip:
                for a, b in zip(geometry.surface, geometry.surface[1:] + geometry.surface[:1]):
                    side = (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
                    self.assertGreaterEqual(side, -1e-8)
        for spacing, thickness in ((0, 1), (4, 0), (4, 5)):
            with self.assertRaises(ValueError):
                build_scanlines(geometry.surface, spacing, thickness)

    def test_minimap_has_no_border_and_scanlines_precede_contents(self):
        renderer = Mock()
        renderer.clip.side_effect = lambda *args: nullcontext()
        view = UiV2View(self.program.config, renderer)
        order = Mock()
        with patch.object(view, "panel_surface", order.surface), patch.object(view, "panel_scanlines", order.scanlines), \
                patch.object(view, "panel_border", order.border):
            order.attach_mock(renderer.line, "map_content")
            view.minimap(self.program.state.hud, 1)
        order.border.assert_not_called()
        self.assertEqual([call[0] for call in order.mock_calls[:3]], ["surface", "scanlines", "map_content"])
        self.assertAlmostEqual(order.surface.call_args.kwargs["fill_opacity"], 0.42)

    def test_scanline_speeds_and_phase_do_not_depend_on_frame_rate(self):
        full = ScanlineMotion(4, 3, 120)
        stepped = ScanlineMotion(4, 3, 120)
        full.update(1.5)
        for _ in range(90):
            stepped.update(1 / 60)
        self.assertAlmostEqual(full.visual.line_offset_pixels, 0.5)
        self.assertAlmostEqual(full.visual.highlight_travel_pixels, 180)
        self.assertAlmostEqual(full.visual.line_offset_pixels, stepped.visual.line_offset_pixels)
        self.assertAlmostEqual(full.visual.highlight_travel_pixels, stepped.visual.highlight_travel_pixels)
        with self.assertRaises(ValueError):
            full.update(-0.1)

    def test_pause_freezes_scanlines_and_reset_restarts_both_layers(self):
        self.program.update(0.5)
        before = self.program.scanline_motion.visual
        self.program.pause.request(True)
        self.program.update(1)
        self.assertEqual(self.program.scanline_motion.visual, before)
        self.program.perform("resume")
        self.program.update(1)
        self.assertEqual(self.program.scanline_motion.visual, before)
        self.program.update(0.1)
        self.assertNotEqual(self.program.scanline_motion.visual, before)
        self.program.perform("reset")
        self.assertEqual(self.program.scanline_motion.visual, ScanlineVisual())

    def test_pause_blocks_sample_shortcuts(self):
        self.program.pico = SimpleNamespace(SDL_WINDOWEVENT=1, SDL_KEYDOWN=2,
                                            SDLK_ESCAPE=27)
        self.program.pause.request(True)
        self.program.update(1)
        before = self.program.state
        self.program.handle_event(SimpleNamespace(type=2, key=49, repeat=False))
        self.assertEqual(self.program.state, before)

    def test_perspective_grows_toward_near_edge_without_reversing_digits(self):
        plane = PerspectivePlane(100, 200, 150, 80, depth=0.3)
        left_top, left_bottom = plane.point(0, 0), plane.point(0, 80)
        right_top, right_bottom = plane.point(150, 0), plane.point(150, 80)
        self.assertLess(left_bottom[1] - left_top[1], right_bottom[1] - right_top[1])
        self.assertLess(plane.point(0, 40)[0], plane.point(75, 40)[0])
        self.assertLess(plane.point(75, 40)[0], plane.point(150, 40)[0])
        self.assertGreater(right_top[0], right_bottom[0])

    def test_energy_frame_moves_level_with_bar_end(self):
        layout = self.program.config.data["v2"]["layout"]
        original = resource_geometry(layout)
        wider_layout = {**layout, "hp_bar": list(layout["hp_bar"]), "energy_bar": list(layout["energy_bar"])}
        wider_layout["hp_bar"][2] += 50
        wider_layout["energy_bar"][2] += 50
        wider = resource_geometry(wider_layout)
        self.assertEqual(original.icon_center, wider.icon_center)
        self.assertEqual(original.icon_radius, wider.icon_radius)
        for before, after in zip(original.level_shape, wider.level_shape):
            self.assertAlmostEqual(after[0], before[0] + 50)
            self.assertAlmostEqual(after[1], before[1])

    def test_partial_health_keeps_full_height_and_parallel_slanted_caps(self):
        bar = (360, 620, 372, 26)
        full, half = slanted_meter(bar), slanted_meter(bar, 0.5)
        self.assertEqual(half[0], full[0])
        self.assertEqual(half[-1], full[-1])
        self.assertEqual(half[2][1] - half[1][1], bar[3])
        self.assertEqual(half[2][0] - half[1][0], full[2][0] - full[1][0])
        self.assertEqual(half[1][0] - half[0][0], bar[2] / 2)

    def test_absorption_keeps_world_start_and_reaches_scaled_icon_and_bar(self):
        self.program.absorb()
        trail = self.program.absorption.trails[1]
        layout = self.program.config.data["v2"]["layout"]
        anchor = (640, 720)
        scale = self.program.config.data["v2"]["style"]["hud_scale"]
        self.assertEqual(trail.start, self.program.config.actor_anchor("target"))
        geometry = resource_geometry(layout, self.program.config.data["v2"]["style"]["level_curve_radius_pixels"])
        self.assertEqual(trail.icon, scaled_point(geometry.icon_center, anchor, scale))
        destination = geometry.energy_tip(self.program.state.energy_ratio)
        self.assertEqual(trail.destination, scaled_point(destination, anchor, scale))

    def test_resource_borders_share_large_diamond_edges_without_hp_padding(self):
        geometry = resource_geometry(self.program.config.data["v2"]["layout"])
        x, y = geometry.icon_center
        radius = geometry.icon_radius
        hp_left = geometry.hp_outline[0]
        energy_left = geometry.energy_outline[-1]
        self.assertAlmostEqual(abs(hp_left[0] - x) + abs(hp_left[1] - y), radius)
        self.assertEqual(geometry.energy_outline[0], (x + radius, y))
        self.assertAlmostEqual(abs(energy_left[0] - x) + abs(energy_left[1] - y), radius)
        self.assertEqual(geometry.hp_shape, geometry.hp_outline)
        self.assertEqual(geometry.hp_outline[3], geometry.energy_body[0])
        self.assertEqual(geometry.hp_outline[2], geometry.energy_body[1])

    def test_curved_level_touches_hp_without_entering_it(self):
        geometry = resource_geometry(self.program.config.data["v2"]["layout"])
        a, b = geometry.hp_outline[1:3]
        # 레벨이 HP와 높이를 공유해도 공유 사선의 오른쪽에만 있어야 한다.
        for x, y in geometry.level_shape:
            if y <= b[1]:
                side = (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
                self.assertLessEqual(side, 1e-8)
        self.assertIn(geometry.hp_outline[2], geometry.level_shape)
        self.assertGreater(len(geometry.level_shape), 20)

    def test_lock_border_scales_with_torso_and_keeps_its_center(self):
        for amount in (0.75, 1, 1.5):
            self.program.set_target_size(amount)
            body = self.program.state.target_body
            x, y, rx, ry = body_diamond((body.x, body.y, body.width, body.height), 1.8)
            self.assertEqual((x, y), (body.x + body.width / 2, body.y + body.height / 2))
            self.assertAlmostEqual(rx, 27 * amount)
            self.assertAlmostEqual(ry, 24.3 * amount)

    def test_counter_plaque_has_parallel_opposite_edges(self):
        a, b, c, d = counter_plaque((50, 90), (200, 100), 8, 6)
        self.assertEqual((b[0] - a[0], b[1] - a[1]), (c[0] - d[0], c[1] - d[1]))
        self.assertEqual((d[0] - a[0], d[1] - a[1]), (c[0] - b[0], c[1] - b[1]))

    def test_counter_digit_growth_keeps_last_digit_size_and_right_edge(self):
        renderer = SimpleNamespace(text_size=lambda text, role: (len(text) * 40, 60),
                                   digit_ink_bottom=lambda role: 50, warped_text=Mock())
        view = UiV2View(self.program.config, renderer)
        for label, role in (("combo", "combo_number"), ("damage", "damage_total")):
            previous_left = None
            digit_bounds = right_edge = None
            with patch.object(view, "polygon") as polygon:
                for value in (9, 99, 999, 9999, 99999999):
                    renderer.warped_text.reset_mock()
                    polygon.reset_mock()
                    view.perspective_counter(CounterVisual(value, value, 1, 1), role, label, 178, 1)
                    digits = [call for call in renderer.warped_text.call_args_list
                              if call.args[3] == role and call.args[4] == self.program.config.colors["text"]]
                    last = digits[-1]
                    _, x, y, _, _, project, _ = last.args
                    width, height = renderer.text_size("9", role)
                    bounds = (project(x, y), project(x + width, y + height))
                    if digit_bounds is not None:
                        for actual, expected in zip(sum(bounds, ()), sum(digit_bounds, ())):
                            self.assertAlmostEqual(actual, expected)
                    digit_bounds = bounds
                    self.assertEqual(last.kwargs["scale_x"], 1)
                    self.assertEqual(last.kwargs["scale_y"], 1)
                    plate = polygon.call_args_list[0].args[0]
                    if right_edge is not None:
                        for actual, expected in zip(plate[1], right_edge):
                            self.assertAlmostEqual(actual, expected)
                        self.assertLess(plate[0][0], previous_left)
                    right_edge, previous_left = plate[1], plate[0][0]
                    fragments = [call.args[0] for call in polygon.call_args_list[1:]]
                    self.assertEqual(len(fragments), 3)
                    self.assertTrue(all(max(point[0] for point in fragment) < plate[0][0]
                                        for fragment in fragments))


if __name__ == "__main__":
    unittest.main()
