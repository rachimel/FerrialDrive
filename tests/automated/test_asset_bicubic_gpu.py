"""FDRIVE_GPU_TESTS=1에서 숨긴 실제 OpenGL 창으로 Bicubic·클리핑·SDL 공존을 검사한다."""

from ctypes import byref, create_string_buffer
import ctypes as ct
import os
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ferrial_drive.assets import AssetCatalog, AssetDefinition, AssetManager
from ferrial_drive.assets.pico_assets import PicoAssetBackend
from ferrial_drive.assets.sprites import SpriteFrame, SpriteClip
from ferrial_drive.rendering import PicoCanvas
from samples.asset_loader.make_sample import write_png


@unittest.skipUnless(os.environ.get('FDRIVE_GPU_TESTS') == '1', '실제 GPU 검사는 명시적으로 실행한다.')
class AssetBicubicGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pico2d.pico2d as pico
        cls.pico = pico
        cls.previous_driver = os.environ.pop('SDL_VIDEODRIVER', None)
        if os.name == 'nt':
            os.environ['SDL_VIDEODRIVER'] = 'windows'
        create_window = pico.SDL_CreateWindow
        def hidden_window(title, x, y, width, height, flags):
            return create_window(title, x, y, width, height, (flags & ~pico.SDL_WINDOW_SHOWN) | pico.SDL_WINDOW_HIDDEN)
        cls.canvas = PicoCanvas(64, 64, 'FDrive Bicubic GPU check')
        with patch.object(pico, 'SDL_CreateWindow', side_effect=hidden_window):
            cls.canvas.open()
        if cls.canvas.info.name != 'opengl':
            cls.canvas.close()
            raise RuntimeError('실제 OpenGL 렌더러가 필요하다.')

    @classmethod
    def tearDownClass(cls):
        cls.canvas.close()
        os.environ.pop('SDL_VIDEODRIVER', None)
        if cls.previous_driver is not None:
            os.environ['SDL_VIDEODRIVER'] = cls.previous_driver

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='asset-bicubic-gpu-')
        self.root = Path(self.temporary.name)
        self.managers = []
        self.pico.SDL_SetRenderTarget(self.pico.renderer, None)
        self.pico.SDL_RenderSetViewport(self.pico.renderer, None)
        self.pico.SDL_RenderSetScale(self.pico.renderer, 1, 1)
        self.pico.SDL_RenderSetClipRect(self.pico.renderer, None)
        self.clear()

    def tearDown(self):
        for manager in self.managers:
            manager.close()
        self.temporary.cleanup()

    def clear(self):
        self.pico.SDL_SetRenderDrawColor(self.pico.renderer, 0, 0, 0, 255)
        self.pico.SDL_RenderClear(self.pico.renderer)

    def resource(self, width, height, pixel):
        path = self.root / f'{len(self.managers)}.png'
        write_png(path, width, height, pixel)
        manager = AssetManager(AssetCatalog([AssetDefinition('gpu', 'image', path)]), PicoAssetBackend())
        self.managers.append(manager)
        resource = manager.acquire('gpu').resource
        self.assertEqual(resource.filtering, 'bicubic')
        return resource

    def pixels(self):
        data = create_string_buffer(64 * 64 * 4)
        self.assertEqual(self.pico.SDL_RenderReadPixels(self.pico.renderer, None, self.pico.SDL_PIXELFORMAT_RGBA32, data, 64 * 4), 0)
        return data.raw

    def at(self, data, x, y):
        return tuple(data[(y * 64 + x) * 4:(y * 64 + x) * 4 + 4])

    def test_part_upscale_preserves_pixels_and_sdl_clip_with_batched_gl_state(self):
        from contextlib import ExitStack

        from ferrial_drive.rendering.gl_pass import SdlOpenGLPass
        from ferrial_drive.rendering.part_upscale import PartUpscaler

        p = self.pico
        batch = SdlOpenGLPass.batch
        clip = p.SDL_Rect(14, 12, 29, 25)
        destination = p.SDL_Rect(8, 7, 42, 38)
        for mode, expected in (("off", 4), ("smaa", 19)):
            with self.subTest(mode=mode), ExitStack() as cleanup:
                upscaler = PartUpscaler(p, mode)
                cleanup.callback(upscaler.close)
                with upscaler.native_target(8, 8):
                    p.SDL_SetRenderDrawColor(p.renderer, 120, 62, 30, 180)
                    p.SDL_RenderFillRect(p.renderer, p.SDL_Rect(1, 1, 6, 5))
                    p.SDL_SetRenderDrawColor(p.renderer, 32, 95, 170, 215)
                    p.SDL_RenderFillRect(p.renderer, p.SDL_Rect(3, 3, 4, 4))

                def draw():
                    self.clear()
                    p.SDL_RenderSetScale(p.renderer, 1.1, 0.9)
                    p.SDL_RenderSetClipRect(p.renderer, byref(clip))
                    try:
                        upscaler.draw(8, 8, destination)
                        active_clip = p.SDL_Rect()
                        p.SDL_RenderGetClipRect(p.renderer, byref(active_clip))
                        self.assertEqual((active_clip.x, active_clip.y, active_clip.w, active_clip.h),
                                         (clip.x, clip.y, clip.w, clip.h))
                        return self.pixels()
                    finally:
                        p.SDL_RenderSetClipRect(p.renderer, None)
                        p.SDL_RenderSetScale(p.renderer, 1, 1)

                with patch.object(SdlOpenGLPass, "batch", lambda sampler, **_: batch(sampler)):
                    reference = draw()
                self.assertGreater(len(set(reference)), 5)
                programs = [upscaler.sampler, *(upscaler.aa.programs if upscaler.aa else ())]
                queries = [cleanup.enter_context(patch.object(sampler, "glGetIntegerv", wraps=sampler.glGetIntegerv))
                           for sampler in programs]
                self.assertEqual(reference, draw())
                self.assertEqual(sum(query.call_count for query in queries), expected)

    def test_identity_preserves_rgb_and_shared_sampler_lifetime(self):
        pixel = lambda x, y: (x * 30, y * 30, (x + y) * 15, 255)
        resource = self.resource(8, 8, pixel)
        second = self.resource(8, 8, pixel)
        self.assertIs(resource.sampler, second.sampler)
        resource.draw_frame(SpriteFrame((0, 0, 8, 8), (0, 0)), 8, 48, shadow=False)
        data = self.pixels()
        for y in range(8):
            for x in range(8):
                self.assertEqual(self.at(data, 8 + x, 8 + y), pixel(x, y))

    def test_ground_friction_uses_top_left_crop_and_foreground(self):
        from ferrial_drive.combat.ground_effects import GroundParticle
        from ferrial_drive.rendering.pico_ground_effects import PicoGroundEffects

        write_png(self.root / "scrape.png", 16, 16,
                  lambda x, y: (255, 0, 0, 255) if y < 4 else (0, 0, 255, 255))
        atlas = self.root / "atlas.json"
        atlas.write_text(json.dumps({"assets": {"scrape_gray": {
            "file": "scrape.png", "size_px": [16, 16],
            "variants": [{"source_rect_top_left_px": [0, 0, 8, 4]}]}}}), encoding="utf-8")
        effect = PicoGroundEffects(self.pico, atlas)
        self.managers.append(effect)
        particle = GroundParticle("foot_friction", (32, 32), (0, 0), (24, 12), 0, 1, 0,
                                  detail=1, growth=0)
        state = SimpleNamespace(particles=[particle], reverse_motion=False, emitter_origins={}, near_front_pixels=12)
        camera = SimpleNamespace(world_to_screen=lambda point: point)
        effect.draw(state, camera, foreground=False)
        self.assertEqual(self.at(self.pixels(), 32, 32)[:3], (0, 0, 0))
        effect.draw(state, camera, foreground=True)
        self.assertEqual(self.at(self.pixels(), 32, 32)[:3], (255, 0, 0))

    def test_ground_friction_mirror_keeps_top_and_bottom(self):
        from ferrial_drive.combat.ground_effects import GroundParticle
        from ferrial_drive.rendering.pico_ground_effects import PicoGroundEffects

        colors = ((255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255))
        write_png(self.root / "asymmetric.png", 16, 16,
                  lambda x, y: colors[(2 if y >= 4 else 0) + (1 if x >= 4 else 0)])
        atlas = self.root / "asymmetric.json"
        atlas.write_text(json.dumps({"assets": {"scrape_gray": {
            "file": "asymmetric.png", "size_px": [16, 16],
            "variants": [{"source_rect_top_left_px": [0, 0, 8, 8]}]}}}), encoding="utf-8")
        effect = PicoGroundEffects(self.pico, atlas)
        self.managers.append(effect)
        particle = GroundParticle("foot_friction", (32, 32), (0, 0), (32, 32), 0, 1, 0,
                                  detail=1, growth=0)
        state = SimpleNamespace(particles=[particle], reverse_motion=False, emitter_origins={}, near_front_pixels=12)
        camera = SimpleNamespace(world_to_screen=lambda point: point)
        for mirrored in (False, True):
            particle.mirror_x = mirrored
            self.clear()
            effect.draw(state, camera, foreground=True)
            pixels = self.pixels()
            for index, (x, y) in enumerate(((24, 24), (40, 24), (24, 40), (40, 40))):
                self.assertEqual(self.at(pixels, x, y)[:3], colors[index ^ int(mirrored)][:3])

    def test_shared_atlas_echo_opacity_does_not_dim_next_body(self):
        from ferrial_drive.rendering.pico_motion_atlas import AtlasPainter
        color = self.resource(8, 8, lambda x, y: (200, 100, 50, 255))
        flow = self.resource(8, 8, lambda x, y: (128, 0, 128, 0))
        painter = AtlasPainter(self.pico)
        self.managers.append(painter)
        def bind(texture):
            x, y = ct.c_float(), ct.c_float()
            self.assertEqual(self.pico.SDL_GL_BindTexture(texture, byref(x), byref(y)), 0)
        resource = SimpleNamespace(data={"clips": {"attack": {
            "pairs": [[0, 0, 0, 0]], "size": [8, 8], "interval_seconds": 1}},
            "frames": {kind: [{"page": 0, "rect": [0, 0, 8, 8]}] for kind in ("color", "vector")}},
            pages={"color": [{"texture": color.textures["body"], "size": [8, 8]}],
                   "vector": [{"texture": flow.textures["body"], "size": [8, 8]}]},
            cache=SimpleNamespace(_bind=bind))
        for opacity in (0.25, 1):
            self.clear()
            painter.draw(resource, "attack", 0.5, self.pico.SDL_Rect(16, 16, 32, 32), opacity=opacity)
            actual = self.at(self.pixels(), 32, 32)
            for channel, expected in zip(actual[:3], (200, 100, 50)):
                self.assertAlmostEqual(channel, expected * opacity, delta=1)
        self.clear()
        painter.draw(resource, "attack", 0.5, self.pico.SDL_Rect(16, 16, 32, 32), opacity=0.25,
                     tint=(0, 1, 1), tint_mix=1)
        actual = self.at(self.pixels(), 32, 32)
        luminance = 200 * 0.299 + 100 * 0.587 + 50 * 0.114
        self.assertEqual(actual[0], 0)
        self.assertAlmostEqual(actual[1], luminance * 0.25, delta=1)
        self.assertAlmostEqual(actual[2], luminance * 0.25, delta=1)
        self.clear()
        painter.draw(resource, "attack", 0.5, self.pico.SDL_Rect(16, 16, 32, 32))
        self.assertEqual(self.at(self.pixels(), 32, 32)[:3], (200, 100, 50))

    def test_training_crop_matches_full_frame_pixels(self):
        from ferrial_drive.combat.movement_application import MovementApplication
        from ferrial_drive.rendering.pico_interpolation import read_rgba_image
        self.resource(8, 8, lambda x, y: (200, 100, 50, 255)).draw_frame(
            SpriteFrame((0, 0, 8, 8), (0, 0)), 8, 48)
        app = object.__new__(MovementApplication)
        app.pico, app.window_size = self.pico, (64, 64)
        path = self.root / "crop.png"
        app.capture(path, self.pico.SDL_Rect(8, 8, 8, 8))
        width, height, pixels = read_rgba_image(self.pico, path)
        self.assertEqual((width, height), (8, 8))
        self.assertEqual(pixels, bytes((200, 100, 50, 255)) * 64)

    def test_energy_tint_restores_shared_texture_color_after_exception(self):
        from ferrial_drive.assets.pico_opacity import texture_tint
        texture = self.resource(8, 8, lambda x, y: (200, 100, 50, 255)).textures["body"]
        def color():
            channels = [ct.c_ubyte() for _ in range(3)]
            self.pico.SDL_GetTextureColorMod(texture, *(byref(v) for v in channels))
            return tuple(v.value for v in channels)
        with self.assertRaisesRegex(RuntimeError, "검증 중단"):
            with texture_tint(self.pico, (texture, texture), (0, 1, 1), 0.5):
                self.assertEqual(color(), (128, 255, 255))
                raise RuntimeError("검증 중단")
        self.assertEqual(color(), (255, 255, 255))

    def test_shadow_cross_sheet_crop_and_pivot_keep_the_same_screen_position(self):
        from ferrial_drive.rendering.pico_shadow_blend import PicoShadowBlend
        a = self.resource(8, 8, lambda x, y: (0, 0, 0, 255 if 2 <= x < 4 and 2 <= y < 4 else 0))
        b = self.resource(12, 10, lambda x, y: (0, 0, 0, 255 if 6 <= x < 8 and 4 <= y < 6 else 0))
        def shadow(resource, name, size, pivot):
            return SimpleNamespace(textures={'shadow': resource.textures['body']}, sizes={'shadow': size},
                target_rect=resource.target_rect, mech=SimpleNamespace(rows={name: {'source_clip': name}},
                sheets={'shadow': SimpleNamespace(clips={name: SpriteClip(12, (SpriteFrame((0, 0, *size), pivot),))})}))
        current = shadow(a, 'transition', (8, 8), (4, 4))
        following = shadow(b, 'loop', (12, 10), (8, 4))
        renderer = PicoShadowBlend(self.pico)
        try:
            for phase in (0, 0.5, 1):
                self.pico.SDL_SetRenderDrawColor(self.pico.renderer, 255, 255, 255, 255)
                self.pico.SDL_RenderClear(self.pico.renderer)
                renderer.draw(current, 'transition', phase, 32, 32, scale=1, opacity=1,
                              endpoint='loop', endpoint_resource=following, loop=False)
                pixels = self.pixels()
                for y in range(26, 38):
                    for x in range(24, 38):
                        expected = 0 if 30 <= x < 32 and 30 <= y < 32 else 255
                        self.assertAlmostEqual(self.at(pixels, x, y)[0], expected, delta=1)
        finally:
            renderer.close()

    def ground_renderer(self):
        from ferrial_drive.rendering.pico_ground_effects import PicoGroundEffects
        write_png(self.root / 'puff.png', 8, 8, lambda x, y: (180, 180, 180, 255))
        row = {'file': 'puff.png', 'size_px': [8, 8], 'variants': [
            {'source_rect_top_left_px': [0, 0, 8, 8]} for _ in range(4)]}
        path = self.root / 'ground.json'
        path.write_text(json.dumps({'assets': {'smoke_gray': row, 'scrape_gray': row}}), encoding='utf-8')
        return PicoGroundEffects(self.pico, path)

    def test_half_alpha_keeps_geometry_and_soft_shadow_does_not_bleed_neighbour_frame(self):
        from ferrial_drive.assets.alpha_data import prepare_alpha_data
        from ferrial_drive.assets.catalog import read_document
        from ferrial_drive.rendering.pico_shadow_blend import PicoShadowBlend

        original = self.resource(32, 16, lambda x, y: (0, 0, 0,
            255 if x >= 16 or (4 <= x < 12 and 4 <= y < 12) else 0))
        source = original.definition.source
        prepare_alpha_data(source, scale=0.5)
        half = PicoAssetBackend(alpha_layers=("body",)).load(read_document(AssetDefinition("half", "image", source)))
        self.managers.append(half)
        self.assertEqual(half.sizes["body"], (32, 16))
        self.assertEqual(half.estimated_bytes, 16 * 8)
        width, height = ct.c_int(), ct.c_int()
        self.pico.SDL_QueryTexture(half.textures["body"], None, None, byref(width), byref(height))
        self.assertEqual((width.value, height.value), (16, 8))
        frame = SpriteFrame((0, 0, 16, 16), (8, 8))
        resource = SimpleNamespace(textures={"shadow": half.textures["body"]}, sizes={"shadow": (32, 16)},
            target_rect=half.target_rect, mech=SimpleNamespace(rows={"idle": {"source_clip": "idle"}},
                sheets={"shadow": SimpleNamespace(clips={"idle": SpriteClip(12, (frame,))})}))
        hard = PicoShadowBlend(self.pico)
        soft = PicoShadowBlend(self.pico, softness_pixels=4, contact_radius_pixels=1)
        self.managers.extend((hard, soft))
        images = []
        for renderer in (hard, soft):
            self.pico.SDL_SetRenderDrawColor(self.pico.renderer, 255, 255, 255, 255)
            self.pico.SDL_RenderClear(self.pico.renderer)
            renderer.draw(resource, "idle", 0, 32, 32, scale=1, opacity=1)
            images.append(self.pixels())
        self.assertEqual(self.at(images[0], 37, 32)[0], 255)
        self.assertLess(self.at(images[1], 37, 32)[0], 255)
        self.assertLess(self.at(images[1], 32, 32)[0], 64)
        self.assertEqual(self.at(images[1], 43, 32)[0], 255)

    def test_bilinear_half_shadow_does_not_blend_across_odd_frame_edge(self):
        from ferrial_drive.assets.alpha_data import prepare_alpha_data
        from ferrial_drive.assets.catalog import read_document
        from ferrial_drive.rendering.pico_shadow_blend import PicoShadowBlend
        original = self.resource(32,16,lambda x,y:(0,0,0,255 if x>=15 or (4<=x<12 and 4<=y<12) else 0))
        source = original.definition.source
        prepare_alpha_data(source,scale=.5)
        half = PicoAssetBackend(alpha_layers=("body",)).load(read_document(AssetDefinition("half_odd","image",source)))
        self.managers.append(half)
        frame = SpriteFrame((0,0,15,16),(8,8))
        resource = SimpleNamespace(textures={"shadow":half.textures["body"]},sizes={"shadow":(32,16)},
            target_rect=half.target_rect,mech=SimpleNamespace(rows={"idle":{"source_clip":"idle"}},
                sheets={"shadow":SimpleNamespace(clips={"idle":SpriteClip(12,(frame,))})}))
        soft = PicoShadowBlend(self.pico,softness_pixels=4,contact_radius_pixels=1)
        self.managers.append(soft)
        self.pico.SDL_SetRenderDrawColor(self.pico.renderer,255,255,255,255)
        self.pico.SDL_RenderClear(self.pico.renderer)
        soft.draw(resource,"idle",0,32,32,scale=1,opacity=1)
        pixels = self.pixels()
        self.assertLess(self.at(pixels,32,32)[0],64)
        self.assertEqual(self.at(pixels,42,32)[0],255)

    def test_reverse_effect_draws_near_nozzle_in_front_and_far_tail_behind_body(self):
        from ferrial_drive.combat.ground_effects import GroundParticle
        renderer = self.ground_renderer()
        particle = GroundParticle('trail', (32, 32), (0, 0), (48, 8), 0, 1, 0, '#00FF00', emitter='calf_l')
        effects = SimpleNamespace(particles=[particle], reverse_motion=True, near_front_pixels=8,
                                  emitter_origins={'calf_l': (56, 32)})
        camera = SimpleNamespace(world_to_screen=lambda point: point)
        try:
            renderer.draw(effects, camera)
            self.pico.SDL_SetRenderDrawColor(self.pico.renderer, 255, 0, 0, 255)
            body = self.pico.SDL_Rect(0, 26, 64, 12)
            self.pico.SDL_RenderFillRect(self.pico.renderer, byref(body))
            renderer.draw(effects, camera, foreground=True)
            pixels = self.pixels()
            self.assertEqual(self.at(pixels, 36, 32)[:3], (255, 0, 0))
            self.assertGreater(self.at(pixels, 52, 32)[1], 100)
        finally:
            renderer.close()

    def test_round_smoke_grows_and_fades_with_age(self):
        from ferrial_drive.combat.ground_effects import GroundParticle
        renderer = self.ground_renderer()
        particle = GroundParticle('thruster_smoke', (32, 32), (0, 0), (12, 12), 0, 1, 0,
                                  opacity=0.8, roundness=1, growth=2)
        effects = SimpleNamespace(particles=[particle], reverse_motion=False, near_front_pixels=8, emitter_origins={})
        camera = SimpleNamespace(world_to_screen=lambda point: point)
        try:
            renderer.draw(effects, camera, foreground=True, trail_in_front=True)
            initial = self.pixels()
            self.clear()
            particle.age_seconds = 0.5
            renderer.draw(effects, camera, foreground=True, trail_in_front=True)
            later = self.pixels()
            self.assertEqual(self.at(initial, 23, 32)[0], 0)
            self.assertGreater(self.at(later, 23, 32)[0], 0)
            self.assertLess(self.at(later, 32, 32)[0], self.at(initial, 32, 32)[0])
        finally:
            renderer.close()

    def test_alpha_shadow_upload_ignores_previous_image_row_stride(self):
        from ferrial_drive.rendering.pico_alpha_texture import load_alpha_texture
        from ferrial_drive.diagnostics.texture_metrics import bind_gl
        resource = self.resource(1, 1, lambda x, y: (255, 255, 255, 255))
        sampler = resource.sampler
        store = bind_gl(self.pico, 'glPixelStorei', None, [ct.c_uint, ct.c_int])
        path = self.root / 'alpha.png'
        write_png(path, 8, 8, lambda x, y: (0, 0, 0, 255 if (x, y) == (3, 4) else 0))
        previous = sampler.integer(0x0CF2)
        texture = None
        try:
            store(0x0CF2, 4)
            texture = load_alpha_texture(self.pico, path, sampler)
            self.assertEqual(sampler.integer(0x0CF2), 4)
            self.pico.SDL_SetRenderDrawColor(self.pico.renderer, 255, 255, 255, 255)
            self.pico.SDL_RenderClear(self.pico.renderer)
            sampler.draw(texture, (8, 8), self.pico.SDL_Rect(0, 0, 8, 8), self.pico.SDL_Rect(8, 8, 8, 8))
            pixels = self.pixels()
            for y in range(8):
                for x in range(8):
                    self.assertEqual(self.at(pixels, 8 + x, 8 + y)[0], 0 if (x, y) == (3, 4) else 255)
        finally:
            store(0x0CF2, previous)
            if texture:
                self.pico.SDL_DestroyTexture(texture)

    def test_trail_echo_shrinks_in_length_and_width_with_age(self):
        from ferrial_drive.combat.ground_effects import GroundParticle
        renderer = self.ground_renderer()
        particle = GroundParticle('trail_echo', (32, 32), (0, 0), (32, 12), 0, 1, 0,
                                  '#00FF00', growth=-0.65)
        effects = SimpleNamespace(particles=[particle], reverse_motion=False, near_front_pixels=8, emitter_origins={})
        camera = SimpleNamespace(world_to_screen=lambda point: point)
        try:
            renderer.draw(effects, camera)
            initial = self.pixels()
            self.clear()
            particle.age_seconds = 0.5
            renderer.draw(effects, camera)
            later = self.pixels()
            self.assertGreater(self.at(initial, 20, 32)[1], 0)
            self.assertEqual(self.at(later, 20, 32)[1], 0)
            self.assertGreater(self.at(initial, 32, 37)[1], 0)
            self.assertEqual(self.at(later, 32, 37)[1], 0)
        finally:
            renderer.close()

    def test_magnification_is_bicubic_instead_of_linear(self):
        pixel = lambda x, y: (255 if x >= 4 else 0, 64, 0, 255)
        resource = self.resource(8, 8, pixel)
        frame = SpriteFrame((0, 0, 8, 8), (0, 0))
        resource.draw_frame(frame, 8, 24, scale=4, shadow=False)
        cubic = self.pixels()
        self.clear()
        resource.set_filtering('linear')
        resource.draw_frame(frame, 8, 24, scale=4, shadow=False)
        linear = self.pixels()
        self.assertNotEqual(self.at(cubic, 22, 28)[0], self.at(linear, 22, 28)[0])
        # 출력 x=22는 원본 x=3.125에 대응하며 Catmull-Rom 가중치는 0.083984375다.
        self.assertAlmostEqual(self.at(cubic, 22, 28)[0], 255 * 0.083984375, delta=2)

    def test_atlas_neighbour_and_transparent_rgb_do_not_bleed(self):
        resource = self.resource(16, 8, lambda x, y: (255, 0, 0, 255) if x < 8 else (0, 255, 0, 255))
        resource.draw_frame(SpriteFrame((0, 0, 8, 8), (0, 0)), 8, 24, scale=4, shadow=False)
        data = self.pixels()
        self.assertEqual(self.at(data, 39, 28)[:3], (255, 0, 0))
        self.clear()
        transparent = self.resource(8, 8, lambda x, y: (0, 255, 0, 255) if 2 <= x <= 5 and 2 <= y <= 5 else (255, 0, 255, 0))
        transparent.draw_frame(SpriteFrame((0, 0, 8, 8), (0, 0)), 8, 24, scale=4, shadow=False)
        data = self.pixels()
        for x in range(8, 40):
            color = self.at(data, x, 28)
            self.assertEqual((color[0], color[2]), (0, 0))

    def test_clipping_and_subsequent_sdl_draw_remain_correct(self):
        resource = self.resource(8, 8, lambda x, y: (255, 0, 0, 255))
        clip = self.pico.SDL_Rect(12, 14, 8, 8)
        self.pico.SDL_RenderSetClipRect(self.pico.renderer, byref(clip))
        resource.draw_frame(SpriteFrame((0, 0, 8, 8), (0, 0)), 8, 24, scale=4, shadow=False)
        self.pico.SDL_RenderSetClipRect(self.pico.renderer, None)
        self.pico.SDL_SetRenderDrawColor(self.pico.renderer, 0, 255, 0, 255)
        box = self.pico.SDL_Rect(48, 48, 4, 4)
        self.pico.SDL_RenderFillRect(self.pico.renderer, byref(box))
        data = self.pixels()
        self.assertEqual(self.at(data, 14, 16)[:3], (255, 0, 0))
        self.assertEqual(self.at(data, 10, 16)[:3], (0, 0, 0))
        self.assertEqual(self.at(data, 49, 49)[:3], (0, 255, 0))

    def test_render_target_uses_matching_sdl_orientation(self):
        target = self.pico.SDL_CreateTexture(self.pico.renderer, self.pico.SDL_PIXELFORMAT_RGBA8888,
                                            self.pico.SDL_TEXTUREACCESS_TARGET, 64, 64)
        try:
            self.assertEqual(self.pico.SDL_SetRenderTarget(self.pico.renderer, target), 0)
            self.clear()
            resource = self.resource(8, 8, lambda x, y: (y * 30, 0, 0, 255))
            resource.draw_frame(SpriteFrame((0, 0, 8, 8), (0, 0)), 8, 48, shadow=False)
            data = self.pixels()
            self.assertEqual(self.at(data, 8, 8)[0], 0)
            self.assertEqual(self.at(data, 8, 15)[0], 210)
        finally:
            self.pico.SDL_SetRenderTarget(self.pico.renderer, None)
            self.pico.SDL_DestroyTexture(target)

    def test_viewport_scale_clip_matches_the_sdl_coordinate_system(self):
        resource = self.resource(8, 8, lambda x, y: (255, 0, 0, 255))
        viewport, clip = self.pico.SDL_Rect(8, 10, 48, 40), self.pico.SDL_Rect(1, 1, 8, 8)
        self.pico.SDL_RenderSetViewport(self.pico.renderer, byref(viewport))
        self.pico.SDL_RenderSetScale(self.pico.renderer, 1.5, 2)
        self.pico.SDL_RenderSetClipRect(self.pico.renderer, byref(clip))
        source, target = self.pico.SDL_Rect(0, 0, 8, 8), self.pico.SDL_Rect(0, 0, 12, 12)
        resource.sampler.draw(resource.textures['body'], (8, 8), source, target)
        cubic = self.pixels()
        self.clear()
        self.pico.SDL_RenderCopy(self.pico.renderer, resource.textures['body'], byref(source), byref(target))
        self.assertEqual(self.pixels(), cubic)


if __name__ == '__main__':
    unittest.main()
