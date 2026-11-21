"""시안 카드의 속성 클리핑·표시 데이터·보조 슬롯·기존 전환 연결을 검사한다."""

from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ferrial_drive.ui.config import UiConfig
from ferrial_drive.ui.state import WeaponInfo
from ferrial_drive.ui_v2.view import UiV2View
from ferrial_drive.ui_v2.weapon_card import draw_auxiliary_slot, draw_weapon_card


class WeaponCardTests(unittest.TestCase):
    def setUp(self):
        self.renderer = Mock()
        self.renderer.text_size.side_effect = lambda text, role, **kwargs: (len(text) * 18 + max(0, len(text) - 1) * kwargs.get("letter_spacing_pixels", 0), 44 if role == "v2_weapon_attribute" else 20)
        self.renderer.scaled.side_effect = lambda *args: nullcontext()
        self.config = UiConfig(ROOT / "samples/ui_unit_test_v2/ui_config.json")
        self.view = UiV2View(self.config, self.renderer)

    def test_json_attribute_list_becomes_immutable_and_legacy_constructor_still_works(self):
        attributes = ["FIRE"]
        weapon = WeaponInfo("PDW", 45, additional_attributes=attributes)
        attributes.append("TEST")
        self.assertEqual(weapon.additional_attributes, ("FIRE",))
        self.assertEqual(WeaponInfo("도검").base_attribute, "")
        for fields in ({"additional_attributes": "FIRE"}, {"additional_attributes": [""]},
                       {"base_attribute": None}, {"auxiliary_kind": "unknown"}):
            with self.assertRaises(ValueError):
                WeaponInfo("PDW", **fields)

    def test_attribute_is_cropped_to_band_and_does_not_cover_kind_or_name(self):
        weapon = WeaponInfo("PDW", 999, base_attribute="IMPACT", auxiliary_kind="back_weapon")
        with patch.object(self.view, "weapon_image"), patch.object(self.view, "panel_layer"):
            draw_weapon_card(self.view, weapon, "ranged", 0, 0, 370, 132, 0.5)
        texts = {call.args[0]: call for call in self.renderer.text.call_args_list}
        attr, name, kind = (texts[key] for key in ("IMPACT", "PDW", "RANGED"))
        clip = attr.kwargs["clip_rect"]
        self.assertLess(attr.args[2], clip.y)
        self.assertLess(clip.height, 44)
        self.assertLessEqual(clip.x + clip.width, 370 - self.view.style["weapon_card"]["kind_width_pixels"])
        self.assertLess(name.args[2], clip.y)
        self.assertGreaterEqual(kind.args[2], clip.y)
        self.assertAlmostEqual(attr.args[5], 0.5 * self.view.style["weapon_card"]["attribute_opacity"])
        self.renderer.gradient_text.assert_called_once_with(
            "999", 310, 9, "v2_ammo", self.config.colors["text"], 0.5 * self.view.style["weapon_text_opacity"],
            gradient_bottom_ratio=self.view.style["weapon_card"]["ammo_gradient_bottom_ratio"])
        self.renderer.neon_text.assert_not_called()

    def test_optional_attribute_icons_and_auxiliary_images_follow_card_opacity(self):
        weapon = WeaponInfo("도검", base_attribute="SLASH", additional_attributes=("FIRE",),
                            auxiliary_kind="counter", auxiliary_image_path="fixture.png")
        with patch("ferrial_drive.ui_v2.weapon_card.draw_attribute_icon") as icons, \
                patch.object(self.view, "weapon_image"), patch.object(self.view, "panel_layer"):
            draw_weapon_card(self.view, weapon, "melee", 20, 30, 390, 132, 0.25)
            self.assertEqual(icons.call_count, 1)
            self.assertEqual(icons.call_args.args[1], "FIRE")
            self.assertAlmostEqual(icons.call_args.args[-1], 0.25 * self.view.style["weapon_text_opacity"])
            self.renderer.image.assert_not_called()
            icons.reset_mock()
            draw_weapon_card(self.view, replace(weapon, additional_attributes=()), "melee", 20, 30, 390, 132, 0.25)
            icons.assert_not_called()

    def test_spine_width_changes_at_band_top_without_connector_and_keeps_flat_ends(self):
        with patch.object(self.view, "polygon") as polygons, patch.object(self.view, "stroke") as strokes, \
                patch.object(self.view, "panel_layer") as panels, patch.object(self.view, "weapon_image"):
            draw_weapon_card(self.view, WeaponInfo("도검"), "melee", 0, 0, 370, 132, 1)
        segments = []
        for call in polygons.call_args_list:
            a, b, c, d = call.args[0]
            first = tuple((x + y) / 2 for x, y in zip(a, d))
            last = tuple((x + y) / 2 for x, y in zip(b, c))
            segments.append((last[0] - first[0], last[1] - first[1]))
        self.assertEqual(len(segments), 2)
        lower, *upper = segments
        for segment in upper:
            self.assertAlmostEqual(lower[0] * segment[1], lower[1] * segment[0])
        lower_shape, upper_shape = [call.args[0] for call in polygons.call_args_list]
        band_top = min(y for _, y in panels.call_args_list[0].args[0])
        self.assertEqual(min(y for _, y in lower_shape), band_top)
        self.assertEqual(max(y for _, y in upper_shape), band_top)
        self.assertEqual(lower_shape[2], upper_shape[0])
        self.assertLess(upper_shape[3][0] - upper_shape[0][0], lower_shape[3][0] - lower_shape[0][0])
        self.assertEqual(upper_shape[1][1], upper_shape[2][1])
        self.assertEqual(lower_shape[0][1], lower_shape[3][1])
        right_band = panels.call_args_list[1].args[0]
        self.assertGreater(right_band[1][0], right_band[2][0])
        strokes.assert_not_called()

    def test_shared_slot_previews_next_swap_at_center_between_panels(self):
        from ferrial_drive.ui_v2.preview import HudPreview
        state = HudPreview().state.hud
        box = self.view.swap_slot_rect()
        raw_left = self.view.layout["weapons"][0] - self.view.style["weapon_depth_offset_pixels"] - self.view.style["weapon_card_cut_pixels"]
        self.assertLess(box.x + box.width, raw_left)
        from ferrial_drive.ui_v2.geometry import resource_geometry
        resource_right = max(point[0] for point in resource_geometry(self.view.layout, self.view.style["level_bevel_pixels"]).level_shape)
        self.assertAlmostEqual(box.x + box.width / 2, (resource_right + raw_left) / 2)
        with patch("ferrial_drive.ui_v2.weapon_card.draw_auxiliary_slot") as slot:
            self.view.shared_swap_slot(replace(state, active_weapon_kind="melee"), 0.6)
            self.assertEqual(slot.call_count, 1)
            self.assertEqual(slot.call_args.args[1], state.loadouts[state.active_loadout_index].ranged)
            self.view.shared_swap_slot(replace(state, active_weapon_kind="ranged"), 0.6)
            self.assertEqual(slot.call_args.args[1], state.loadouts[state.active_loadout_index].melee)

    def test_hiding_key_hints_preserves_swap_and_dash_icons(self):
        from ferrial_drive.ui_v2.preview import HudPreview
        state = HudPreview().state
        self.view.show_key_hints = False
        with patch("ferrial_drive.ui_v2.weapon_card.draw_auxiliary_slot") as slot:
            self.view.shared_swap_slot(state.hud, 1)
            slot.assert_called_once()
            self.renderer.text.assert_not_called()
        with patch.object(self.view, "slanted_text") as label:
            before = self.renderer.filtered_polygons.call_count
            self.view.dash_indicator(state, 1)
            self.assertEqual(self.renderer.filtered_polygons.call_count - before, 2)
            label.assert_not_called()

    def test_missile_and_counter_use_one_cached_image_without_runtime_strokes(self):
        for kind in ("back_weapon", "counter"):
            self.renderer.reset_mock()
            with patch.object(self.view, "stroke") as stroke, patch.object(self.view, "panel_layer") as panel:
                draw_auxiliary_slot(self.view, WeaponInfo("test", auxiliary_kind=kind), 20, 30, 120, .6)
            self.renderer.image.assert_called_once()
            self.assertTrue(self.renderer.image.call_args.args[0].is_file())
            self.assertEqual(self.renderer.image.call_args.args[2], .6)
            self.assertEqual(self.renderer.filtered_polygons.call_count, 2 if kind == "back_weapon" else 1)
            stroke.assert_not_called()
            panel.assert_not_called()

    def test_transparent_slot_glyph_uses_shared_panel_and_keeps_counter_without_ring(self):
        self.view.style["shared_swap_slot"]["glyph_kinds"] = ["back_weapon", "counter"]
        for kind in ("back_weapon", "counter"):
            self.renderer.reset_mock()
            draw_auxiliary_slot(self.view, WeaponInfo("test", auxiliary_kind=kind), 20, 30, 120, .6)
            self.renderer.image.assert_called_once()
            self.assertEqual(self.renderer.filtered_polygons.call_count, 2 if kind == "back_weapon" else 1)
            self.assertEqual(self.renderer.image.call_args.args[2], .6)



if __name__ == "__main__":
    unittest.main()
