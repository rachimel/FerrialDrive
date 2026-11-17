"""팔레트 연결·중첩 위젯 격리·저장 실패 보존과 잘못된 실시간 테마 거절을 검사한다."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import unittest

from ferrial_drive.ui.config import UiConfig
from ferrial_drive.ui.theme import ThemeWatcher, default_theme, save_theme, validate_theme, widget_colors
from ferrial_drive.ui_v2.view import UiV2View

ROOT = Path(__file__).resolve().parents[2]


class HudThemeTests(unittest.TestCase):
    def test_overdrive_palette_applies_to_nested_widgets_without_changing_saved_theme(self):
        view = UiV2View(self.config, Mock())
        view.hud_theme = self.document
        original = deepcopy(self.document)
        normal = dict(self.config.colors)
        view.overdrive_palette = True
        for widget in ("health", "weapons", "radar", "menus"):
            with widget_colors(view, widget):
                color = self.config.colors["ui_accent"]
                self.assertGreater(int(color[1:3], 16), int(color[3:5], 16))
                with widget_colors(view, "damage"):
                    self.assertEqual(self.config.colors["ui_accent"], color)
        self.assertEqual(self.document, original)
        self.assertEqual(self.config.colors, normal)
        view.overdrive_palette = False
        with widget_colors(view, "health"):
            self.assertEqual(self.config.colors, normal)

    def setUp(self):
        self.config = UiConfig(ROOT / "samples/ui_unit_test_v2/ui_config.json")
        self.document = default_theme(self.config.colors)

    def test_overdrive_cache_tracks_palette_edits_rainbow_and_theme_reload(self):
        view = UiV2View(self.config, Mock())
        self.document["palette"]["accent"] = "#FFFFFF"
        view.hud_theme = self.document
        view.overdrive_palette = True
        with widget_colors(view, "health"):
            self.assertEqual(view.config.colors["accent"], "#FF4045")
        # 편집기가 같은 문서를 수정해도 기존 캐시 색이 남으면 안 된다.
        self.document["palette"]["accent"] = "#000000"
        with widget_colors(view, "health"):
            self.assertEqual(view.config.colors["accent"], "#000000")
        replacement = deepcopy(self.document)
        replacement["palette"]["accent"] = "#FFFFFF"
        view.hud_theme = replacement
        view.overdrive_color = "#00FF00"
        with widget_colors(view, "health"):
            self.assertEqual(view.config.colors["accent"], "#40FF40")
            self.assertEqual(view.config.colors["energy"], view.base_theme_colors["energy"])
        view.overdrive_color = None
        with widget_colors(view, "health"):
            self.assertEqual(view.config.colors["accent"], "#FF4045")
        self.assertEqual(view.config.colors, view.base_theme_colors)

    def test_widget_overrides_are_scoped_and_nested_state_is_restored_even_on_error(self):
        view = UiV2View(self.config, Mock())
        original = dict(self.config.colors)
        self.document["palette"]["custom"] = "#AA7733"
        self.document["widgets"]["health"] = {"accent": "custom"}
        view.hud_theme = self.document
        with widget_colors(view, "health"):
            self.assertEqual(view.config.colors["accent"], "#AA7733")
            with self.assertRaises(RuntimeError):
                with widget_colors(view, "weapons"):
                    self.assertEqual(view.config.colors["accent"], original["accent"])
                    raise RuntimeError("그리기 실패")
            self.assertEqual(view.config.colors["accent"], "#AA7733")
        self.assertEqual(self.config.colors, original)

    def test_live_palette_update_changes_all_bindings_but_preserves_energy_semantics(self):
        view = UiV2View(self.config, Mock())
        self.document["palette"]["text"] = "#35CB99"
        self.document["widgets"]["global"]["energy"] = "text"
        view.hud_theme = self.document
        for group in ("health", "weapons", "menus"):
            with widget_colors(view, group):
                self.assertEqual(view.config.colors["text"], "#35CB99")
                self.assertEqual(view.config.colors["energy"], view.base_theme_colors["energy"])
                self.assertEqual(view.level_energy_color(2), view.style["energy_level_colors"][1])

    def test_invalid_reload_keeps_last_good_palette_and_valid_replacement_recovers(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "theme.json"
            watcher = ThemeWatcher(path)
            self.assertFalse(watcher.poll(force=True))
            save_theme(path, self.document)
            self.assertTrue(watcher.poll(force=True))
            previous = deepcopy(watcher.document)
            path.write_text('{"version":1}', encoding="utf-8")
            self.assertFalse(watcher.poll(force=True))
            self.assertEqual(watcher.document, previous)
            self.assertIsNotNone(watcher.error)
            self.document["palette"]["text"] = "#FEDCBA"
            save_theme(path, self.document)
            self.assertTrue(watcher.poll(force=True))
            self.assertEqual(watcher.document["palette"]["text"], "#FEDCBA")

    def test_failed_atomic_save_does_not_replace_previous_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "theme.json"
            save_theme(path, self.document)
            before = path.read_bytes()
            self.document["palette"]["text"] = "#123456"
            with patch("ferrial_drive.ui.theme.os.replace", side_effect=OSError("저장 실패")):
                with self.assertRaises(OSError):
                    save_theme(path, self.document)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_missing_palette_reference_and_non_color_values_are_rejected(self):
        self.document["widgets"]["weapons"]["text"] = "missing"
        with self.assertRaises(ValueError):
            validate_theme(self.document)
        self.document = default_theme(self.config.colors)
        self.document["palette"]["text"] = "red"
        with self.assertRaises(ValueError):
            validate_theme(self.document)


if __name__ == "__main__":
    unittest.main()
