"""총 강철 불꽃의 재질·상한·수명과 레벨별 Trail 색상 전송을 확인한다."""

import os
import unittest
from ctypes import byref, c_int, c_ubyte
from unittest.mock import patch

from ferrial_drive.combat.gun_contact import GunContactEffects
from ferrial_drive.combat.geometry import Vec2
from ferrial_drive.combat.ranged_combat import RangedCombat
from ferrial_drive.combat.camera import LookAheadCamera
from ferrial_drive.rendering.canvas import PicoCanvas
from ferrial_drive.rendering.pico_gun_effects import PicoGunEffects
from ferrial_drive.ui.pico_renderer import PicoRenderer


class GunFeedbackTests(unittest.TestCase):
    def test_explosions_shrink_without_stale_vertices_and_restore_blend_on_failure(self):
        import pico2d.pico2d as pico

        with patch.dict(os.environ, SDL_VIDEODRIVER='dummy'), PicoCanvas(128, 128, '폭발 배치 수명'):
            renderer = PicoRenderer({}, {})
            effects = PicoGunEffects(renderer)
            try:
                camera = LookAheadCamera(128, 128)
                camera.reset((100, 80))
                camera.feedback_offset_pixels = (7, -3)
                camera.zoom_animation.start_value = camera.zoom_animation.end_value = .85
                contact = GunContactEffects()
                for index in range(24):
                    contact.emit(Vec2(100, 80), Vec2(1, 0), 'metal', seed=index)
                    contact.emit_explosion(Vec2(100, 80), (76.8, 24.6), seed=index)
                original = pico.SDL_RenderGeometry
                counts = []

                def submit(target, image, vertices, count, indices, index_count):
                    self.assertTrue(all(0 <= i < count for i in indices[:index_count]))
                    counts.append(count)
                    return original(target, image, vertices, count, indices, index_count)

                with patch.object(pico, 'SDL_RenderGeometry', side_effect=submit):
                    effects.draw_contacts(camera, contact, (80, 184, 242))
                    contact.reset()
                    contact.emit(Vec2(100, 80), Vec2(1, 0), 'generic')
                    effects.draw_contacts(camera, contact, (80, 184, 242))
                self.assertGreater(counts[0], counts[1])
                center = effects.contact_vertices[0].position
                self.assertAlmostEqual(center.x, 71)
                self.assertAlmostEqual(center.y, 61)
                pico.SDL_SetRenderDrawBlendMode(pico.renderer, pico.SDL_BLENDMODE_BLEND)
                with patch.object(pico, 'SDL_RenderGeometry', return_value=-1), self.assertRaises(RuntimeError):
                    effects.draw_contacts(camera, contact, (80, 184, 242))
                blend = c_int()
                pico.SDL_GetRenderDrawBlendMode(pico.renderer, byref(blend))
                self.assertEqual(blend.value, pico.SDL_BLENDMODE_BLEND)
                contact.update(1)
                with patch.object(pico, 'SDL_RenderGeometry') as draw:
                    effects.draw_contacts(camera, contact, (80, 184, 242))
                    draw.assert_not_called()
            finally:
                effects.close()
                renderer.close()

    def test_explosion_is_bounded_expires_and_renders_in_one_batch_without_texture_upload(self):
        import pico2d.pico2d as pico
        with patch.dict(os.environ, SDL_VIDEODRIVER='dummy'), PicoCanvas(192, 192, '국소 폭발 표시'):
            renderer = PicoRenderer({}, {})
            effects = PicoGunEffects(renderer)
            try:
                contact = GunContactEffects({'explosion': {'max_count': 2}})
                for seed in range(3):
                    contact.emit_explosion(Vec2(96, 96), (76.8, 24.64512), seed=seed)
                self.assertEqual(len(contact.explosions), 2)
                camera = LookAheadCamera(192, 192)
                camera.reset((96, 96))
                for seconds in (0, .04, .1):
                    contact.update(seconds)
                    with patch.object(pico, 'SDL_CreateTexture', side_effect=AssertionError('표시 중 생성')), \
                         patch.object(pico, 'SDL_UpdateTexture', side_effect=AssertionError('표시 중 업로드')), \
                         patch.object(pico, 'SDL_RenderGeometry', wraps=pico.SDL_RenderGeometry) as draw:
                        effects.draw(camera, (), contact=contact, color='#FF263D')
                        self.assertEqual(draw.call_count, 1)
                        self.assertIsNone(draw.call_args.args[1])
                        colors = [(v.color.r, v.color.g, v.color.b) for v in draw.call_args.args[2]]
                        self.assertIn((255, 38, 61), colors)
                contact.update(.3)
                self.assertFalse(contact.explosions)
                contact.emit_explosion(Vec2(), (10, 5))
                contact.reset()
                self.assertFalse(contact.explosions)
            finally:
                effects.close()
                renderer.close()

    def test_muzzle_flash_reuses_texture_follows_shot_and_expires(self):
        import pico2d.pico2d as pico

        with patch.dict(os.environ, SDL_VIDEODRIVER='dummy'), PicoCanvas(128, 128, '총구 화염 재사용'):
            renderer = PicoRenderer({}, {})
            effects = PicoGunEffects(renderer)
            try:
                camera = LookAheadCamera(128, 128)
                camera.reset((64, 64))
                camera.zoom_animation.start_value = camera.zoom_animation.end_value = .85
                gun, muzzle = RangedCombat(), Vec2(64, 64)
                with patch.object(pico, 'SDL_CreateTexture', side_effect=AssertionError('표시 중 텍스처 생성')), \
                     patch.object(pico, 'SDL_UpdateTexture', side_effect=AssertionError('표시 중 픽셀 전송')):
                    for direction in (Vec2(1, 0), Vec2(0, 1), Vec2(-1, 0), Vec2(0, -1), Vec2(1, 1)):
                        gun.reset()
                        gun.update(.01, muzzle, muzzle + direction * 1000, firing=True, aiming=True, max_shots=1)
                        renderer.clear('#000000')
                        with patch.object(pico, 'SDL_RenderGeometry', wraps=pico.SDL_RenderGeometry) as draw:
                            effects.draw(camera, (), active_gun=gun, muzzle=muzzle, color='#50B8F2')
                            self.assertEqual(draw.call_count, 1)
                            self.assertEqual(draw.call_args.args[1], effects.flash_texture)
                            vertices = draw.call_args.args[2]
                            a, b = vertices[0].position, vertices[1].position
                            delta = Vec2(b.x - a.x, b.y - a.y)
                            self.assertGreater(delta.x * gun.shot_direction.x + delta.y * gun.shot_direction.y, 0)
                            self.assertAlmostEqual(delta.length,
                                84 * effects.flash_size_scale * (1 - .3 * .01 / .045) * .85, places=4)
                            c = vertices[3].position
                            across = Vec2(c.x - a.x, c.y - a.y)
                            self.assertAlmostEqual(across.length,
                                90 * effects.flash_size_scale * (1 - .3 * .01 / .045) * .85, places=4)
                            self.assertAlmostEqual(across.x * gun.shot_direction.x
                                                   + across.y * gun.shot_direction.y, 0, places=4)
                            self.assertTrue(all((v.color.r, v.color.g, v.color.b) == (80, 184, 242)
                                                for v in vertices))
                        pixels = (c_ubyte * (128 * 128 * 4))()
                        self.assertEqual(pico.SDL_RenderReadPixels(pico.renderer, None,
                            pico.SDL_PIXELFORMAT_RGBA32, pixels, 128 * 4), 0)
                        self.assertGreater(sum(pixels[i] > 40 for i in range(0, len(pixels), 4)), 10)
                        gun.update(0, muzzle, muzzle + direction * 1000)
                        self.assertAlmostEqual(gun.shot_age_seconds, .01)
                        scale = effects.flash_size_scale
                        effects.draw(camera, (), active_gun=gun, muzzle=muzzle, color='#FF4044')
                        self.assertEqual(effects.flash_size_scale, scale)
                        gun.update(.04, muzzle, muzzle + direction * 1000)
                        with patch.object(pico, 'SDL_RenderGeometry') as draw:
                            effects.draw(camera, (), active_gun=gun, muzzle=muzzle)
                            draw.assert_not_called()
                    gun.reset()
                    gun.update(.001, muzzle, Vec2(1000, 64), firing=True)
                    scales = []
                    for _ in range(8):
                        gun.update(gun.interval_seconds, muzzle, Vec2(1000, 64), firing=True)
                        with patch.object(pico, 'SDL_RenderGeometry', wraps=pico.SDL_RenderGeometry) as draw:
                            effects.draw(camera, (), active_gun=gun, muzzle=muzzle, color='#FF4044')
                            self.assertTrue(all((v.color.r, v.color.g, v.color.b) == (255, 64, 68)
                                                for v in draw.call_args.args[2]))
                        scales.append(effects.flash_size_scale)
                    self.assertTrue(all(.8 <= scale <= 1.2 for scale in scales))
                    self.assertGreater(len(set(scales)), 1)
                    gun.reset()
                    gun.ammo = 0
                    gun.update(.01, muzzle, Vec2(1000, 64), firing=True)
                    with patch.object(pico, 'SDL_RenderGeometry') as draw:
                        effects.draw(camera, (), active_gun=gun, muzzle=muzzle)
                        draw.assert_not_called()
            finally:
                with patch.object(pico, 'SDL_DestroyTexture', wraps=pico.SDL_DestroyTexture) as destroy:
                    effects.close()
                    effects.close()
                    self.assertEqual(destroy.call_count, 2)
                renderer.close()

    def test_level_trail_length_grows_without_extending_behind_muzzle(self):
        import pico2d.pico2d as pico

        with patch.dict(os.environ, SDL_VIDEODRIVER='dummy'), PicoCanvas(512, 128, '레벨별 총탄 Trail'):
            renderer = PicoRenderer({}, {})
            effects = PicoGunEffects(renderer, {'length_pixels': 108})
            try:
                camera = LookAheadCamera(512, 128)
                camera.reset((256, 64))
                gun = RangedCombat()
                for seconds, expected in ((.3, (108, 135, 162)), (.01, (11, 11, 11))):
                    gun.reset()
                    gun.update(seconds, Vec2(20, 64), Vec2(1000, 64), firing=True, aiming=True, max_shots=1)
                    for level, length in enumerate(expected, 1):
                        lengths = []
                        original = pico.SDL_RenderGeometry
                        def submit(target, image, vertices, count, indices, index_count):
                            from math import hypot
                            a, b = vertices[0].position, vertices[1].position
                            lengths.append(hypot(b.x - a.x, b.y - a.y))
                            return original(target, image, vertices, count, indices, index_count)
                        with patch.object(pico, 'SDL_RenderGeometry', side_effect=submit):
                            effects.draw(camera, (gun,), energy_level=level)
                        self.assertAlmostEqual(lengths[0], length, places=4)
            finally:
                effects.close()
                renderer.close()

    def test_energy_impact_uses_actual_contact_on_every_material_and_expires(self):
        effect = GunContactEffects({'energy_impact': {'max_impacts': 2}})
        point = Vec2(37, 53)
        for material in ('generic', 'metal', 'steel'):
            effect.emit(point, Vec2(2, 0), material)
        self.assertEqual(len(effect.impacts), 2)
        self.assertTrue(all(impact.origin == point and impact.direction == Vec2(1, 0)
                            for impact in effect.impacts))
        self.assertEqual(len(effect.sparks), 8)
        effect.update(0)
        self.assertEqual(len(effect.impacts), 2)
        effect.update(.16)
        self.assertFalse(effect.impacts)
        effect.emit(point, Vec2(1, 0), 'generic')
        effect.reset()
        self.assertFalse(effect.impacts)
        self.assertFalse(effect.sparks)

    def test_sparks_are_metal_only_bounded_and_expire_without_new_hits(self):
        effect = GunContactEffects({'max_sparks': 9})
        effect.emit(Vec2(), Vec2(1, 0), 'generic')
        self.assertFalse(effect.sparks)
        for index in range(10):
            effect.emit(Vec2(), Vec2(1, 0), 'steel', seed=index)
        self.assertEqual(len(effect.sparks), 9)
        self.assertTrue(all(spark.velocity.x < 0 for spark in effect.sparks))
        effect.update(0)
        self.assertEqual(len(effect.sparks), 9)
        effect.update(.24)
        self.assertFalse(effect.sparks)
        effect.reset()
        self.assertEqual(effect.time_seconds, 0)

    def test_metal_sparks_remain_visible_on_ground_after_one_tenth_second(self):
        import pico2d.pico2d as pico
        from ferrial_drive.ui.components import Rect

        with patch.dict(os.environ, SDL_VIDEODRIVER='dummy'), PicoCanvas(192, 192, '금속 불똥 가시성'):
            renderer = PicoRenderer({}, {})
            effects = PicoGunEffects(renderer)
            try:
                contact = GunContactEffects()
                contact.emit(Vec2(120, 96), Vec2(1, 0), 'metal', seed=1)
                contact.impacts.clear()  # 금속 불똥의 가시성만 독립 확인한다.
                contact.update(.1)
                for zoom in (1, .85):
                    camera = LookAheadCamera(192, 192)
                    camera.reset((96, 96))
                    camera.zoom_animation.start_value = camera.zoom_animation.end_value = zoom
                    renderer.rect(Rect(0, 0, 192, 192), '#544C38')
                    pico.SDL_SetRenderDrawBlendMode(pico.renderer, pico.SDL_BLENDMODE_BLEND)
                    effects.draw(camera, (), contact=contact)
                    previous = c_int()
                    pico.SDL_GetRenderDrawBlendMode(pico.renderer, byref(previous))
                    self.assertEqual(previous.value, pico.SDL_BLENDMODE_BLEND)
                    pixels = (c_ubyte * (192 * 192 * 4))()
                    self.assertEqual(pico.SDL_RenderReadPixels(pico.renderer, None,
                        pico.SDL_PIXELFORMAT_RGBA32, pixels, 192 * 4), 0)
                    bright = sum(pixels[i] > 150 and pixels[i + 1] > 135 and pixels[i + 2] > 110
                                 for i in range(0, len(pixels), 4))
                    self.assertGreaterEqual(bright, 20, f'불똥 대비 부족: zoom={zoom}')
            finally:
                effects.close()
                renderer.close()

    def test_energy_flash_renders_current_energy_color_and_visible_pixels(self):
        import pico2d.pico2d as pico
        from ferrial_drive.ui.components import Rect

        with patch.dict(os.environ, SDL_VIDEODRIVER='dummy'), PicoCanvas(128, 128, '에너지 명중 확인'):
            renderer = PicoRenderer({}, {})
            effects = PicoGunEffects(renderer)
            try:
                camera = LookAheadCamera(128, 128)
                camera.reset((64, 64))
                for color in ('#50B8F2', '#78D0FF', '#A0E6FF', '#FF263D'):
                    contact = GunContactEffects()
                    contact.emit(Vec2(64, 64), Vec2(1, 0), 'generic')
                    contact.update(.04)
                    renderer.rect(Rect(0, 0, 128, 128), '#202020')
                    original, colors = pico.SDL_RenderGeometry, []
                    def submit(target, image, vertices, count, indices, index_count):
                        colors.extend((v.color.r, v.color.g, v.color.b) for v in vertices[:count])
                        return original(target, image, vertices, count, indices, index_count)
                    with patch.object(pico, 'SDL_RenderGeometry', side_effect=submit):
                        effects.draw(camera, (), contact=contact, color=color)
                    expected = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
                    self.assertIn(expected, colors)
                    self.assertNotIn((0, 255, 0), colors)
                    pixels = (c_ubyte * (128 * 128 * 4))()
                    self.assertEqual(pico.SDL_RenderReadPixels(pico.renderer, None,
                        pico.SDL_PIXELFORMAT_RGBA32, pixels, 128 * 4), 0)
                    self.assertGreater(sum(max(pixels[i:i + 3]) > 80
                        for i in range(0, len(pixels), 4)), 30)
            finally:
                effects.close()
                renderer.close()

    def test_energy_color_is_carried_by_vertices_without_rebaking_texture(self):
        import pico2d.pico2d as pico
        with patch.dict(os.environ, SDL_VIDEODRIVER='dummy'), PicoCanvas(128, 128, '총 피드백 확인'):
            renderer = PicoRenderer({}, {})
            effects = PicoGunEffects(renderer)
            try:
                camera = LookAheadCamera(128, 128)
                camera.reset((64, 64))
                gun = RangedCombat()
                gun.update(.01, Vec2(20, 64), Vec2(1000, 64), firing=True, max_shots=1)
                texture = effects.texture
                original = pico.SDL_RenderGeometry
                for color in ('#50B8F2', '#78D0FF', '#A0E6FF', '#FF263D'):
                    colors = []
                    def submit(target, image, vertices, count, indices, index_count):
                        colors.extend((vertex.color.r, vertex.color.g, vertex.color.b) for vertex in vertices[:count])
                        return original(target, image, vertices, count, indices, index_count)
                    with patch.object(pico, 'SDL_RenderGeometry', side_effect=submit):
                        effects.draw(camera, (gun,), color=color)
                    expected = tuple(int(color[index:index+2], 16) for index in (1, 3, 5))
                    self.assertTrue(colors)
                    self.assertTrue(all(value == expected for value in colors))
                    self.assertEqual(effects.texture, texture)
            finally:
                effects.close()
                renderer.close()


if __name__ == '__main__':
    unittest.main()
