"""v2 독립 실행 계약·표시 데이터·흡수 경로·일시정지 경계 검사."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("ui_v2_sample", ROOT / "tests/ui_unit_test_v2.py")
SAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLE)

from ferrial_drive.ui_v2.effects import AbsorptionTrail, EnergyAbsorption
from ferrial_drive.ui_v2.geometry import (PerspectivePlane, body_diamond, counter_plaque,
                                         resource_geometry, scaled_point, slanted_meter)


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

    def test_pause_blocks_sample_shortcuts(self):
        self.program.pico = SimpleNamespace(SDL_WINDOWEVENT=1, SDL_KEYDOWN=2,
                                            SDLK_F1=1001, SDLK_ESCAPE=27)
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


if __name__ == "__main__":
    unittest.main()
