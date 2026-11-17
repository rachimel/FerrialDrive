"""찌르기 중복 표시·연계 잔여물·카메라 투영이 접히는 구간을 검사한다."""

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from ferrial_drive.combat.geometry import Vec2
from ferrial_drive.combat.sword_effects import SwordSection
from ferrial_drive.rendering.sword_trail_geometry import sweep_runs
from ferrial_drive.rendering.pico_sword_effects import PicoSwordEffects


def section(a, b, time=0.01, *, strike=1, chevron=()):
    return SwordSection((), Vec2(), Vec2(*a), Vec2(), Vec2(*b), time, 0.4, strike, 1, (), chevron)


class SwordTrailContinuityTests(unittest.TestCase):
    def test_near_parallel_and_reversed_blade_do_not_bridge_sweep_runs(self):
        valid = section((100, 0), (100, 20))
        edge_on = section((100, 20), (110, 22), 0.02)
        reversed_blade = section((110, 22), (-100, -20), 0.03)
        next_sweep = section((-100, -20), (-100, -40), 0.04)
        runs = sweep_runs([valid, edge_on, reversed_blade, next_sweep])
        self.assertEqual(runs, [[valid], [next_sweep]])

    def test_tiny_degenerate_sweep_is_not_a_floating_fragment(self):
        rows = [section((100, 0), (100, 1))]
        self.assertEqual(sweep_runs(rows), [])

    def draw(self, rows, now=0.04):
        import pico2d.pico2d as pico
        geometries = []
        def geometry(renderer, texture, vertices, count, indices, index_count):
            geometries.append([(vertices[i].position.x, vertices[i].position.y,
                                vertices[i].tex_coord.x, vertices[i].tex_coord.y) for i in range(count)])
            return 0
        fake = SimpleNamespace(SDL_Vertex=pico.SDL_Vertex, SDL_FPoint=pico.SDL_FPoint,
                               SDL_Color=pico.SDL_Color, SDL_RenderGeometry=geometry, renderer=None)
        painter = PicoSwordEffects(SimpleNamespace(pico=fake))
        painter.prepare_flow = Mock()
        effect = SimpleNamespace(sections=rows, time_seconds=now, settings={},
                                 profiles=[{'color':'#2855E8','reach_scale':2.4,'trail_opacity':0.5}],
                                 opacity=lambda item:1)
        painter.draw_trail(effect, SimpleNamespace(world_to_screen=lambda point:point), '#2855E8')
        return geometries

    def thrusts(self):
        wings = (Vec2(-30, -20), Vec2(0, 0), Vec2(-30, 20))
        return [section((10, 0), (20, 0), time, chevron=wings) for time in (0.01, 0.02, 0.03)]

    def test_thrust_is_one_connected_shape_with_texture_continuous_at_tip(self):
        geometries = self.draw(self.thrusts())
        self.assertEqual([len(mesh) for mesh in geometries], [8, 8])
        for mesh in geometries:
            self.assertEqual(mesh[2], mesh[5])
            self.assertEqual(mesh[3], mesh[4])
            self.assertEqual(mesh[2][2], 0.5)

    def test_next_strike_fades_thrust_even_when_new_sweep_is_edge_on(self):
        next_strike = section((100, 0), (110, 0), 0.04, strike=2)
        self.assertEqual(self.draw(self.thrusts() + [next_strike], now=0.2), [])
