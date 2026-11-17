"""테마 편집기의 상속 사용처·팔레트 출처와 배율·잘림을 적용한 강조 위치를 검사한다."""

from copy import deepcopy
from contextlib import nullcontext
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from Tools.hud_theme_editor.parts import delete_palette_color, palette_usages
from ferrial_drive.diagnostics.theme_preview import PreviewColor, ThemePreviewRenderer
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.theme import ThemeWatcher, save_theme, validate_theme, widget_colors
from tempfile import TemporaryDirectory
from ferrial_drive.ui.config import UiConfig
from ferrial_drive.ui_v2.view import UiV2View
from ferrial_drive.ui_v2.preview import create_preview


ROOT = Path(__file__).resolve().parents[2]


class ThemePreviewTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((ROOT / "samples/hud_theme_editor/default_theme.json").read_text(encoding="utf-8"))

    def test_usages_follow_overrides_and_keep_equal_hex_colors_separate(self):
        self.document["palette"]["custom"] = self.document["palette"]["text"]
        self.document["widgets"]["health"]["text"] = "custom"
        usages = palette_usages(self.document, "text")
        self.assertNotIn("text", usages["health"] if "health" in usages else [])
        self.assertIn("text", usages["weapons"])
        self.assertEqual(palette_usages(self.document, "custom"), {"health": ["text"]})
        del self.document["widgets"]["health"]["text"]
        self.assertIn("text", palette_usages(self.document, "text")["health"])

    def test_recording_uses_viewport_scale_clip_and_restores_normal_colors(self):
        config = UiConfig(ROOT / "samples/ui_unit_test_v2/ui_config.json")
        source = Mock()
        source.draw_transform.return_value = ((2, 2), (10, 20, 400, 300), (800, 600), (0, 0, 30, 40))
        view = UiV2View(config, source)
        view.hud_theme, view.theme_preview_active = self.document, True
        normal = deepcopy(config.colors)
        recorder = ThemePreviewRenderer(source)
        with widget_colors(view, "health"):
            recorder.record("rect", {"rect": Rect(-5, 10, 50, 50), "color": config.colors["text"], "opacity": 1})
        self.assertEqual(recorder.export(), [{"widget": "health", "role": "text", "palette": "text", "bounds": [20, 60, 80, 120]}])
        self.assertEqual(config.colors, normal)
        self.assertTrue(all(type(value) is str for value in config.colors.values()))

    def test_equal_colors_and_invisible_geometry_do_not_merge_sources(self):
        source = Mock()
        source.draw_transform.return_value = ((1, 1), (0, 0, 100, 100), (100, 100), None)
        recorder = ThemePreviewRenderer(source)
        for palette, opacity in (("first", 1), ("second", 1), ("hidden", 0)):
            recorder.record("rect", {"rect": Rect(5, 10, 20, 30), "opacity": opacity,
                                     "color": PreviewColor("#FFFFFF", "health", "text", palette)})
        self.assertEqual([item["palette"] for item in recorder.export()], ["first", "second"])

    def test_nested_scope_retains_its_own_source_and_untraced_rendering_is_plain(self):
        view = UiV2View(UiConfig(ROOT / "samples/ui_unit_test_v2/ui_config.json"), Mock())
        view.hud_theme = self.document
        with widget_colors(view, "health"):
            self.assertIs(type(view.config.colors["text"]), str)
        view.theme_preview_active = True
        with widget_colors(view, "health"):
            self.assertEqual(view.ui_accent.widget, "health")
            with widget_colors(view, "weapons"):
                self.assertEqual(view.config.colors["text"].widget, "weapons")
            self.assertEqual(view.config.colors["text"].widget, "health")

    def test_target_bar_uses_target_override_without_changing_global_or_health(self):
        program = create_preview()
        source = Mock()
        source.scaled.side_effect = lambda *args: nullcontext()
        view = UiV2View(program.config, source)
        view.hud_theme = self.document
        self.document["palette"]["target_only"] = "#AA3377"
        self.document["widgets"]["target"] = {"enemy": "target_only"}
        for method in ("minimap", "radar", "target", "lock_marker", "resources", "weapons",
                       "shared_swap_slot", "perspective_counter", "absorption", "dialogue"):
            setattr(view, method, Mock())
        applied = []
        view.meter = lambda *args, **kwargs: applied.append(view.config.colors["enemy"])
        normal = dict(view.config.colors)
        view._combat(program.state)
        self.assertEqual(applied, ["#AA3377"])
        self.assertEqual(view.config.colors, normal)

    def test_deleting_bound_color_clears_all_references_and_keeps_other_colors(self):
        self.document["palette"]["custom"] = "#AA3377"
        self.document["widgets"]["health"] = {"accent": "accent", "text": "custom"}
        self.document["widgets"]["target"]["enemy"] = "accent"
        self.assertEqual(delete_palette_color(self.document, "accent"), 3)
        self.assertNotIn("accent", self.document["palette"])
        self.assertTrue(all("accent" not in bindings.values() for bindings in self.document["widgets"].values()))
        self.assertEqual(self.document["widgets"]["health"]["text"], "custom")
        validate_theme(self.document)

    def test_deleting_override_uses_global_then_deleting_global_uses_original_color(self):
        view = UiV2View(UiConfig(ROOT / "samples/ui_unit_test_v2/ui_config.json"), Mock())
        view.hud_theme = self.document
        original = view.base_theme_colors["accent"]
        self.document["palette"]["custom"] = "#AA3377"
        self.document["palette"]["accent"] = "#228844"
        self.document["widgets"]["health"]["accent"] = "custom"
        delete_palette_color(self.document, "custom")
        with widget_colors(view, "health"):
            self.assertEqual(view.config.colors["accent"], "#228844")
        delete_palette_color(self.document, "accent")
        with widget_colors(view, "health"):
            self.assertEqual(view.config.colors["accent"], original)
        self.assertIn("accent", palette_usages(self.document, None)["health"])

    def test_empty_palette_saves_reloads_and_uses_base_colors_without_repopulating(self):
        for name in tuple(self.document["palette"]):
            delete_palette_color(self.document, name)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "empty.json"
            save_theme(path, self.document)
            watcher = ThemeWatcher(path)
            self.assertTrue(watcher.poll(force=True))
            self.assertEqual(watcher.document["palette"], {})
            view = UiV2View(UiConfig(ROOT / "samples/ui_unit_test_v2/ui_config.json"), Mock())
            view.hud_theme, view.theme_preview_active = watcher.document, True
            with widget_colors(view, "health"):
                self.assertEqual(view.config.colors["accent"], view.base_theme_colors["accent"])
                self.assertIsNone(view.config.colors["accent"].palette)
            self.assertEqual(view.hud_theme["palette"], {})

    def test_widget_only_binding_usage_remains_visible_after_global_role_is_removed(self):
        self.document["widgets"]["global"].pop("text")
        self.document["widgets"]["health"]["text"] = "text"
        self.assertEqual(palette_usages(self.document, "text"), {"health": ["text"]})


if __name__ == "__main__":
    unittest.main()
