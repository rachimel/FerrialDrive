"""직접 조작의 느린 프레임과 보고서 탐색 목록을 창 없이 검증한다."""

from collections import deque
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ferrial_drive.diagnostics.benchmark_archive import default_benchmark_output, write_interactive_index
from ferrial_drive.diagnostics.benchmark_report import slow_frame_details
from ferrial_drive.diagnostics.frame_benchmark import benchmark_program
from ferrial_drive.diagnostics.interactive_frame_trace import InteractiveFrameTrace
from ferrial_drive.diagnostics.render_breakdown import RenderBreakdown


class Gun:
    shots_fired = 0

    def update(self, fired=0):
        self.shots_fired += fired

    def fire_followup(self):
        self.shots_fired += 1


class InteractiveCaptureTests(unittest.TestCase):
    def test_combat_events_follow_actual_calls_and_match_retained_frame(self):
        hud = SimpleNamespace(state=SimpleNamespace(hud=SimpleNamespace(active_loadout_index=0,
                                                                        active_weapon_kind="ranged")),
                              view=SimpleNamespace(), renderer=SimpleNamespace())
        gun = Gun()
        app = SimpleNamespace(running=True, hud=hud, guns=[gun], loadout_fade_seconds=0,
                              swap_actions=SimpleNamespace(launch=lambda launches: (object(),) * launches),
                              draw=lambda: None)

        def perform(action):
            if action == "loadout":
                hud.state.hud.active_loadout_index = 1

        def action(name):
            if name == "loadout":
                app.loadout_fade_seconds = .28

        def update(seconds):
            if app.loadout_fade_seconds:
                gun.update(2)
                gun.fire_followup()
                app.swap_actions.launch(3)
                hud.perform("loadout")
                app.loadout_fade_seconds = 0
            else:
                gun.update(0)
                app.swap_actions.launch(0)

        hud.perform, app.perform_hud_action, app.update = perform, action, update
        app.handle_event = lambda event: app.perform_hud_action(event.action)
        pico = SimpleNamespace(SDL_QUIT=256, SDL_RenderFlush=lambda renderer: None, renderer=None)
        canvas = SimpleNamespace(pico=pico, present=lambda: None)
        probe = RenderBreakdown(app)
        self.addCleanup(probe.close)
        trace = InteractiveFrameTrace(probe, canvas).install()
        ticks = iter(index * .01 for index in range(200))
        events = deque([[], [], [SimpleNamespace(type=10, action="loadout")], []])
        with patch("ferrial_drive.runtime.poll_events", side_effect=lambda *a, **kw: events.popleft()), \
             patch("ferrial_drive.diagnostics.frame_benchmark.bind_gl", return_value=lambda: None), \
             patch("ferrial_drive.diagnostics.frame_benchmark.GpuFrameTimer",
                   return_value=Mock(samples_ms=[], available=False)), \
             patch("ferrial_drive.diagnostics.frame_benchmark.process_memory", return_value={}), \
             patch("ferrial_drive.diagnostics.frame_benchmark.perf_counter", side_effect=lambda: next(ticks)):
            result = benchmark_program(app, canvas, interactive=True, frames=3, warmup=1, paced=False,
                                       target_fps=60, sample_capacity=2, frame_trace=trace)

        action_frame, idle_frame = result["frames"]
        self.assertEqual((action_frame["frame"], idle_frame["frame"]), (2, 3))
        self.assertEqual(action_frame["combat_events"], [
            {"type": "loadout_transition_start"},
            {"type": "gun_fire", "gun_slot": 1, "count": 2, "followup": False},
            {"type": "gun_fire", "gun_slot": 1, "count": 1, "followup": True},
            {"type": "back_weapon_fire", "count": 3},
            {"type": "loadout_changed", "from": 1, "to": 2},
        ])
        self.assertEqual(idle_frame["combat_events"], [])
        self.assertEqual(action_frame["function_timings_ns"]["RangedCombat.update"][0], 1)
        self.assertIn("SwapActions.launch", action_frame["function_timings_ns"])
        markdown = "\n".join(slow_frame_details(result))
        for label in ("총격 2회", "백웨폰 미사일 3발", "로드아웃 1 → 2", "RangedCombat.update"):
            self.assertIn(label, markdown)
        self.assertFalse(trace.recording)
        self.assertFalse(probe.active)

    def test_frame_within_budget_has_no_detail(self):
        probe = RenderBreakdown(None)
        trace = InteractiveFrameTrace(probe, None)
        trace.begin()
        trace.timing(("draw",), 2_000_000, 2_000_000)
        row = {"work_ms": 4}
        trace.finish(row, budget_ms=16.67)
        self.assertEqual(row, {"work_ms": 4})

    def test_live_combat_phases_only_save_slow_frames_and_keep_nested_paths(self):
        from ferrial_drive.rendering.part_shadow_map import PartShadowMap
        from ferrial_drive.rendering.pico_part_motion import PicoPartMotion

        body = PicoPartMotion.__new__(PicoPartMotion)
        shadow = PartShadowMap.__new__(PartShadowMap)

        def draw(sprite):
            sprite.prepare_draw()
            sprite.prepare_shadow()

        hud = SimpleNamespace(state=SimpleNamespace(hud=SimpleNamespace(active_loadout_index=1,
                                                                        active_weapon_kind="ranged")),
                              view=SimpleNamespace(), renderer=SimpleNamespace())
        app = SimpleNamespace(hud=hud, guns=[], draw_live_combat_motion=lambda: body.draw())
        probe = RenderBreakdown(app)
        with patch.object(PicoPartMotion, "draw", draw), \
             patch.object(PicoPartMotion, "prepare_draw", lambda sprite: None, create=True), \
             patch.object(PicoPartMotion, "prepare_shadow", lambda sprite: shadow.render_depth(), create=True), \
             patch.object(PartShadowMap, "render_depth", lambda shadow: None, create=True), \
             patch("ferrial_drive.diagnostics.render_breakdown.perf_counter_ns",
                   side_effect=range(0, 100_000_000, 1_000_000)):
            trace = InteractiveFrameTrace(probe, SimpleNamespace(pico=None)).install()
            try:
                app.draw_live_combat_motion()
                trace.begin()
                app.draw_live_combat_motion()
                fast = {"work_ms": 10}
                trace.finish(fast, 16.67)
                trace.begin()
                body.draw()
                app.draw_live_combat_motion()
                slow = {"work_ms": 30}
                trace.finish(slow, 16.67)
            finally:
                probe.close()

        self.assertNotIn("live_combat_stacks", fast)
        stacks = slow["live_combat_stacks"]
        self.assertEqual(sum(row["self_wall_ns"] for row in stacks),
                         slow["function_timings_ns"][trace.live_combat_root][1])
        phases = {tuple(scope.split(".")[1] for scope in row["stack"] if scope.startswith("live_combat."))
                  for row in stacks}
        self.assertTrue({("parts_compose", "pose_prepare"),
                         ("parts_compose", "shadow_prepare", "shadow_submit")} <= phases)
        root = trace.live_combat_root
        measurement = next(row for row in probe.report()["timings"]["measurements"] if row["name"] == root)
        self.assertEqual(measurement["calls"], 2)
        self.assertTrue(all(row["stack"][0] == root for row in stacks))


class InteractiveIndexTests(unittest.TestCase):
    def test_index_includes_legacy_and_new_manual_reports(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            sources = {
                root / "report" / "legacy-direct": "interactive",
                default_benchmark_output(root, "new-direct", interactive=True): "interactive",
                root / "report" / "legacy-auto": "auto",
                default_benchmark_output(root, "new-auto", interactive=False): "auto",
                root / "report" / "broken": None,
            }
            for directory, mode in sources.items():
                directory.mkdir(parents=True)
                (directory / "report.json").write_text(json.dumps({"input_mode": mode, "status": "completed"}),
                                                        encoding="utf-8")
            notice = write_interactive_index(root).read_text(encoding="utf-8")
            self.assertIn("legacy-direct/report.json", notice)
            self.assertIn("interactive/new-direct/report.json", notice)
            for unrelated in ("legacy-auto", "new-auto", "broken"):
                self.assertNotIn(unrelated, notice)
            self.assertTrue(all(directory.is_dir() for directory in sources))
