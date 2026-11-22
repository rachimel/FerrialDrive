import gc
import unittest
from unittest.mock import patch
import weakref

from ferrial_drive.combat.session_gc import CombatCollection
from ferrial_drive.runtime import run_application


class CombatSessionGcTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(gc.enable if gc.isenabled() else gc.disable)
        gc.enable()

    def test_runtime_releases_combat_before_collection_and_reloads_on_same_canvas(self):
        events = []
        app_refs = []
        canvas_ids = []
        real_collect = gc.collect

        class Screen:
            def show(self, progress, label):
                events.append("loading")

            def close(self):
                events.append("loading_closed")

        class Program:
            window_size = (64, 64)

            def __init__(self):
                app_refs.append(weakref.ref(self))
                self.cycle = self
                self.running = True
                self.reload_on_exit = len(app_refs) == 1

            def prepare_combat_collection(self):
                self.collection = CombatCollection(Screen)
                return self.collection

            def enter(self):
                self.collection.set_combat(self.reload_on_exit)

            def update(self, seconds):
                events.append(("update", gc.isenabled()))
                self.running = False

            def exit(self):
                events.append("exit")

        def collect(generation):
            self.assertEqual(generation, 2)
            self.assertFalse(gc.isenabled())
            self.assertEqual(events[-2:], ["exit", "loading"])
            self.assertIsNotNone(app_refs[-1]())
            events.append("collect")
            result = real_collect(generation)
            self.assertIsNone(app_refs[-1]())
            return result

        with patch("ferrial_drive.runtime.PicoCanvas") as canvas, \
                patch("ferrial_drive.runtime.poll_events", return_value=()), \
                patch("ferrial_drive.combat.session_gc.gc.collect", side_effect=collect):
            run_application(Program, title="전투 수명 검사")
            canvas.assert_called_once()
        self.assertEqual(events, [("update", False), "exit", "loading", "collect",
                                  "loading_closed", ("update", True), "exit"])
        self.assertTrue(gc.isenabled())

    def test_collection_finishes_once_and_preserves_disabled_gc(self):
        gc.disable()
        collection = CombatCollection(None)
        with patch("ferrial_drive.combat.session_gc.gc.collect") as collect:
            collection.finish()
            collect.assert_not_called()
            collection.set_combat(True)
            collection.set_combat(False)
            self.assertFalse(gc.isenabled())
            collection.finish()
            collection.finish()
            collect.assert_called_once_with(2)
        collection.restore()
        self.assertFalse(gc.isenabled())


if __name__ == "__main__":
    unittest.main()
