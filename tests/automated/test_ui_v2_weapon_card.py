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
from ferrial_drive.ui_v2.weapon_card import draw_weapon_card


class WeaponCardTests(unittest.TestCase):
    def setUp(self):
        self.renderer = Mock()
        self.renderer.text_size.side_effect = lambda text, role: (len(text) * 18, 44 if role == "v2_weapon_attribute" else 20)
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
        self.assertEqual(self.renderer.neon_text.call_args.args[0], "999")

    def test_optional_attribute_icons_and_auxiliary_images_follow_card_opacity(self):
        weapon = WeaponInfo("도검", base_attribute="SLASH", additional_attributes=("FIRE",),
                            auxiliary_kind="counter", auxiliary_image_path="fixture.png")
        with patch("ferrial_drive.ui_v2.weapon_card.draw_attribute_icon") as icons, \
                patch.object(self.view, "weapon_image"), patch.object(self.view, "panel_layer"):
            draw_weapon_card(self.view, weapon, "melee", 20, 30, 390, 132, 0.25)
            self.assertEqual(icons.call_count, 1)
            self.assertEqual(icons.call_args.args[1], "FIRE")
            self.assertAlmostEqual(icons.call_args.args[-1], 0.25 * self.view.style["weapon_text_opacity"])
            self.assertEqual(self.renderer.image.call_args.args[0], "fixture.png")
            self.assertEqual(self.renderer.image.call_args.args[2], 0.25)
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
        # 원의 선만 남고 하단 패널 외곽선은 그리지 않는다.
        self.assertEqual(strokes.call_count, 1)
        self.assertEqual(len(strokes.call_args.args[0]), 49)

    def test_circle_has_gap_from_thin_spine_midpoint_and_content_stays_to_its_right(self):
        weapon = WeaponInfo("PDW", 45, auxiliary_image_path="fixture.png")
        with patch.object(self.view, "polygon") as polygons, patch.object(self.view, "stroke"), \
                patch.object(self.view, "panel_layer"), patch.object(self.view, "weapon_image") as image:
            draw_weapon_card(self.view, weapon, "ranged", 0, 0, 420, 132, 1)
        lower_piece, upper_piece = polygons.call_args_list[1].args[0], polygons.call_args_list[-1].args[0]
        endpoints = (lower_piece[0], lower_piece[3], upper_piece[1], upper_piece[2])
        center_x, center_y = tuple(sum(point[axis] for point in endpoints) / 4 for axis in (0, 1))
        icon = self.renderer.image.call_args.args[1]
        radius = self.view.style["weapon_card"]["auxiliary_diameter_pixels"] / 2
        gap = self.view.style["weapon_card"]["auxiliary_gap_pixels"]
        self.assertAlmostEqual(icon.x + icon.width / 2 + radius + gap, center_x)
        self.assertAlmostEqual(icon.y + icon.height / 2, center_y)
        circle_right = center_x - gap
        self.assertGreater(image.call_args.args[2].x, circle_right)
        name = next(call for call in self.renderer.text.call_args_list if call.args[0] == "PDW")
        self.assertGreater(name.args[1], circle_right)


if __name__ == "__main__":
    unittest.main()
