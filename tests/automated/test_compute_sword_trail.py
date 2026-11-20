"""Compute 정점과 CPU 기준의 좌표·UV·알파·화면 및 GL 상태 복구를 비교한다."""

import ctypes as ct
from dataclasses import replace
from math import cos, sin
import os
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ferrial_drive.combat.geometry import Vec2
from ferrial_drive.diagnostics.gpu_profile import bind_gl
from ferrial_drive.rendering.compute_sword_trail import ComputeSwordTrail, SSBO, SSBO_BINDING, trail_inputs
from ferrial_drive.rendering.pico_sword_effects import PicoSwordEffects
from tests.automated.test_sword_trail_continuity import section


def fixture(now=.08):
    rows = [section((cos(i*.35)*70,sin(i*.35)*70),(cos((i+1)*.35)*70,sin((i+1)*.35)*70),.01*(i+1))
            for i in range(5)]
    rows.extend([section((60,0),(40,20),.04,strike=2,chevron=(Vec2(-30,-30),Vec2(90,-20),Vec2(-30,0))),
                 section((60,0),(40,20),.05,strike=2,chevron=(Vec2(-30,-30),Vec2(90,-20),Vec2(-30,0)))])
    effects = SimpleNamespace(sections=rows,time_seconds=now,settings={"thrust_visual_scale":1.6},
                              profiles=[{"reach_scale":1,"color":"#9DDFEA","trail_opacity":.3}])
    effects.opacity = lambda row: max(0,1-(effects.time_seconds-row.created_seconds)/row.lifetime_seconds)
    return effects


class TrailInputTests(unittest.TestCase):
    def test_section_overdrive_color_reaches_compute_controls(self):
        effect = fixture()
        effect.sections = [replace(row, color="#FF4044") for row in effect.sections]
        controls, _ = trail_inputs(effect, "#FFFFFF")
        self.assertAlmostEqual(controls[12], 1)
        self.assertAlmostEqual(controls[13], 64 / 255)
        self.assertAlmostEqual(controls[14], 68 / 255)

    def test_control_transfer_preserves_game_sections_and_does_not_generate_cpu_curve(self):
        effect = fixture()
        before = list(effect.sections)
        with patch("ferrial_drive.rendering.sword_trail_geometry.curved_trail_sections", side_effect=AssertionError("CPU 곡선 계산")):
            controls,jobs = trail_inputs(effect,"#FFFFFF")
        self.assertEqual(effect.sections,before)
        self.assertGreater(len(jobs),0)
        self.assertLess(len(controls)*4+len(jobs)*4,(len(jobs)//8)*128)


@unittest.skipUnless(os.environ.get("FDRIVE_GPU_TESTS")=="1","실제 GPU 검사는 선택 실행한다.")
class ComputeTrailGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pico2d.pico2d as pico
        from ferrial_drive.rendering import PicoCanvas
        cls.pico = pico
        create_window = pico.SDL_CreateWindow
        cls.environment = patch.dict(os.environ,{"SDL_VIDEODRIVER":"windows"})
        cls.environment.start()
        cls.canvas = PicoCanvas(224,224,"Compute Trail comparison")
        with patch.object(pico,"SDL_CreateWindow",side_effect=lambda t,x,y,w,h,f:
                          create_window(t,x,y,w,h,(f & ~pico.SDL_WINDOW_SHOWN)|pico.SDL_WINDOW_HIDDEN)):
            cls.canvas.open()
        from ferrial_drive.assets.trail_flow import prepare_flow_texture
        cls.flow_workspace = TemporaryDirectory()
        prepare_flow_texture({},cls.flow_workspace.name)

    @classmethod
    def tearDownClass(cls):
        cls.flow_workspace.cleanup()
        cls.canvas.close()
        cls.environment.stop()

    def setUp(self):
        self.p = self.pico
        self.renderer = SimpleNamespace(pico=self.p)
        self.camera = SimpleNamespace(world_to_screen=lambda point:(point[0]+90,point[1]+90))
        self.cpu = PicoSwordEffects(self.renderer,flow_directory=self.flow_workspace.name)
        self.gpu = ComputeSwordTrail(self.p)
        self.addCleanup(self.gpu.close)
        self.addCleanup(self.cpu.close)

    def test_generated_vertices_match_curves_thrusts_alpha_uv_and_long_clock(self):
        finish = bind_gl(self.p,"glFinish",None,[])
        for long_clock in (0,100000):
            effect = fixture()
            effect.time_seconds += long_clock
            effect.sections = [replace(row,created_seconds=row.created_seconds+long_clock) for row in effect.sections]
            expected = []
            def capture(renderer,texture,vertices,count,indices,index_count):
                expected.extend((v.position.x,v.position.y,v.tex_coord.x,v.tex_coord.y,
                                 v.color.r/255,v.color.g/255,v.color.b/255,v.color.a/255) for v in vertices[:count])
                return 0
            camera = SimpleNamespace(world_to_screen=lambda point:point)
            with patch.object(self.p,"SDL_RenderGeometry",side_effect=capture):
                self.cpu.draw_trail(effect,camera,"#FFFFFF")
            with self.gpu.batch(),self.gpu.state():
                self.gpu.generate(effect,"#FFFFFF")
                self.gpu.glMemoryBarrier(0x0200)
                finish()
                actual = (ct.c_float*(self.gpu.last_job_count*32))()
                self.gpu.glBindBuffer(SSBO,self.gpu.buffers[2])
                self.gpu.glGetBufferSubData(SSBO,0,ct.sizeof(actual),actual)
            self.assertEqual(len(expected),self.gpu.last_job_count*4)
            for index,row in enumerate(expected):
                got = actual[index*8:index*8+8]
                for field,(left,right) in enumerate(zip(row,got)):
                    self.assertAlmostEqual(left,right,delta=.002 if field<4 else 1/255+.00001,
                                           msg=f"vertex {index}, field {field}, clock {long_clock}")

    def test_pixels_match_cpu_and_ssbo_state_is_restored(self):
        effect = fixture()
        p = self.p
        def render(compute):
            p.SDL_SetRenderDrawColor(p.renderer,24,30,38,255)
            p.SDL_RenderClear(p.renderer)
            if compute:
                self.cpu.prepare_flow(effect.settings)
                self.gpu.render(effect,self.camera,self.renderer,self.cpu.flow_texture,"#FFFFFF")
            else:
                self.cpu.draw_trail(effect,self.camera,"#FFFFFF")
            pixels = ct.create_string_buffer(224*224*4)
            self.assertEqual(p.SDL_RenderReadPixels(p.renderer,None,p.SDL_PIXELFORMAT_RGBA32,pixels,224*4),0)
            return pixels.raw
        original = self.gpu.integer(SSBO_BINDING)
        for zoom in (1,.9,.85):
            self.camera = SimpleNamespace(zoom=zoom,world_to_screen=lambda point:(point[0]*zoom+90,point[1]*zoom+90))
            cpu,gpu = render(False),render(True)
            self.assertEqual(self.gpu.integer(SSBO_BINDING),original)
            difference = sum(abs(a-b) for a,b in zip(cpu,gpu))/len(cpu)
            self.assertLess(difference,.15)
            self.assertGreater(sum(cpu[i]!=24 for i in range(0,len(cpu),4)),100)

    def test_loading_preparation_executes_and_reserves_without_touching_target_state(self):
        effect = fixture()
        effect.settings['max_sections'] = 8
        self.cpu.prepare(effect.settings)
        p = self.p
        original = self.gpu.integer(SSBO_BINDING)
        viewport,clip = p.SDL_Rect(4,5,180,170),p.SDL_Rect(2,3,150,140)
        try:
            p.SDL_RenderSetScale(p.renderer,.8,.75)
            p.SDL_RenderSetViewport(p.renderer,ct.byref(viewport))
            p.SDL_RenderSetClipRect(p.renderer,ct.byref(clip))
            self.gpu.prepare(effect.settings,self.cpu.flow_texture)
            actual_viewport,actual_clip = p.SDL_Rect(),p.SDL_Rect()
            sx,sy = ct.c_float(),ct.c_float()
            p.SDL_RenderGetScale(p.renderer,ct.byref(sx),ct.byref(sy))
            p.SDL_RenderGetViewport(p.renderer,ct.byref(actual_viewport))
            p.SDL_RenderGetClipRect(p.renderer,ct.byref(actual_clip))
            self.assertAlmostEqual(sx.value,.8)
            self.assertAlmostEqual(sy.value,.75)
            self.assertEqual(tuple(getattr(actual_viewport,k)for k in ('x','y','w','h')),(4,5,180,170))
            self.assertEqual(tuple(getattr(actual_clip,k)for k in ('x','y','w','h')),(2,3,150,140))
            self.assertEqual(self.gpu.integer(SSBO_BINDING),original)
            self.assertEqual(self.gpu.last_job_count,0)
            with patch.object(self.gpu,'glBufferData',side_effect=AssertionError('첫 공격 버퍼 할당')):
                self.gpu.render(effect,self.camera,self.renderer,self.cpu.flow_texture,'#FFFFFF')
        finally:
            p.SDL_RenderSetScale(p.renderer,1,1)
            p.SDL_RenderSetViewport(p.renderer,None)
            p.SDL_RenderSetClipRect(p.renderer,None)

    def test_first_draw_after_loading_never_generates_pixels_or_compiles_again(self):
        effect = fixture()
        painter = PicoSwordEffects(self.renderer,trail_backend='compute',flow_directory=self.flow_workspace.name)
        self.addCleanup(painter.close)
        with patch('ferrial_drive.rendering.sword_trail_texture.trail_flow_pixels',side_effect=AssertionError('픽셀 생성')):
            painter.prepare(effect.settings)
            self.assertTrue(painter.prepared)
            self.assertIsNotNone(painter.compute_trail)
            with patch('ferrial_drive.rendering.compute_sword_trail.ShaderProgram',side_effect=AssertionError('첫 공격 컴파일')), \
                 patch.object(painter.compute_trail,'glBufferData',side_effect=AssertionError('첫 공격 할당')):
                painter.draw_trail(effect,self.camera,'#FFFFFF')
                painter.prepare(effect.settings)
        self.assertEqual(painter.last_trail_backend,'compute')

    def test_failed_preparation_restores_target_and_ssbo(self):
        self.cpu.prepare_flow({})
        original = self.gpu.integer(SSBO_BINDING)
        with patch.object(self.gpu,'_dispatch_inputs',side_effect=RuntimeError('의도한 사전 실행 실패')):
            with self.assertRaisesRegex(RuntimeError,'의도한 사전 실행 실패'):
                self.gpu.prepare({},self.cpu.flow_texture)
        self.assertFalse(self.p.SDL_GetRenderTarget(self.p.renderer))
        self.assertEqual(self.gpu.integer(SSBO_BINDING),original)


if __name__=="__main__":
    unittest.main()
