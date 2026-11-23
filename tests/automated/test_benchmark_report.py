"""실패 보고서 오판·조건별 결과 손실과 combat 자동 입력을 검사한다."""

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from xml.etree import ElementTree as ET

from ferrial_drive.diagnostics.benchmark_report import render_report, write_report
from ferrial_drive.diagnostics.render_breakdown import RenderBreakdown


class ReportTests(unittest.TestCase):
    def test_failed_load_has_no_fabricated_fps(self):
        report = render_report({"status": "error", "error": "MemoryError"})
        self.assertIn("MemoryError", report)
        self.assertIn("프레임 측정값 없음", report)
        self.assertNotIn("실측 0.00", report)

    def test_comparisons_keep_each_round_and_missing_gpu(self):
        benchmark = {"observed_fps": 58.25, "completed": False, "target_met": False,
                     "work_ms": {"p95": 21}, "cpu_ms": {"update_ms": {"mean": 4}},
                     "gpu_draw_elapsed_ms": None, "deadline_miss_percent": 30}
        report = render_report({"status": "interrupted", "benchmark": benchmark,
                                "comparisons": [{"round": index, "variant": "baseline", "benchmark": benchmark}
                                                for index in (1, 2)]})
        self.assertIn("| 1 | baseline | 58.25 | 21.00 | 30.00 | False |", report)
        self.assertIn("| 2 | baseline |", report)
        self.assertIn("| GPU draw elapsed | 미측정", report)
        self.assertIn("목표 충족: False", report)

    def test_report_rebuild_reads_limits_without_changing_json(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "report.json"
            text = json.dumps({"status": "error"})
            source.write_text(text, encoding="utf-8")
            source.with_name("limits_final.json").write_text(json.dumps({
                "verified": True, "peak_process_commit_bytes": 128 * 1024**2}), encoding="utf-8")
            report = write_report(source).read_text(encoding="utf-8")
            self.assertIn("128.00MiB", report)
            self.assertEqual(source.read_text(encoding="utf-8"), text)
            self.assertNotIn("flamegraph.svg", report)
            self.assertFalse(source.with_name("flamegraph.svg").exists())

    def test_report_saves_flamegraph_with_nested_widths(self):
        result = {"draw_breakdown": {"flamegraph_stacks": [
            {"stack": ["update"], "self_wall_ns": 3_000_000},
            {"stack": ["update", "A<&>"], "self_wall_ns": 2_000_000},
            {"stack": ["draw"], "self_wall_ns": 5_000_000},
        ]}}
        with TemporaryDirectory() as directory:
            source = Path(directory) / "report.json"
            source.write_text(json.dumps(result), encoding="utf-8")
            report = write_report(source).read_text(encoding="utf-8")
            self.assertIn("[Flamegraph 열기](flamegraph.svg)", report)
            svg = ET.parse(source.with_name("flamegraph.svg"))
            rects = [rect for rect in svg.findall(".//{*}g/{*}rect") if "stroke" in rect.attrib]
            width = float(svg.getroot().attrib["width"]) - 40
            self.assertEqual([float(rect.attrib["width"]) for rect in rects], [width * .5, width * .5, width * .2])
            self.assertLess(int(rects[2].attrib["y"]), int(rects[1].attrib["y"]))
            titles = [element.text for element in svg.findall(".//{*}g/{*}title")]
            self.assertIn("update → A<&>\n포함 2.000 ms (20.00%)\n자체 2.000 ms", titles)

    def test_tiny_blocks_have_full_names_in_legend(self):
        long_name = "SomeVeryLongClass." + "prepare_" * 10 + "surface"
        result = {"draw_breakdown": {"flamegraph_stacks": [
            {"stack": ["main"], "self_wall_ns": 1_000_000},
            {"stack": ["main", long_name], "self_wall_ns": 1},
        ]}}
        with TemporaryDirectory() as directory:
            source = Path(directory) / "report.json"
            source.write_text(json.dumps(result), encoding="utf-8")
            write_report(source)
            svg = ET.parse(source.with_name("flamegraph.svg"))
            legend = svg.find(".//{*}g[@aria-label='전체 함수·구간 이름']")
            self.assertIn(long_name, [text.text for text in legend.findall("{*}text")])
            self.assertGreater(int(svg.getroot().attrib["width"]), 1440)

    def test_report_links_frame_svg_and_counts_nested_phases_once(self):
        root = ["EncounterApplication.draw_live_combat_motion"]
        compose = root + ["live_combat.parts_compose.PicoPartMotion.draw"]
        shadow = compose + ["live_combat.shadow_prepare.PicoPartMotion.prepare_shadow"]
        stacks = [
            (root, 1), (compose, 3), (compose + ["PartPainter.paint"], 2),
            (compose + ["live_combat.pose_prepare.PicoPartMotion.prepare_draw"], 4),
            (shadow, 2), (shadow + ["live_combat.shadow_submit.PartShadowMap.render_depth"], 1),
        ]
        result = {"benchmark": {"frames": [{"frame": 90, "work_ms": 39.3, "session_ms": 1830,
                    "live_combat_stacks": [{"stack": path, "self_wall_ns": ms * 1_000_000}
                                           for path, ms in stacks]}]}}
        with TemporaryDirectory() as directory:
            source = Path(directory) / "report.json"
            source.write_text(json.dumps(result), encoding="utf-8")
            report = write_report(source).read_text(encoding="utf-8")
            name = "flamegraphs/frame-000090.svg"
            self.assertIn(f"| 90 / 1.83초 | 39.30 | 13.00 | 4.00 | 2.00 | 1.00 | 5.00 | 1.00 | [열기]({name}) |",
                          report)
            svg = ET.parse(source.parent / name)
            descriptions = [text.text for text in svg.findall(".//{*}title")]
            self.assertTrue(any("live_combat.shadow_submit.PartShadowMap.render_depth" in text
                                and "자체 1.000 ms" in text for text in descriptions))


class CombatInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "hardware_profile_benchmark.py"
        spec = importlib.util.spec_from_file_location("hardware_benchmark", path)
        cls.entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.entry)

    def test_smg_overdrive_uses_game_actions_after_reset(self):
        calls = []
        app = SimpleNamespace(window_size=(1920, 1080), reset=lambda: calls.append("reset"),
                              set_energy_level=lambda value: calls.append(value),
                              perform_hud_action=calls.append)
        self.entry.prepare_auto_cycle(app, weapon="smg", overdrive=True)
        self.assertEqual(calls, ["reset", 3, "swap", "overdrive"])
        self.assertTrue(app.attack_held)

    def test_aim_uses_tuple_player_position_and_ignores_dead_enemy(self):
        from ferrial_drive.combat.geometry import Vec2
        enemies = {str(index): SimpleNamespace(alive=alive, position_m=Vec2(x, 0),
                                               profile=SimpleNamespace(height_pixels=10))
                   for index, (x, alive) in enumerate(((0, False), (5, True), (20, True)))}
        app = SimpleNamespace(encounter=SimpleNamespace(enemies=enemies),
                              controller=SimpleNamespace(position_m=(0, 0)),
                              projection=SimpleNamespace(project=lambda point: point),
                              camera=SimpleNamespace(world_to_screen=lambda point: point))
        self.entry.aim_at_enemy(app)
        self.assertEqual(app.mouse, (5, -10))

    def test_auto_dash_reproduces_ground_effect_workload(self):
        app = SimpleNamespace(window_size=(1920, 1080), reset=Mock(), set_energy_level=Mock(), keys=set())
        self.entry.prepare_auto_cycle(app, dash=True)
        self.assertEqual(app.keys, {"d", "left_shift"})

    def test_combat_activity_excludes_warmup_and_restores_hooks(self):
        encounter = SimpleNamespace(enemies={"a": SimpleNamespace(alive=True)}, projectiles=[], result="running")
        for name in ("advance", "_think", "_move", "sync_health", "advance_reactions"):
            setattr(encounter, name, Mock())
        hud = SimpleNamespace(state=SimpleNamespace(overdrive=True, hud=SimpleNamespace(active_weapon_kind="ranged")), draw=Mock(),
                              view=SimpleNamespace(), renderer=SimpleNamespace(directional_blur=Mock()))
        app = SimpleNamespace(encounter=encounter, encounter_view=None, update=Mock(), hud=hud,
                              guns=[SimpleNamespace(projectiles=[1, 2])], sword_effects=None, draw_world=Mock(),
                              ground=None, shadow_blend=None, ground_effect_renderer=None, sword_renderer=None,
                              attack_sprite=None, motion_sprite=None)
        original = app.update
        probe = RenderBreakdown(app).install()
        try:
            app.update(.1)
            probe.step(True)
            app.update(.1)
            encounter.enemies["a"].alive = False
            encounter.result = "victory"
            probe.step(True)
            app.update(.1)
            activity = probe.report()["combat_activity"]
            self.assertEqual(activity["movement_backend"], "python")
            self.assertEqual(activity["sampled_frames"], 2)
            self.assertEqual(activity["alive_min"], 0)
            self.assertEqual(activity["mean"]["alive_enemies"], .5)
            self.assertEqual(activity["peak"]["player_projectiles"], 2)
            self.assertEqual(activity["running_frames"], 1)
            self.assertEqual(activity["ranged_frames"], 2)
            self.assertEqual(probe.report()["frames"], 2)
        finally:
            probe.close()
        self.assertIs(app.update, original)


if __name__ == "__main__":
    unittest.main()
