"""개별 피해 숫자의 겹침·크기·고정 위치와 TV 펼침 연결을 확인한다."""

from dataclasses import replace
from types import SimpleNamespace
import unittest

from ferrial_drive.ui.damage import DamageNumbers, DamageVisual
from ferrial_drive.ui.view import UiView


class DamagePopupTests(unittest.TestCase):
    def make_numbers(self, **kwargs):
        settings = dict(measure_text=lambda text: (len(text) * 20, 36),
                        digit_scales=(0.75, 1, 1.3, 1.6, 1.9), gap_pixels=6,
                        width_expand_seconds=0.05, height_expand_seconds=0.06)
        settings.update(kwargs)
        return DamageNumbers(1.15, 0, 0, **settings)

    def test_digit_boundaries_scale_up_and_cap_without_hiding_the_amount(self):
        numbers = self.make_numbers()
        for amount in (9, 10, 99, 100, 999, 1000, 9999, 10000, 999999):
            numbers.add("target", amount, 640, 360)
        expected = (0.75, 1, 1, 1.3, 1.3, 1.6, 1.6, 1.9, 1.9)
        self.assertEqual(tuple(visual.font_scale for visual in numbers.visuals), expected)
        self.assertEqual(numbers.visuals[-1].amount, 999999)

    def test_burst_reserves_full_size_for_all_owners_before_expansion(self):
        numbers = self.make_numbers()
        for index, amount in enumerate((9, 99, 999, 9999, 99, 10000, 5, 875, 26, 1000)):
            old_positions = [(popup.x, popup.y) for popup in numbers.popups]
            numbers.add("player" if index % 2 else "target", amount, 640, 360)
            self.assertEqual([(popup.x, popup.y) for popup in numbers.popups[:-1]], old_positions)
        self.assertTrue(all(visual.height_progress == 0 for visual in numbers.visuals))
        for index, popup in enumerate(numbers.popups):
            a = popup.bounds
            for other in numbers.popups[index+1:]:
                b = other.bounds
                self.assertTrue(a.x + a.width + 6 <= b.x or b.x + b.width + 6 <= a.x
                                or a.y + a.height + 6 <= b.y or b.y + b.height + 6 <= a.y)
        positions = [(popup.x, popup.y) for popup in numbers.popups]
        numbers.update(0.3)
        self.assertTrue(all(visual.height_progress == 1 for visual in numbers.visuals))
        self.assertEqual([(popup.x, popup.y) for popup in numbers.popups], positions)

    def test_expiration_and_owner_clear_free_positions_without_moving_survivors(self):
        numbers = self.make_numbers()
        numbers.add("target", 99, 640, 360)
        numbers.add("player", 99, 640, 360)
        survivor = numbers.popups[-1].bounds
        numbers.clear("target")
        self.assertEqual(numbers.popups[0].bounds, survivor)
        numbers.add("target", 99, 640, 360)
        self.assertEqual((numbers.popups[-1].x, numbers.popups[-1].y), (640, 360))
        numbers.update(2)
        self.assertEqual(numbers.visuals, ())
        numbers.add("target", 99, 640, 360)
        self.assertEqual((numbers.popups[-1].x, numbers.popups[-1].y), (640, 360))

    def test_random_scatter_is_used_once_and_positions_stay_fixed(self):
        numbers = DamageNumbers(1.15, 64, 44, measure_text=lambda text: (20, 36))
        numbers.random.seed(7)
        numbers.add("target", 9, 640, 360)
        first = numbers.visuals[0]
        self.assertTrue(576 <= first.x <= 704)
        self.assertTrue(316 <= first.y <= 404)
        numbers.update(0.7)
        self.assertEqual((first.x, first.y), (numbers.visuals[0].x, numbers.visuals[0].y))

    def test_fixed_player_and_sliding_target_stay_separate_through_scene_transition(self):
        numbers = self.make_numbers()
        numbers.add("target", 99, 640, 360, offset_x_range=(0, 36))
        numbers.add("player", 99, 686, 360)
        target, player = numbers.popups
        for shift in (0, 9, 18, 27, 36):
            left, right = target.x + shift - target.width / 2, target.x + shift + target.width / 2
            fixed = player.bounds
            self.assertTrue(right + 6 <= fixed.x or left >= fixed.x + fixed.width + 6
                            or target.y + target.height + 6 <= fixed.y
                            or target.y >= fixed.y + fixed.height + 6)

    def test_scaled_tv_motion_keeps_center_and_one_pixel_line(self):
        calls, rects = [], []
        renderer = SimpleNamespace(text_size=lambda *args: (60, 36),
                                   text=lambda *args, **kwargs: calls.append((args, kwargs)),
                                   rect=lambda rect, *args: rects.append(rect))
        config = SimpleNamespace(colors={"damage_number": "#FF625D", "accent": "#91AEBB"})
        view = UiView(config, renderer)
        visual = DamageVisual(999, 640, 360, 1, "player", 0.5, 0, 1.3)
        view.damage_number(visual, 1, 36)
        self.assertEqual(rects[-1].height, 1)
        self.assertEqual(rects[-1].width, 60 * 1.3 * 0.5)
        center = 360 + 36 * 1.3 / 2
        self.assertAlmostEqual(rects[-1].y + 0.5, center)
        for phase in (0.2, 1, 0.6):
            view.damage_number(replace(visual, width_progress=1, height_progress=phase), 1, 36)
            args, kwargs = calls[-1]
            self.assertEqual(args[1], 640)
            self.assertAlmostEqual(args[2] + 36 * kwargs["scale_y"] / 2, center)
            self.assertEqual(kwargs["scale_x"], 1.3)

    def test_invalid_layout_inputs_are_rejected_and_zero_damage_is_ignored(self):
        for settings in ({"digit_scales": ()}, {"digit_scales": (1, 0.5)},
                         {"digit_scales": (float("nan"),)}, {"gap_pixels": -1}):
            with self.assertRaises(ValueError):
                self.make_numbers(**settings)
        numbers = self.make_numbers()
        numbers.add("target", 0, 640, 360)
        self.assertEqual(numbers.visuals, ())
        with self.assertRaises(ValueError):
            numbers.add("target", 3.5, 640, 360)
        with self.assertRaises(ValueError):
            numbers.add("target", 3, float("inf"), 360)
        with self.assertRaises(ValueError):
            self.make_numbers(measure_text=lambda text: (0, 36)).add("target", 3, 640, 360)


if __name__ == "__main__":
    unittest.main()
