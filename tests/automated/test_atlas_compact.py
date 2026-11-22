"""해상도 유지·그림자 복원·에너지 RGB 보존·실제 GL 저장 형식을 확인한다."""

import ctypes as ct
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zlib

from ferrial_drive.rendering.atlas_compact import compact_variant, compact_energy_variant, read_document, verify_variant
from ferrial_drive.rendering.atlas_texture_cache import AtlasTextureBindings, bind_atlas_textures
from ferrial_drive.rendering.motion_atlas import AtlasItem, pack_items
from ferrial_drive.rendering.texture_codecs import texture_payload_size, unpack_payload


class AtlasBindingTests(unittest.TestCase):
    def test_outer_pass_can_restore_unit_zero_without_reading_it_again(self):
        from unittest.mock import Mock, call

        sampler = Mock()
        sampler.integer.return_value = 42
        sampler.texture_stack_covers.return_value = False
        entries = [{"gl_texture": 5}, {"gl_texture": 6}]
        with bind_atlas_textures(sampler, None, entries, restore_unit_zero=False):
            sampler.integer.assert_called_once_with(0x8069)
        self.assertEqual(sampler.glBindTexture.call_args_list,
                         [call(0x0DE1, 5), call(0x0DE1, 6), call(0x0DE1, 42)])
        self.assertEqual(sampler.glActiveTexture.call_args, call(0x84C0))

    def test_texture_stack_probe_restores_uncovered_units_and_uses_cached_result(self):
        from ferrial_drive.rendering.gl_pass import SdlOpenGLPass, TEXTURE_STATE

        for covered in (2, 4):
            with self.subTest(covered_units=covered):
                sampler = SdlOpenGLPass.__new__(SdlOpenGLPass)
                sampler._texture_stack_units = None
                bound, active, stack, probes = [41, 42, 43, 44], 0, [], []

                def activate(texture):
                    nonlocal active
                    active = texture - 0x84C0

                def integer(name):
                    if name == 0x8872:
                        probes.append(name)
                        return len(bound)
                    return bound[active]

                def bind(target, name):
                    bound[active] = name

                def push(mask):
                    self.assertEqual(mask, TEXTURE_STATE)
                    stack.append((active, bound[:covered]))

                def pop():
                    nonlocal active
                    active, saved = stack.pop()
                    bound[:covered] = saved

                sampler.integer = integer
                sampler.glActiveTexture = activate
                sampler.glBindTexture = bind
                sampler._push_attrib = push
                sampler._pop_attrib = pop

                self.assertEqual(sampler.texture_stack_covers(3, 5), covered >= 3)
                self.assertEqual(bound, [41, 42, 43, 44])
                self.assertEqual(active, 0)
                with self.assertRaisesRegex(RuntimeError, "그리기 실패"):
                    with bind_atlas_textures(sampler, None, [{"gl_texture": name} for name in (5, 6, 7)],
                                             restore_unit_zero=False):
                        self.assertEqual(bound, [5, 6, 7, 44])
                        raise RuntimeError("그리기 실패")
                self.assertEqual(bound, [41 if covered >= 3 else 5, 42, 43, 44])
                self.assertFalse(stack)
                self.assertEqual(active, 0)
                self.assertEqual(probes, [0x8872])

    def test_queries_each_unit_target_once_and_restores_after_failure(self):
        class Sampler:
            def __init__(self):
                self.unit = 0
                self.bound = {(0, 0x0DE1): 41, (1, 0x0DE1): 42, (1, 0x8C2A): 43}
                self.queries = []
                self.binds = []

            def glActiveTexture(self, texture):
                self.unit = texture - 0x84C0

            def integer(self, binding):
                self.queries.append((self.unit, binding))
                return self.bound[self.unit, {0x8069: 0x0DE1, 0x8C2C: 0x8C2A}[binding]]

            def glBindTexture(self, target, name):
                self.binds.append((self.unit, target, name))
                self.bound[self.unit, target] = name

        sampler = Sampler()
        original = sampler.bound.copy()
        with self.assertRaisesRegex(RuntimeError, "그리기 실패"):
            with AtlasTextureBindings(sampler) as bindings:
                first = [{"gl_texture": 5}, {"texture": object(), "gl_name": 6}]
                with bind_atlas_textures(sampler, None, first, bindings):
                    self.assertEqual(sampler.bound[1, 0x0DE1], 6)
                with bind_atlas_textures(sampler, None, first, bindings):
                    self.assertEqual(len(sampler.binds), 2)
                second = [first[0], {"gl_texture": 7, "gl_target": 0x8C2A, "gl_binding": 0x8C2C}]
                with bind_atlas_textures(sampler, None, second, bindings):
                    self.assertEqual(sampler.bound[1, 0x8C2A], 7)
                self.assertEqual(sampler.queries, [(0, 0x8069), (1, 0x8069), (1, 0x8C2C)])
                self.assertEqual(sampler.unit, 0)
                raise RuntimeError("그리기 실패")
        self.assertEqual(sampler.bound, original)
        self.assertEqual(sampler.unit, 0)


class CompactFixture:
    def source(self, directory):
        directory.mkdir()
        width,height=13,11
        color=bytes(v for y in range(height) for x in range(width) for v in (x*9,y*12,50,180))
        shadow=bytes(v for y in range(height) for x in range(width) for v in (0,0,0,(x+y)*9))
        energy=bytes(v for y in range(height) for x in range(width) for v in (255 if x%2 else 0,0 if x%2 else 255,y*7,180))
        pages={};frames={}
        for kind,items in (("color",[AtlasItem(width,height,color),AtlasItem(width,height,shadow)]),
                           ("energy",[AtlasItem(width,height,energy)]),
                           ("vector",[AtlasItem(width,height,bytes((128,0,128,0))*width*height)])):
            packed,frames[kind]=pack_items(items,max_side=64)
            pages[kind]=[]
            for index,page in enumerate(packed):
                filename=f"{kind}_{index}.rgba.zlib";payload=zlib.compress(page.pixels)
                (directory/filename).write_bytes(payload)
                pages[kind].append(dict(file=filename,codec="rgba_zlib",width=page.width,height=page.height,
                                        sha256=hashlib.sha256(payload).hexdigest()))
        base=dict(interval_seconds=1/12,source_size=[width,height],size=[width,height],pivot=[6,10],pixel_scale=1,loop=True)
        document=dict(version=1,divisor=1,color_alpha_mode="premultiplied",vector_encoding="signed16_rgba_x64",
            pages=pages,frames=frames,clips={"body":dict(base,pairs=[[0,0,0,0,0,0]]),
                                          "shadow/body":dict(base,pairs=[[1,1,0,0]])})
        source=directory/"atlas.json";source.write_text(json.dumps(document),encoding="utf-8")
        return source


class CompactTests(CompactFixture,unittest.TestCase):
    def test_frame_bytes_rgb_and_playback_metadata_are_preserved(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);source=self.source(root/"source");before=source.read_bytes()
            compact_variant(source,root/"candidate")
            result=verify_variant(source,root/"candidate/atlas.json")
            self.assertTrue(result["pixels_equal"])
            self.assertEqual(source.read_bytes(),before)
            document=read_document(root/"candidate/atlas.json")
            self.assertEqual([p["codec"] for p in document["pages"]["color"]],["rgba_zlib","a8_zlib"])
            self.assertEqual(document["pages"]["energy"][0]["codec"],"rgb8_zlib")

    def test_existing_destination_is_never_overwritten(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);source=self.source(root/"source")
            compact_variant(source,root/"candidate")
            with self.assertRaises(FileExistsError):compact_variant(source,root/"candidate")

    def test_energy_only_keeps_color_payload_and_vector_data(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);source=self.source(root/"source")
            compact_energy_variant(source,root/"candidate")
            self.assertTrue(verify_variant(source,root/"candidate/atlas.json")["pixels_equal"])
            before,after=read_document(source),read_document(root/"candidate/atlas.json")
            self.assertEqual(before["pages"]["color"][0]["sha256"],after["pages"]["color"][0]["sha256"])

    def test_smaller_pages_do_not_trigger_new_full_preload(self):
        from types import SimpleNamespace
        from ferrial_drive.rendering.pico_pose_table import PicoPoseTable
        with TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ("idle_loop","run_loop"):
                (root/(name+".json")).write_text(json.dumps({"pages":{"color":[
                    {"width":4,"height":4,"codec":"a8_zlib"}]},"compaction":{"before_bytes":64},
                    "clips":{name+"/n":{"pixel_scale":1.5,"pivot":[2,3],"source_size":[4,4]}}}),encoding="utf-8")
            catalog=SimpleNamespace(directory=root,motions={name:{"variants":{"high":name+".json"}}
                                                           for name in ("idle_loop","run_loop")})
            with patch("ferrial_drive.rendering.pico_pose_table.PicoAtlasSprite",return_value=SimpleNamespace(estimated_bytes=16,close=lambda:None)) as load:
                table=PicoPoseTable(None,catalog,"high",budget_bytes=100)
                self.assertEqual(load.call_count,1)
                self.assertEqual(table.sizes["idle_loop"],16)
                self.assertEqual(table.clip_bounds["idle_loop/n"],(-3,-4.5,6,6))
                table.close()

    def test_short_rgb_and_alpha_payloads_are_rejected(self):
        for codec,channels in (("rgb8_zlib",3),("a8_zlib",1)):
            self.assertEqual(texture_payload_size(codec,3,2),6*channels)
            self.assertEqual(unpack_payload(codec,zlib.compress(bytes(6*channels)),3,2),(bytes(6*channels),False))
            with self.assertRaises(ValueError):unpack_payload(codec,zlib.compress(bytes(6*channels-1)),3,2)


@unittest.skipUnless(os.environ.get("FDRIVE_GPU_TESTS")=="1","실제 GPU 선택 검사")
class CompactGpuTests(CompactFixture,unittest.TestCase):
    def test_gpu_pixels_formats_and_storage_match_expected_channels(self):
        import pico2d.pico2d as pico
        from ferrial_drive.rendering.canvas import PicoCanvas
        from ferrial_drive.rendering.pico_motion_atlas import PicoAtlasSprite
        from ferrial_drive.diagnostics.gpu_profile import Uhd630Profile
        original=pico.SDL_CreateWindow
        with TemporaryDirectory() as directory, patch.dict(os.environ,SDL_VIDEODRIVER="windows"), \
             patch.object(pico,"SDL_CreateWindow",side_effect=lambda title,x,y,w,h,flags:
                original(title,x,y,w,h,(flags & ~pico.SDL_WINDOW_SHOWN)|pico.SDL_WINDOW_HIDDEN)):
            root=Path(directory);source=self.source(root/"source");compact_variant(source,root/"candidate")
            with PicoCanvas(64,64,"단축 채널 아틀라스 검사",vsync=False), Uhd630Profile(pico) as guard:
                sprites=[]
                try:
                    for path in (source,root/"candidate/atlas.json"):
                        sprites.append(PicoAtlasSprite(pico,path,decode_workers=1))
                    for clip in ("body","shadow/body"):
                        images=[]
                        for sprite in sprites:
                            pico.SDL_SetRenderDrawColor(pico.renderer,12,20,28,255)
                            pico.SDL_RenderClear(pico.renderer)
                            sprite.energy_color=(.2,.7,1)
                            sprite.draw_frame(clip,0,32,32,scale=2.3)
                            data=(ct.c_ubyte*(64*64*4))()
                            self.assertEqual(pico.SDL_RenderReadPixels(pico.renderer,None,pico.SDL_PIXELFORMAT_RGBA32,data,256),0)
                            images.append(bytes(data))
                        self.assertLessEqual(max(abs(a-b) for a,b in zip(*images)),1)
                    textures=sprites[1].cache.report()["textures"]
                    formats={row["codec"]:row["internal_format"] for row in textures}
                    self.assertEqual(formats["a8_zlib"],0x8229)
                    self.assertEqual(formats["rgb8_zlib"],0x8051)
                    self.assertFalse(guard.violations)
                finally:
                    for sprite in sprites:sprite.close()


if __name__=="__main__":unittest.main()
