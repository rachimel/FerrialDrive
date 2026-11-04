"""무기 교체 중 실루엣 비율과 합친 원본의 연결·외곽선을 확인한다."""

from collections import deque
from pathlib import Path
from types import SimpleNamespace
import unittest

from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.config import UiConfig
from ferrial_drive.ui.weapon_icons import WEAPON_ASPECTS, fit_weapon_icon, weapon_icon_pixels
from ferrial_drive.ui.state import WeaponInfo
from ferrial_drive.ui.view import UiView


ROOT = Path(__file__).resolve().parents[2]


class WeaponIconTests(unittest.TestCase):
    def test_swap_preserves_sword_and_pdw_aspect_at_every_size(self):
        config = UiConfig(ROOT / "samples/ui_unit_test/ui_config.json")
        slots = config.layout["equipment_slots"]
        for kind in ("melee", "ranged"):
            small = slots.get(kind + "_inactive", slots["inactive"])["image"]
            large = slots.get(kind + "_active", slots["active"])["image"]
            for weight in (0, 0.25, 0.5, 0.75, 1):
                area = Rect(*(a + (b - a) * weight for a, b in zip(small, large)))
                fitted = fit_weapon_icon(kind, area)
                self.assertAlmostEqual(fitted.width / fitted.height, WEAPON_ASPECTS[kind])
                self.assertGreaterEqual(fitted.x, area.x)
                self.assertGreaterEqual(fitted.y, area.y)
                self.assertLessEqual(fitted.x + fitted.width, area.x + area.width + 0.000001)
                self.assertLessEqual(fitted.y + fitted.height, area.y + area.height + 0.000001)

    def test_sword_uses_card_width_throughout_swap_without_empty_ammo_space(self):
        config = UiConfig(ROOT / "samples/ui_unit_test/ui_config.json")
        images, panels = [], []
        renderer = SimpleNamespace(
            text_size=lambda *args: (28, 17), rect=lambda *args: None,
            text=lambda *args, **kwargs: None,
            weapon_silhouette=lambda kind, rect, *args: images.append(rect))
        view = UiView(config, renderer)
        view.panel = lambda area, *args, **kwargs: panels.append(Rect(*area))
        previous_width = 0
        for step in range(21):
            weight = step / 20
            view.equipment_weapon(WeaponInfo("도검"), "melee", weight, 900, 516, 1)
            image, card = images[-1], panels[-1]
            right_gap = card.x + card.width - image.x - image.width
            self.assertAlmostEqual(right_gap, 12 + 4 * weight)
            self.assertAlmostEqual(image.width / image.height, WEAPON_ASPECTS["melee"])
            self.assertGreaterEqual(image.width, previous_width)
            self.assertGreaterEqual(image.x, card.x)
            self.assertGreaterEqual(image.y, card.y)
            self.assertLessEqual(image.y + image.height, card.y + card.height)
            previous_width = image.width

    def test_sword_blade_guard_and_handle_form_one_connected_silhouette(self):
        width, height, pixels = weapon_icon_pixels("melee", (1, 2, 3), (4, 5, 6), 0)
        opaque = {i for i in range(width * height) if pixels[i * 4 + 3]}
        seed = next(iter(opaque))
        visited, pending = {seed}, deque([seed])
        while pending:
            point = pending.popleft()
            x, y = point % width, point // width
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                neighbor = ny * width + nx
                if 0 <= nx < width and 0 <= ny < height and neighbor in opaque and neighbor not in visited:
                    visited.add(neighbor)
                    pending.append(neighbor)
        self.assertEqual(visited, opaque)

    def test_pdw_outline_surrounds_the_union_without_internal_part_borders(self):
        width, height, pixels = weapon_icon_pixels("ranged", (1, 2, 3), (4, 5, 6), 4)
        colors = {bytes(pixels[i:i + 4]) for i in range(0, len(pixels), 4)}
        self.assertEqual(colors, {b"\0\0\0\0", bytes((1, 2, 3, 255)), bytes((4, 5, 6, 255))})
        receiver = (round(height * 0.4) * width + round(width * 0.3)) * 4
        self.assertEqual(pixels[receiver:receiver + 4], bytes((1, 2, 3, 255)))


if __name__ == "__main__":
    unittest.main()
