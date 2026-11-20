"""모션 벡터 프레임 보간
원본·단순 혼합·벡터 보간·동일 시점 도형을 비교한다.
전체 KeyFrame 위상의 SmoothStep과 노출 시간 기반 모션 블러를 확인한다.
"""

import argparse
import ctypes as ct
import json
from math import isfinite
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ferrial_drive.diagnostics import TimingRecorder
from ferrial_drive.rendering.bicubic import BicubicSampler
from ferrial_drive.rendering.gl_pass import TexturedQuadPass
from ferrial_drive.rendering.motion_vectors import EASING_CODES, advance_combo_phase, frame_interval, load_clip, target_phase
from ferrial_drive.rendering.pico_interpolation import PicoFrameInterpolator, read_rgba_image
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.pico_renderer import PicoRenderer
from samples.frame_interpolation.fixture import build_clip, reference_shader


SAMPLE_DIRECTORY = PROJECT_ROOT / "samples/frame_interpolation"
WINDOW_SIZE = (1232, 690)


def pixel_metrics(reference, candidate):
    if len(reference) != len(candidate) or len(reference) % 4:
        raise ValueError("같은 크기의 RGBA 비교가 필요하다.")
    union = intersection = error = 0
    for index in range(0, len(reference), 4):
        ra, ca = reference[index + 3], candidate[index + 3]
        if ra or ca:
            union += 1
            error += sum(abs(reference[index + c] - candidate[index + c]) for c in range(4))
        if ra >= 128 and ca >= 128:
            intersection += 1
    mask_union = sum(reference[i] >= 128 or candidate[i] >= 128 for i in range(3, len(reference), 4))
    return {"premultiplied_mae_in_visible_union": error / (max(1, union) * 4 * 255),
            "alpha_iou": intersection / mask_union if mask_union else 1.0}


class FrameInterpolationTest:
    def __init__(self, *, dataset=None, phase=None, capture=None, report=None, timings=None,
                 scene=0, easing="smoothstep", blur=True):
        self.running = True
        self.pico = self.ui = self.interpolator = self.reference = None
        self.dataset = Path(dataset).resolve() if dataset else None
        self.capture_path = Path(capture).resolve() if capture else None
        self.report_path = Path(report).resolve() if report else None
        self.timings_path = Path(timings).resolve() if timings else None
        self.timings = TimingRecorder(enabled=bool(timings), session="frame_interpolation")
        self.config = json.loads((SAMPLE_DIRECTORY / "scenes.json").read_text(encoding="utf-8"))
        self.scene_index = scene
        self.phase = 0.0 if phase is None else phase
        target_phase(self.phase)
        self.paused = phase is not None
        self.easing = easing
        self.blur_enabled = blur
        self.blur_direction = "trailing"
        self.blur_strength = 0.65
        self.shutter_seconds = 0.016
        self.speed = 1.0
        self.dragging = False
        self.dragging_strength = False
        self.direction = 1
        self.smoothed_delta_seconds = 1 / 60
        self.frame_count = 0
        self.cache = {}
        self.checkerboard_texture = None
        self.checkerboard_size = None
        self.reference_frames = []
        self.reference_textures = {}
        self.native_provenance = {}
        self.dataset_catalog = []
        self.combo_boundary = "zero"
        self.catalog_durations = []
        self.dataset_catalog_path = self.dataset
        if self.dataset:
            catalog = json.loads(self.dataset.read_text(encoding="utf-8"))
            self.dataset_catalog = catalog.get("clips", [])
            if self.dataset_catalog:
                self.dataset = self.dataset.parent / self.dataset_catalog[0]["path"]
                for item in self.dataset_catalog:
                    path = self.dataset_catalog_path.parent / item["path"]
                    clip = json.loads(path.read_text(encoding="utf-8"))
                    pair = json.loads((path.parent / clip["pairs"][0]).read_text(encoding="utf-8"))
                    self.catalog_durations.append(len(clip["pairs"]) * pair["duration_seconds"])

    def enter(self):
        import pico2d.pico2d as pico
        self.pico = pico
        theme = json.loads((PROJECT_ROOT / "Tools/theme_reference/theme.json").read_text(encoding="utf-8"))
        self.colors = theme["colors"]
        fonts = theme["fonts"]
        self.ui = PicoRenderer({role: PROJECT_ROOT / "data/fonts" / info["path"] for role, info in fonts.items()},
                               {role: info["size"] for role, info in fonts.items()})
        self.interpolator = PicoFrameInterpolator(pico)
        initial_scene = self.scene_index
        if self.dataset_catalog:
            for index in range(len(self.dataset_catalog)):
                self.select_scene(index)
        self.select_scene(initial_scene)

    def select_scene(self, index):
        for texture in self.reference_textures.values():
            self.pico.SDL_DestroyTexture(texture)
        self.reference_textures.clear()
        if self.dataset:
            if self.dataset_catalog:
                self.scene_index = index % len(self.dataset_catalog)
                self.dataset = self.dataset_catalog_path.parent / self.dataset_catalog[self.scene_index]["path"]
            cache_key = ("dataset", self.dataset.resolve())
            if cache_key not in self.cache:
                self.cache[cache_key] = load_clip(self.dataset, lambda path: read_rgba_image(self.pico, path))
            self.clip = self.cache[cache_key]
            metadata = json.loads(self.dataset.read_text(encoding="utf-8"))
            self.reference_frames = metadata.get("reference_frames", [])
            self.native_provenance = metadata.get("provenance", {})
            self.description = ("Unreal 원본 벡터 · 실제 중간 렌더 비교" if self.native_provenance.get("type") == "unreal_native_motion_vectors"
                                else "외부 모션 벡터 · 출처와 변환 규약 별도 확인")
        else:
            self.reference_frames = []
            self.native_provenance = {}
            self.scene_index = index % len(self.config["scenes"])
            scene = self.config["scenes"][self.scene_index]
            if self.scene_index not in self.cache:
                self.cache[self.scene_index] = build_clip(scene, self.config["size_pixels"],
                                                          self.config["duration_seconds"])
            self.clip = self.cache[self.scene_index]
            self.description = scene["description"]
        self.interpolator.set_clip(self.clip)
        if self.reference:
            self.reference.close()
            self.reference = None
        if not self.dataset:
            self.reference = TexturedQuadPass(self.pico, fragment_shader=reference_shader(scene),
                                           extra_uniforms=("phase", "blurSpan", "easing", "blurBias", "playbackDirection", "blurStrength"))
        elif self.reference_frames:
            self.reference = BicubicSampler(self.pico, None)

    def handle_event(self, event):
        p = self.pico
        if event.type == p.SDL_KEYDOWN:
            key = event.key
            if key == p.SDLK_ESCAPE:
                self.running = False
            elif key == p.SDLK_SPACE:
                self.paused = not self.paused
            elif key == p.SDLK_b:
                self.blur_enabled = not self.blur_enabled
            elif key == p.SDLK_d:
                choices = ("trailing", "centered", "leading")
                self.blur_direction = choices[(choices.index(self.blur_direction) + 1) % 3]
            elif key in (p.SDLK_COMMA, p.SDLK_PERIOD):
                self.blur_strength = max(0, min(1, self.blur_strength + (0.05 if key == p.SDLK_PERIOD else -0.05)))
            elif key == p.SDLK_s:
                self.easing = "linear" if self.easing == "smoothstep" else "smoothstep"
            elif key in (p.SDLK_1, p.SDLK_2, p.SDLK_3, p.SDLK_4) and (not self.dataset or self.dataset_catalog):
                self.select_scene(key - p.SDLK_1)
                self.phase = 0
            elif key in (p.SDLK_LEFT, p.SDLK_RIGHT):
                self.paused = True
                self.phase = max(0, min(1, self.phase + (1 if key == p.SDLK_RIGHT else -1) / 120))
            elif key in (p.SDLK_LEFTBRACKET, p.SDLK_RIGHTBRACKET):
                delta = 0.004 if key == p.SDLK_RIGHTBRACKET else -0.004
                self.shutter_seconds = max(0, min(0.064, self.shutter_seconds + delta, self.clip.duration_seconds))
            elif key in (p.SDLK_UP, p.SDLK_DOWN):
                self.speed = max(0.25, min(2, self.speed + (0.25 if key == p.SDLK_UP else -0.25)))
        elif event.type == p.SDL_MOUSEBUTTONDOWN and event.button == p.SDL_BUTTON_LEFT:
            button_key = None
            if 80 <= event.y <= 116:
                for left, width, key in ((16, 500, p.SDLK_s), (528, 370, p.SDLK_b),
                                         (910, 140, p.SDLK_LEFTBRACKET), (1062, 154, p.SDLK_RIGHTBRACKET)):
                    if left <= event.x <= left + width:
                        button_key = key
            elif 600 <= event.y <= 633 and (not self.dataset or self.dataset_catalog):
                choices = ((16, 84), (110, 100), (220, 84), (314, 84)) if self.dataset_catalog else ((16, 84), (110, 100), (220, 84))
                for index, (left, width) in enumerate(choices):
                    if left <= event.x <= left + width:
                        button_key = p.SDLK_1 + index
            if button_key is not None:
                key_event = p.Event(p.SDL_KEYDOWN)
                key_event.key = button_key
                self.handle_event(key_event)
            elif 960 <= event.x <= 1216 and 534 <= event.y <= 566:
                self.dragging_strength = True
                self.blur_strength = max(0, min(1, (event.x - 960) / 256))
            elif 16 <= event.x <= 1216 and 492 <= event.y <= 532:
                self.dragging = self.paused = True
                self.phase = max(0, min(1, (event.x - 16) / 1200))
        elif event.type == p.SDL_MOUSEBUTTONDOWN and event.button == p.SDL_BUTTON_RIGHT:
            if 528 <= event.x <= 898 and 80 <= event.y <= 116:
                key_event = p.Event(p.SDL_KEYDOWN)
                key_event.key = p.SDLK_d
                self.handle_event(key_event)
        elif event.type == p.SDL_MOUSEBUTTONUP:
            self.dragging = False
            self.dragging_strength = False
        elif event.type == p.SDL_MOUSEMOTION and self.dragging_strength:
            self.blur_strength = max(0, min(1, (event.x - 960) / 256))
        elif event.type == p.SDL_MOUSEMOTION and self.dragging:
            self.phase = max(0, min(1, (event.x - 16) / 1200))
        elif event.type == p.SDL_WINDOWEVENT and event.window_event == p.SDL_WINDOWEVENT_FOCUS_LOST:
            self.dragging = False
            self.dragging_strength = False
            self.paused = True

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("프레임 시간은 0 이상의 유한한 초 단위여야 한다.")
        self.frame_count += 1
        self.smoothed_delta_seconds += (delta_seconds - self.smoothed_delta_seconds) * 0.05
        if not self.paused:
            if self.dataset_catalog:
                durations = self.catalog_durations or [self.clip.duration_seconds] * len(self.dataset_catalog)
                index, phase = advance_combo_phase(self.scene_index, self.phase, delta_seconds * self.speed,
                                                    durations, boundary=self.combo_boundary)
                if index != self.scene_index:
                    self.select_scene(index)
                self.phase, self.direction = phase, 1
                return
            # 정방향/역방향은 클립 전체 위상에 적용한다. 각 구간에서 곡선을 재시작하지 않는다.
            travel = self.phase if self.direction > 0 else 2 - self.phase
            travel = (travel + delta_seconds * self.speed / self.clip.duration_seconds) % 2
            self.phase, self.direction = (travel, 1) if travel <= 1 else (2 - travel, -1)

    def draw_reference(self, destination, *, shutter_seconds=0):
        if self.reference is None:
            return
        s, pair = self.reference, self.clip.pairs[0]
        if self.dataset:
            reference = self.nearest_reference()
            name = reference["image"]
            if name not in self.reference_textures:
                width, height, pixels = read_rgba_image(self.pico, self.dataset.parent / name)
                if (width, height) != (pair.width, pair.height):
                    raise ValueError("정답 렌더와 원본의 크롭·크기가 다르다.")
                self.reference_textures[name] = self.interpolator._texture(width, height, pixels)
            s.draw(self.reference_textures[name], (pair.width, pair.height),
                   self.pico.SDL_Rect(0, 0, pair.width, pair.height), destination)
            return
        with s.batch():
            s.glUniform1f(s.uniforms["phase"], self.phase)
            s.glUniform1f(s.uniforms["blurSpan"], shutter_seconds / self.clip.duration_seconds)
            s.glUniform1f(s.uniforms["blurStrength"], self.blur_strength)
            s.glUniform1f(s.uniforms["blurBias"], {"trailing": -0.5, "centered": 0.0, "leading": 0.5}[self.blur_direction])
            s.glUniform1f(s.uniforms["playbackDirection"], self.direction)
            s.glUniform1i(s.uniforms["easing"], EASING_CODES[self.easing])
            s.draw(self.interpolator.textures[0], (pair.width, pair.height),
                   self.pico.SDL_Rect(0, 0, pair.width, pair.height), destination)

    def nearest_reference(self):
        goal = target_phase(self.phase, easing=self.easing)
        return min(self.reference_frames, key=lambda item: abs(item["phase"] - goal))

    def draw_mode(self, mode, destination, *, shutter_seconds=0):
        if mode == "reference":
            self.draw_reference(destination, shutter_seconds=shutter_seconds)
        else:
            with self.timings.scope("interpolation.cpu_dispatch"):
                self.interpolator.draw(self.phase, destination, mode=mode,
                                       easing=self.easing, shutter_seconds=shutter_seconds,
                                       blur_direction=self.blur_direction, playback_direction=self.direction,
                                       blur_strength=self.blur_strength)

    def checkerboard(self, x, y, size):
        if self.checkerboard_size != size:
            if self.checkerboard_texture:
                self.pico.SDL_DestroyTexture(self.checkerboard_texture)
            light, dark = bytes((23, 42, 53, 255)), bytes((16, 31, 39, 255))
            rows = [b"".join(light if (row // 24 + column // 24) % 2 else dark for column in range(size))
                    for row in range(size)]
            self.checkerboard_texture = self.interpolator._texture(size, size, b"".join(rows))
            self.checkerboard_size = size
        target = self.pico.SDL_Rect(x, y, size, size)
        self.pico.SDL_RenderCopy(self.pico.renderer, self.checkerboard_texture, None, ct.byref(target))

    def draw(self):
        r, c, p = self.ui, self.colors, self.pico
        p.SDL_SetRenderDrawColor(p.renderer, 9, 18, 23, 255)
        p.SDL_RenderClear(p.renderer)
        r.text("모션 벡터 프레임 보간", 16, 16, "title", c["text"])
        clip_label = self.dataset_catalog[self.scene_index]["name"] if self.dataset_catalog else self.clip.pairs[0].label
        r.text(clip_label + "  ·  " + self.description, 16, 53, "small", c["muted"], max_width=1190)
        label = "SmoothStep · 전체 KeyFrame 위상" if self.easing == "smoothstep" else "선형 · 전체 KeyFrame 위상"
        shutter = min(self.shutter_seconds * self.speed, self.clip.duration_seconds) if self.blur_enabled else 0.0
        direction_label = {"trailing": "후방", "centered": "양방향", "leading": "전방"}[self.blur_direction]
        for x, width, text in ((16, 500, label),
                               (528, 370, f"블러 {'ON' if shutter else 'OFF'} · {direction_label} · {self.shutter_seconds * 1000 if shutter else 0:.0f}ms"),
                               (910, 140, "노출 −4ms"), (1062, 154, "노출 +4ms")):
            r.rect(Rect(x, 80, width, 36), c["selected"])
            r.text(text, x + 12, 87, "small", c["accent"])
        labels = ("원본 프레임 유지", "단순 이미지 혼합", "벡터 보간" + (" + 블러" if shutter else ""),
                  "실제 Unreal 렌더" if self.dataset else "동일 시점 도형" + (" + 블러" if shutter else ""))
        for index, mode in enumerate(("hold", "blend", "motion", "reference")):
            x = 16 + index * 304
            r.text(labels[index], x, 132, "body", c["text"])
            self.checkerboard(x, 164, 288)
            self.draw_mode(mode, p.SDL_Rect(x, 164, 288, 288),
                           shutter_seconds=shutter if mode in ("motion", "reference") else 0)
            if mode == "reference" and not self.reference:
                r.text("정답 미제공", x + 144, 292, "body", c["warning"], align="center")
        goal = target_phase(self.phase, easing=self.easing)
        pair_index, fraction = frame_interval(goal, len(self.clip.pairs))
        reference_info = (f" · 정답 위상 {self.nearest_reference()['phase']:.3f}" if self.reference_frames else "")
        r.text(f"시간 진행률 {self.phase:.3f}  →  목표 위상 {goal:.3f}  →  원본 {pair_index}–{pair_index + 1} · 보간률 {fraction:.3f}{reference_info}",
               16, 465, "small", c["muted"])
        r.rect(Rect(16, 500, 1200, 8), c["line"])
        r.rect(Rect(16, 500, max(1, 1200 * self.phase), 8), c["accent"])
        r.rect(Rect(13 + 1200 * self.phase, 494, 6, 20), c["text"])
        r.text(f"{'일시정지' if self.paused else '재생'}  ·  {self.speed:.2f}배  ·  원본 {1 / self.clip.pairs[0].duration_seconds:g}fps  ·  표시 약 {1 / max(0.0001, self.smoothed_delta_seconds):.0f}fps",
               16, 540, "small", c["muted"])
        r.text(f"강도 {self.blur_strength:.0%}", 850, 540, "small", c["accent"])
        r.rect(Rect(960, 548, 256, 6), c["line"])
        r.rect(Rect(960, 548, max(1, 256 * self.blur_strength), 6), c["accent"])
        r.text("Space 재생/정지   ← → 시점   ↑ ↓ 속도   S 위상   B 블러   D 방향(블러 우클릭)   , . 강도   [ ] 노출", 16, 574, "small", c["text"])
        buttons = ((16, 84, "1 이동"), (110, 100, "2 검 회전"), (220, 84, "3 가림"))
        if self.dataset_catalog:
            buttons = ((16, 84, "1타"), (110, 100, "2타"), (220, 84, "3타"), (314, 84, "4타"))
        for index, (x, width, text) in enumerate(buttons):
            enabled = not self.dataset or bool(self.dataset_catalog)
            r.rect(Rect(x, 600, width, 33), c["selected"] if index == self.scene_index and enabled else c["panel"])
            r.text(text, x + 8, 607, "small", c["text"] if enabled else c["disabled"])
        r.text("각 동작 선택 · 재생 시 1→2→3→4타 연계" if self.dataset_catalog else "막대 드래그 · 위쪽 버튼으로 비교 전환 · Esc 종료",
               418 if self.dataset_catalog else 324, 607, "small", c["text"])
        note = ("Unreal 검 동작 · 정답은 가장 가까운 원본 렌더 시각(블러 없음) · 가림 복원/본편 연결은 별도 검증"
                if self.dataset else "도형의 정확한 대응 벡터 실험 · 실제 Unreal 벡터 추출/가림 복원/본편 연결은 별도 검증")
        r.text(note, 16, 646, "small", c["warning"])
        if self.capture_path:
            r.save_frame(self.capture_path, *WINDOW_SIZE)
            self.capture_path = None

    def read_mode_pixels(self, mode, *, shutter_seconds=0):
        p, pair = self.pico, self.clip.pairs[0]
        target = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_TARGET,
                                     pair.width, pair.height)
        if not target:
            raise RuntimeError("비교용 렌더 타깃 생성 실패")
        previous = p.SDL_GetRenderTarget(p.renderer)
        try:
            if p.SDL_SetRenderTarget(p.renderer, target) != 0:
                raise RuntimeError("비교용 렌더 타깃 연결 실패")
            p.SDL_SetRenderDrawColor(p.renderer, 0, 0, 0, 0)
            p.SDL_RenderClear(p.renderer)
            self.draw_mode(mode, p.SDL_Rect(0, 0, pair.width, pair.height), shutter_seconds=shutter_seconds)
            buffer = ct.create_string_buffer(pair.width * pair.height * 4)
            if p.SDL_RenderReadPixels(p.renderer, None, p.SDL_PIXELFORMAT_RGBA32, buffer, pair.width * 4) != 0:
                raise RuntimeError("비교 이미지 읽기 실패")
            return buffer.raw
        finally:
            if self.checkerboard_texture:
                self.pico.SDL_DestroyTexture(self.checkerboard_texture)
                self.checkerboard_texture = None
            p.SDL_SetRenderTarget(p.renderer, previous)
            p.SDL_DestroyTexture(target)

    def quality_report(self):
        report = {"scene": self.clip.pairs[0].label, "clock_phase": self.phase,
                  "target_phase": target_phase(self.phase, easing=self.easing), "easing": self.easing,
                  "duration_seconds": self.clip.duration_seconds,
                  "source_intervals": len(self.clip.pairs), "shader_blur_samples": 9, "blur_strength": self.blur_strength,
                  "blur_direction": self.blur_direction, "playback_direction": self.direction,
                  "unreal_motion_vectors_verified": bool(self.native_provenance.get("native_capture_verified")),
                  "occlusion_reconstruction": False,
                  "gpu_time_measured": False, "reference_provided": self.reference is not None}
        if self.reference:
            reference = self.read_mode_pixels("reference")
            report["metrics"] = {mode: pixel_metrics(reference, self.read_mode_pixels(mode))
                                 for mode in ("hold", "blend", "motion")}
            if self.dataset:
                reference_phase = self.nearest_reference()["phase"]
                report["reference_phase"] = reference_phase
                report["reference_time_error_seconds"] = abs(reference_phase - report["target_phase"]) * self.clip.duration_seconds
                report["native_reference_blur_available"] = False
            else:
                shutter = min(self.shutter_seconds * self.speed, self.clip.duration_seconds)
                report["blur_shutter_seconds"] = self.shutter_seconds
                report["blur_clip_span_seconds"] = shutter
                report["metrics"]["motion_blur"] = pixel_metrics(
                    self.read_mode_pixels("reference", shutter_seconds=shutter),
                    self.read_mode_pixels("motion", shutter_seconds=shutter))
        return report

    def exit(self):
        try:
            if self.report_path and self.interpolator and self.interpolator.pair:
                self.report_path.parent.mkdir(parents=True, exist_ok=True)
                self.report_path.write_text(json.dumps(self.quality_report(), ensure_ascii=False, indent=2), encoding="utf-8")
            if self.timings_path:
                self.timings.write_json(self.timings_path)
        finally:
            for texture in self.reference_textures.values():
                self.pico.SDL_DestroyTexture(texture)
            self.reference_textures.clear()
            if self.reference:
                self.reference.close()
                self.reference = None
            if self.interpolator:
                self.interpolator.close()
                self.interpolator = None
            if self.ui:
                self.ui.close()
                self.ui = None


class ComboBoundaryComparison:
    """한 재생기에서 A 이월 / B 첫 위상 출력 후보를 전환한다."""

    def __init__(self, dataset, *, phase=None, capture=None):
        self.program = FrameInterpolationTest(dataset=dataset, phase=phase)
        self.program.combo_boundary = "carry"
        self.running = True
        self.capture = Path(capture) if capture else None

    def enter(self):
        self.program.enter()

    def handle_event(self, event):
        program = self.program
        p = program.pico
        if event.type == p.SDL_KEYDOWN and event.key == p.SDLK_TAB:
            program.combo_boundary = "zero" if program.combo_boundary == "carry" else "carry"
            return
        if event.type == p.SDL_MOUSEBUTTONDOWN and event.button == p.SDL_BUTTON_LEFT and 12 <= event.y <= 47:
            if 850 <= event.x <= 1020:
                program.combo_boundary = "carry"
                return
            if 1032 <= event.x <= 1216:
                program.combo_boundary = "zero"
                return
        if event.type == p.SDL_KEYDOWN and event.key == p.SDLK_r:
            program.select_scene(0)
            program.phase = 0
            program.paused = False
            return
        program.handle_event(event)
        self.running = program.running

    def update(self, delta_seconds):
        self.program.update(delta_seconds)

    def draw(self):
        program = self.program
        program.draw()
        r, c = program.ui, program.colors
        for x, width, mode, label in ((850, 170, "carry", "A 시간 이월"), (1032, 184, "zero", "B 위상 0 시작")):
            r.rect(Rect(x, 12, width, 35), c["selected"] if program.combo_boundary == mode else c["panel"])
            r.text(label, x + 10, 21, "small", c["accent"] if program.combo_boundary == mode else c["muted"])
        r.rect(Rect(16, 640, 1200, 38), c["background"])
        label = "A 시간 이월" if program.combo_boundary == "carry" else "B 위상 0 시작"
        r.text(f"현재 {label} · Tab/버튼으로 전환 · R 같은 시작점에서 재생 · 한 후보만 렌더한다.", 16, 646, "small", c["warning"])
        if self.capture:
            r.save_frame(self.capture, *WINDOW_SIZE)
            self.capture = None

    def exit(self):
        self.program.exit()


def main():
    from ferrial_drive.runtime import run_application
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, help="외부 클립 또는 프레임 쌍 JSON")
    parser.add_argument("--phase", type=float, help="0~1의 전체 시간 진행률에서 정지")
    parser.add_argument("--scene", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--linear", action="store_true")
    parser.add_argument("--no-blur", action="store_true")
    parser.add_argument("--frames", type=int)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timings", type=Path)
    args = parser.parse_args()
    program = FrameInterpolationTest(dataset=args.dataset, phase=args.phase, capture=args.capture,
                                     report=args.report, timings=args.timings, scene=args.scene - 1,
                                     easing="linear" if args.linear else "smoothstep", blur=not args.no_blur)
    run_application(program, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1],
                    title="Ferrial Drive | Frame Interpolation", frame_limit=args.frames)
