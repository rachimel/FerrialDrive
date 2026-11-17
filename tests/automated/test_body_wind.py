"""몸 주변 검풍의 후방 사각·유효 시간·중복 타격과 이동 관통을 검사한다."""

from math import cos, pi, sin
import unittest

from ferrial_drive.assets.directional import SCREEN_DIRECTIONS
from ferrial_drive.combat.geometry import Vec2, moving_circle_touches_polygon
from ferrial_drive.combat.sword_effects import BladeTrajectory, SwordEffects, SwordTarget, body_wind_sector
from test_sword_effects import settings, step


class BodyWindTests(unittest.TestCase):
    def make_effect(self):
        config = settings()
        config['body_wind'] = dict(enabled=True, radius_pixels=40, center_offset_pixels=(0, 0),
                                   rear_half_angle_degrees=30, segments=30)
        trajectory = BladeTrajectory({'combo_01/e': [(0, Vec2(1000, 0), Vec2(1100, 0)),
                                                     (1, Vec2(1000, 0), Vec2(1100, 20))]})
        return SwordEffects(trajectory, config, scale=1, project=lambda p: p, easing='linear')

    def test_rear_thirty_degrees_on_each_side_stays_open_in_all_directions(self):
        config = self.make_effect().settings['body_wind']
        for index, direction in enumerate(SCREEN_DIRECTIONS):
            wind = body_wind_sector(Vec2(), direction, config, 1)
            for relative, expected in ((0, True), (90, True), (-90, True),
                                       (149, True), (-149, True), (151, False), (-151, False), (180, False)):
                angle = index * pi / 4 + relative * pi / 180
                target = Vec2(cos(angle), sin(angle)) * 30
                hit = any(moving_circle_touches_polygon(target, target, 0, triangle) for triangle in wind.triangles)
                self.assertEqual(hit, expected, (direction, relative))

    def test_body_hit_and_blade_hit_share_one_hit_per_strike(self):
        effect = self.make_effect()
        body = SwordTarget('body', Vec2(0, 20), 1)
        blade = SwordTarget('blade', Vec2(1050, 5), 1)
        effect.update(0.5, [step(0, 0.5)], 1, [body, blade])
        self.assertCountEqual(effect.hits, [(1, 'body'), (1, 'blade')])
        effect.update(0.5, [step(0.5, 1)], 1, [body, blade])
        self.assertEqual(effect.hits, [])

    def test_wind_hits_only_in_active_window_and_does_not_remain(self):
        effect = self.make_effect()
        effect.settings['active_phase_windows'] = [[0.2, 0.4]] * 4
        target = SwordTarget('body', Vec2(0, 20), 1)
        effect.update(0.1, [step(0, 0.1)], 1, [target])
        self.assertEqual(effect.hits, [])
        self.assertEqual(effect.body_winds, [])
        effect.update(0.2, [step(0.1, 0.3)], 1, [target])
        self.assertEqual(effect.hits, [(1, 'body')])
        self.assertEqual(len(effect.body_winds), 1)
        effect.update(0.3, [step(0.3, 0.6)], 1)
        self.assertEqual(effect.body_winds, [])
        effect.update(0.1, [], 1)
        self.assertEqual(effect.body_winds, [])

    def test_fast_body_wind_sweeps_movement_without_closing_rear_gap(self):
        effect = self.make_effect()
        from ferrial_drive.combat.movement_combat import AttackStep
        move = AttackStep(1, 'combo_01/e', 0, 1, 1, 1, (0, 0), (200, 0))
        effect.update(1, [move], 1, [SwordTarget('between', Vec2(100, 20), 1),
                                   SwordTarget('rear', Vec2(-30, 0), 1)])
        self.assertEqual(effect.hits, [(1, 'between')])

    def test_target_radius_can_touch_rear_boundary(self):
        wind = body_wind_sector(Vec2(), 'e', self.make_effect().settings['body_wind'], 1)
        point = Vec2(cos(151 * pi / 180), sin(151 * pi / 180)) * 30
        self.assertTrue(any(moving_circle_touches_polygon(point, point, 3, triangle) for triangle in wind.triangles))

    def test_energy_increases_visible_wind_and_collision_together(self):
        settings = self.make_effect().settings['body_wind']
        settings['level_scales'] = [1, 1.25, 1.5]
        winds = [body_wind_sector(Vec2(), 'e', settings, level) for level in (1, 2, 3)]
        self.assertEqual([wind.radius_pixels for wind in winds], [40, 50, 60])
        self.assertEqual([wind.band_width_pixels for wind in winds], [18, 22.5, 27])
        target = Vec2(55, 0)
        hit = [any(moving_circle_touches_polygon(target, target, 0, triangle) for triangle in wind.triangles)
               for wind in winds]
        self.assertEqual(hit, [False, False, True])
        rear = Vec2(-25, 0)
        self.assertFalse(any(moving_circle_touches_polygon(rear, rear, 0, triangle)
                             for wind in winds for triangle in wind.triangles))
