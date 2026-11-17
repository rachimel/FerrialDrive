"""검 Trail의 색 결·레벨별 잔상 수와 잔상 명도 소멸을 검사한다."""

import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from ferrial_drive.rendering.pico_sword_effects import PicoSwordEffects, body_wind_tint
from ferrial_drive.rendering.sword_trail_texture import trail_flow_pixels
from ferrial_drive.rendering.sword_trail_geometry import curved_trail_sections

ROOT = Path(__file__).resolve().parents[2]


class TrailPresentationTests(unittest.TestCase):
    def test_curve_keeps_strikes_separate_and_does_not_edit_hit_geometry(self):
        from dataclasses import replace
        from ferrial_drive.combat.geometry import Vec2
        from ferrial_drive.combat.sword_effects import SwordSection
        points = [Vec2(0, 0), Vec2(20, 0), Vec2(20, 20), Vec2(20, 40)]
        first = [SwordSection((a, b), Vec2(), a, Vec2(), b, (i+1)/240, 0.3, 1, 1, (a, b))
                 for i, (a, b) in enumerate(zip(points, points[1:]))]
        second = [replace(row, strike_id=2, root_a=Vec2(1000, 0), root_b=Vec2(1000, 0),
                          tip_a=row.tip_a + Vec2(1000, 0), tip_b=row.tip_b + Vec2(1000, 0)) for row in first]
        before = first[:]
        curved = curved_trail_sections(first + second)
        self.assertEqual(first, before)
        self.assertEqual(len(curved), 18)
        for strike in (1, 2):
            rows = [row for row in curved if row.strike_id == strike]
            self.assertEqual(rows[-1].created_seconds, first[-1].created_seconds)
            for a, b in zip(rows, rows[1:]):
                self.assertLess((a.tip_b - b.tip_a).length, 1e-9)
            self.assertTrue(all((row.tip_b - row.tip_a).length < 20 for row in rows))
        self.assertEqual(curved[0].hit_vertices, first[0].hit_vertices)

    def test_body_wind_is_gray_and_blends_with_nearby_ground(self):
        self.assertEqual(body_wind_tint({}), (184, 184, 184))
        self.assertEqual(body_wind_tint({'ground_color_blend':0}, '#603020'), (184, 184, 184))
        self.assertEqual(body_wind_tint({'ground_color_blend':1}, '#603020'), (96, 48, 32))
        red, green, blue = body_wind_tint({}, '#603020')
        self.assertGreater(red, green)
        self.assertGreater(green, blue)
        self.assertTrue(all(32 < value < 184 for value in (red, green, blue)))

    def test_flow_has_longitudinal_threads_and_transparent_tapered_edges(self):
        pixels = trail_flow_pixels(128, 64)
        alpha = [list(pixels[(y * 128) * 4 + 3:((y + 1) * 128) * 4:4]) for y in range(64)]
        self.assertEqual(set(alpha[0] + alpha[-1]), {0})
        self.assertTrue(all(row[0] == row[-1] == 0 for row in alpha))
        self.assertGreater(max(max(row) for row in alpha), 230)
        near_end = sum(row[5] > 80 for row in alpha)
        middle = sum(row[64] > 80 for row in alpha)
        self.assertLess(near_end, middle)
        along = sum(abs(row[x + 1] - row[x]) for row in alpha for x in range(25, 100))
        across = sum(abs(alpha[y + 1][x] - alpha[y][x]) for y in range(63) for x in range(25, 100))
        self.assertLess(along, across)

    def test_training_profiles_keep_blue_and_echo_counts(self):
        config = json.loads((ROOT / 'samples/sword_movement/movement_config.json').read_text(encoding='utf-8'))
        profiles = config['sword_effects']['levels']
        self.assertEqual([p['echo_count'] for p in profiles], [0, 4, 8])
        self.assertEqual([p['trail_opacity'] for p in profiles], [0.5, 0.65, 0.8])
        for profile in profiles:
            red, green, blue = (int(profile['color'][i:i + 2], 16) for i in (1, 3, 5))
            self.assertLess(red, green)
            self.assertLess(green, blue)

    def test_echo_loses_brightness_as_well_as_opacity(self):
        echo = SimpleNamespace(position_m=(0, 0), clip_name='attack', elapsed_seconds=0.2,
                               opacity=0.5, tint=(0.2, 0.5, 1), tint_mix=0.7)
        effect = SimpleNamespace(echoes=[echo], opacity=Mock(side_effect=[1, 0.5, 0.1]))
        sprite = Mock()
        painter = PicoSwordEffects(Mock())
        for _ in range(3):
            painter.draw_echoes(effect, SimpleNamespace(world_to_screen=lambda p: p),
                               SimpleNamespace(project=lambda p: p), sprite, {'attack': None},
                               scale=1, interpolate=True, easing='linear')
        calls = [call.kwargs for call in sprite.draw.call_args_list]
        for earlier, later in zip(calls, calls[1:]):
            self.assertGreater(earlier['brightness'], later['brightness'])
            self.assertGreater(earlier['opacity'], later['opacity'])
