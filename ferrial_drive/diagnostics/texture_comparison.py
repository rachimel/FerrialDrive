"""독립 텍스처 비교 화면. 게임 입력·판정과 자원 준비/계측을 분리한다."""

import ctypes as ct
import gc
import json
from math import ceil
from pathlib import Path
from statistics import mean
from time import perf_counter

from ferrial_drive.diagnostics import TimingRecorder
from ferrial_drive.diagnostics.texture_metrics import GpuFrameTimer, ProcessGpuMemory, bind_gl, process_memory
from ferrial_drive.rendering.pico_motion_atlas import AtlasPainter, AtlasTextureCache, PicoMotionAtlas
from ferrial_drive.rendering.pico_motion_sprite import PicoMotionSprite
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.pico_renderer import PicoRenderer


WINDOW_SIZE = (1440, 900)
ROOT = Path(__file__).resolve().parents[2]


def legacy_disk_size(catalog):
    """실제로 선택한 입력이 참조하는 파일을 중복 없이 집계한다."""
    catalog = Path(catalog)
    paths = {catalog.resolve()}
    for row in json.loads(catalog.read_text(encoding="utf-8"))["clips"]:
        clip = (catalog.parent / row["path"]).resolve()
        paths.add(clip)
        for pair_name in json.loads(clip.read_text(encoding="utf-8"))["pairs"]:
            pair = (clip.parent / pair_name).resolve()
            paths.add(pair)
            data = json.loads(pair.read_text(encoding="utf-8"))
            for key in ("image_a", "image_b", "forward_a_to_b", "backward_b_to_a"):
                paths.add((pair.parent / data[key]).resolve())
    return sum(path.stat().st_size for path in paths)


class TextureComparison:
    def __init__(self, comparison, *, case=None, report=None, capture=None, phase=None,
                 clip=None, measure=False, quality_directory=None, started=None, candidate=None):
        self.source = Path(comparison).resolve()
        self.document = json.loads(self.source.read_text(encoding="utf-8"))
        self.case, self.measure = case, measure
        self.report_path, self.capture_path = Path(report) if report else None, Path(capture) if capture else None
        self.quality_directory = Path(quality_directory) if quality_directory else None
        self.started = perf_counter() if started is None else started
        self.running, self.paused, self.blur = True, phase is not None, True
        self.show_metrics = False
        self.phase = 0 if phase is None else phase
        self.zoom, self.instances = 1, 1
        self.frame, self.first_present_seconds, self.frame_started = 0, None, 0
        self.frame_times, self.captures = [], []
        self.clip_index = self.document["clips"].index(clip) if clip else 0
        self.case_names = [name for name in self.document["cases"] if name != "legacy"]
        self.candidate_index = 1 if len(self.case_names) > 1 else 0
        if candidate:
            self.candidate_index = self.case_names.index(candidate)
        self.timings = TimingRecorder(enabled=measure or report is not None, session="texture-comparison")
        self.painter = self.cache = self.ui = self.gpu_timer = self.gpu_memory = None
        self.legacy = self.candidate = None
        self.assets_loaded = False
        self.resources = []
        self.memory_before = self.memory_loaded = self.gpu_before = None
        self.gpu_loaded = None
        self.gpu_memory_samples = []
        self.loaded_case, self.disk_bytes, self.clone_extra_gpu_bytes = None, 0, None
        self.benchmark_summary = {}
        benchmark_path = self.source.parent / "benchmark" / "summary.json"
        if benchmark_path.is_file():
            self.benchmark_summary = json.loads(benchmark_path.read_text(encoding="utf-8"))

    @property
    def clip_name(self):
        return self.document["clips"][self.clip_index]

    def enter(self):
        import pico2d.pico2d as pico
        self.pico = pico
        self.theme = json.loads((ROOT / "Tools/theme_reference/theme.json").read_text(encoding="utf-8"))
        self.colors = self.theme["colors"]
        self.ui = PicoRenderer({role: ROOT / "data/fonts" / value["path"] for role, value in self.theme["fonts"].items()},
                               {role: value["size"] for role, value in self.theme["fonts"].items()})
        self.painter = AtlasPainter(pico)
        get_string = bind_gl(pico, "glGetString", ct.c_char_p, [ct.c_uint])
        self.gpu_device = {name: get_string(value).decode(errors="replace") for name, value in
                           (("vendor", 0x1F00), ("renderer", 0x1F01), ("version", 0x1F02))}
        self.cache = AtlasTextureCache(pico, self.painter.sampler, timings=self.timings,
                                        ktx_library=self.document["dependencies"].get("ktx_library"))
        self.gpu_timer, self.gpu_memory = GpuFrameTimer(pico), ProcessGpuMemory()
        self.cache.finish()
        self.memory_before, self.gpu_before = process_memory(), self.gpu_memory.sample()
        if not self.show_metrics:
            self.load_assets()
        self.draw = self.timings.wrap(self.draw, name="frame.cpu_draw")

    def load_assets(self):
        pico = self.pico
        if self.case is None or self.case == "legacy":
            with self.timings.scope("load.legacy_total"):
                self.legacy = PicoMotionSprite(pico, self.source.parent / self.document["cases"]["legacy"]["path"],
                                               easing="linear", blur_strength=0.2, shutter_seconds=0.008,
                                               timings=self.timings)
        if self.case != "legacy":
            self.load_candidate(self.case or self.case_names[self.candidate_index])
        self.loaded_case = self.case or self.case_names[self.candidate_index]
        if self.case == "legacy":
            self.disk_bytes = legacy_disk_size(self.source.parent / self.document["cases"]["legacy"]["path"])
        self.cache.finish()
        gc.collect()
        self.memory_loaded = process_memory()
        self.gpu_loaded = self.gpu_memory.sample()
        self.gpu_memory_samples.append({"frame": 0, **self.gpu_loaded})
        self.assets_loaded = True

    def load_candidate(self, name):
        if self.candidate:
            self.candidate.close()
        source = self.source.parent / self.document["cases"][name]["path"]
        with self.timings.scope("load.atlas_total"):
            self.candidate = PicoMotionAtlas(self.pico, source, self.cache)
        before = self.cache.report()["gpu_storage_bytes"]
        clone = PicoMotionAtlas(self.pico, source, self.cache)
        self.clone_extra_gpu_bytes = self.cache.report()["gpu_storage_bytes"] - before
        clone.close()
        self.loaded_case = name
        from ferrial_drive.rendering.motion_atlas import payload_summary
        self.disk_bytes = payload_summary(source)["disk_bytes"]

    def handle_event(self, event):
        p = self.pico
        if event.type != p.SDL_KEYDOWN:
            return
        if event.key in (p.SDLK_ESCAPE, p.SDLK_q):
            self.running = False
        elif event.key == p.SDLK_SPACE:
            self.paused = not self.paused
        elif event.key == p.SDLK_b:
            self.blur = not self.blur
        elif event.key == p.SDLK_z:
            self.zoom = 2 if self.zoom == 1 else 1
        elif event.key == p.SDLK_c:
            self.instances = {1: 8, 8: 32, 32: 1}[self.instances]
        elif event.key == p.SDLK_TAB:
            self.show_metrics = not self.show_metrics
            if not self.show_metrics and not self.assets_loaded:
                self.load_assets()
        elif event.key in (p.SDLK_LEFT, p.SDLK_RIGHT):
            self.clip_index = (self.clip_index + (-1 if event.key == p.SDLK_LEFT else 1)) % len(self.document["clips"])
            self.phase = 0
        elif event.key in (p.SDLK_COMMA, p.SDLK_PERIOD):
            self.paused = True
            self.phase = max(0, min(1, self.phase + (-0.02 if event.key == p.SDLK_COMMA else 0.02)))
        elif self.case is None and not self.show_metrics and p.SDLK_1 <= event.key <= p.SDLK_6:
            self.candidate_index = min(event.key-p.SDLK_1, len(self.case_names)-1)
            self.load_candidate(self.case_names[self.candidate_index])

    def update(self, delta_seconds):
        self.frame_started = perf_counter()
        if self.quality_directory and self.frame < 6:
            self.phase = (0.15, 0.5, 0.85)[self.frame % 3]
            self.blur = self.frame >= 3
        elif not self.paused:
            self.phase = (self.phase + min(delta_seconds, 0.1)*1.5) % 1

    def draw_resource(self, name, center_x, center_y, *, legacy=False):
        p = self.pico
        smoothstep = name.startswith("combo_")
        if legacy:
            motion = self.legacy.motion_clips[name]
            self.legacy.shutter_seconds = 0.008 if self.blur else 0
            self.legacy.draw(name, min(self.phase, 1-1e-9)*motion.duration_seconds, center_x, center_y,
                              scale=128/202*self.zoom, easing="smoothstep" if smoothstep else "linear")
        else:
            clip = self.candidate.data["clips"][name]
            factor = 128/202 * clip["pixel_scale"] * self.zoom
            width, height = clip["source_size"]
            destination = p.SDL_Rect(round(center_x-clip["pivot"][0]*factor), round(center_y-clip["pivot"][1]*factor),
                                     round(width*factor), round(height*factor))
            self.painter.draw(self.candidate, name, self.phase, destination, blur=self.blur, smoothstep=smoothstep)

    def draw_panel(self, left, legacy):
        r, c = self.ui, self.colors
        r.rect(Rect(left, 150, 640, 560), c["panel"])
        if legacy:
            motion = self.legacy.motion_clips[self.clip_name]
            width, height = motion.pairs[0].width, motion.pairs[0].height
            pivot, pixel_scale, _ = self.legacy.placements[self.clip_name]
        else:
            clip = self.candidate.data["clips"][self.clip_name]
            width, height = clip["source_size"]
            pivot, pixel_scale = clip["pivot"], clip["pixel_scale"]
        factor = 128/202 * pixel_scale * self.zoom
        with r.clip(Rect(left, 150, 640, 560)):
            columns = ceil(self.instances**0.5)
            rows = ceil(self.instances / columns)
            min_x, max_x = left+min(300, pivot[0]*factor), left+640-min(300, (width-pivot[0])*factor)
            min_y, max_y = 150+min(400, pivot[1]*factor), 710-min(150, (height-pivot[1])*factor)
            for index in range(self.instances):
                x = left+320 if self.instances == 1 else min_x+(index % columns)*(max_x-min_x)/max(1, columns-1)
                y = max(470, 160+pivot[1]*factor) if self.instances == 1 else min_y+(index // columns)*(max_y-min_y)/max(1, rows-1)
                self.draw_resource(self.clip_name, x, y, legacy=legacy)

    def draw(self):
        p, r, c = self.pico, self.ui, self.colors
        r.clear(c["background"])
        r.text("텍스처 · 보간 적재 비교", 24, 24, "title", c["text"])
        r.text(self.document["scope"], 24, 58, "small", c["muted"])
        if self.show_metrics:
            self.draw_metrics()
            return
        r.text(f"{self.clip_name}  ·  {self.phase:.2f}  ·  블러 {'켬' if self.blur else '끔'}  ·  {self.instances}개 인스턴스", 24, 86, "body", c["text"])
        p.SDL_RenderFlush(p.renderer)
        self.gpu_timer.begin()
        try:
            if self.case is None:
                self.draw_panel(24, True)
                self.draw_panel(744, False)
            else:
                self.draw_panel(400, self.case == "legacy")
        finally:
            self.gpu_timer.end()
        if self.case is None:
            r.text("기존 클립별 RGBA", 24, 122, "body", c["text"])
            r.text(self.document["cases"][self.loaded_case]["label"], 744, 122, "body", c["accent"])
        else:
            r.text(self.document["cases"][self.case]["label"], 400, 122, "body", c["accent"])
        text = "1 원해상도 아틀라스  ·  2 반해상도  ·  3 KTX2  ·  4 50% Oodle  ·  5 100% Oodle  ·  6 75% Oodle  ·  ←/→ 클립  ·  Space 재생/정지"
        r.text(text, 24, 740, "small", c["text"])
        r.text("Tab 측정표  ·  B 블러  ·  Z 실제 크기/2배  ·  C 1/8/32개  ·  ,/. 위상 이동  ·  Esc 종료", 24, 768, "small", c["muted"])
        report = self.benchmark_summary.get("cases", {}).get(self.loaded_case, {})
        if report:
            memory = report.get("memory_loaded", {})
            gpu = report.get("gpu", {}).get("gpu_storage_bytes", 0)
            first = report.get("first_present_seconds", 0)
            r.text(f"별도 프로세스 측정: 디스크 {report.get('disk_bytes', 0)/2**20:.1f} MiB  ·  GPU Storage {gpu/2**20:.1f} MiB"
                   f"  ·  RAM {memory.get('working_set_bytes', 0)/2**20:.1f} MiB  ·  첫 표시 {first:.3f}초", 24, 803, "small", c["text"])
            vram = report.get("process_gpu_loaded", {})
            vram_text = f"{vram['dedicated_bytes']/2**20:.1f} MiB" if vram.get("available") else "미측정"
            shared_text = f"{vram['shared_bytes']/2**20:.1f} MiB" if vram.get("shared_available") else "미측정"
            r.text(f"전용 VRAM {vram_text} / 공유 GPU {shared_text}  ·  GPU Storage와 별도  ·  {self.document['coverage']}", 24, 832, "small", c["warning"])
        else:
            r.text("측정 결과는 --benchmark로 수집한다. 계산상 텍스처 크기와 실제 프로세스 VRAM은 구분한다.", 24, 816, "small", c["warning"])
        if self.quality_directory and self.frame < 6:
            self.quality_directory.mkdir(parents=True, exist_ok=True)
            from PIL import Image
            area = p.SDL_Rect(464, 194, 512, 512)
            buffer = ct.create_string_buffer(512*512*4)
            if p.SDL_RenderReadPixels(p.renderer, ct.byref(area), p.SDL_PIXELFORMAT_RGBA32, buffer, 512*4):
                raise RuntimeError("품질 비교 화면 읽기 실패")
            filename = f"phase_{self.frame % 3}_blur_{int(self.blur)}.png"
            Image.frombytes("RGBA", (512, 512), buffer.raw).save(self.quality_directory / filename)
            self.captures.append({"file": filename, "phase": self.phase, "blur": self.blur, "clip": self.clip_name})
        if self.capture_path:
            self.capture_path.parent.mkdir(parents=True, exist_ok=True)
            r.save_frame(self.capture_path, *WINDOW_SIZE)
            self.capture_path = None

    def draw_metrics(self):
        r, c = self.ui, self.colors
        cases = self.benchmark_summary.get("cases", {})
        if not cases:
            r.text("측정 결과가 없다. --benchmark 실행 후 다시 연다.", 24, 120, "body", c["warning"])
            return
        positions = (24, 250, 350, 450, 550, 660, 780, 900, 1020, 1130, 1230, 1330)
        headings = ("방식", "Format", "Disk MiB", "RAM MiB", "GPU MiB", "전용/공유", "Read ms", "Decode ms", "Upload ms", "CPU ms", "GPU ms", "첫 표시 s")
        for x, heading in zip(positions, headings):
            r.text(heading, x, 120, "small", c["muted"])
        for index, (name, report) in enumerate(cases.items()):
            y = 160+index*44
            timings = {row["name"]: row["total_ns"]/1e6 for row in report["timings"]["measurements"]}
            formats = {row["internal_format"] for row in report["gpu"]["textures"]}
            format_name = "BC7+RGBA8" if 0x8E8C in formats else "RGBA8"
            gpu_process = report.get("process_gpu_peak_observed", report["process_gpu_loaded"])
            values = (self.document["cases"][name]["label"], format_name,
                      f"{report['disk_bytes']/2**20:.2f}", f"{report['memory_loaded'].get('working_set_bytes', 0)/2**20:.1f}",
                      f"{report['gpu']['gpu_storage_bytes']/2**20:.2f}",
                      (f"{gpu_process['dedicated_bytes']/2**20:.0f}/" +
                       (f"{gpu_process['shared_bytes']/2**20:.0f}" if gpu_process.get("shared_available") else "미측정")) if gpu_process.get("available") else "미측정",
                      f"{timings['load.file_read']:.2f}" if "load.file_read" in timings else "통합 측정",
                      f"{timings['load.decode']:.2f}" if "load.decode" in timings else "통합 측정",
                      f"{timings.get('load.upload_complete', 0):.2f}",
                      f"{report['cpu_frame_ms']['mean']:.3f}" if report['cpu_frame_ms']['mean'] is not None else "미측정",
                      f"{report['gpu_interpolation_ms']['mean']:.3f}" if report['gpu_interpolation_ms']['mean'] is not None else "미측정",
                      f"{report['first_present_seconds']:.3f}")
            for column, (x, value) in enumerate(zip(positions, values)):
                r.text(value, x, y, "small", c["text"], max_width=216 if column == 0 else 105)
        r.text("품질: 기존 방식과 동일한 위상·배경. 움직이는 영역 합집합의 평균 PSNR / SSIM", 24, 460, "body", c["text"])
        for index, (name, samples) in enumerate(self.benchmark_summary.get("quality", {}).items()):
            parts = []
            for blur in (False, True):
                subset = [sample for sample in samples if sample["blur"] == blur]
                finite = [sample["visible_union_psnr_db"] for sample in subset if sample["visible_union_psnr_db"] is not None]
                psnr = f"{mean(finite):.2f} dB" if finite else "동일"
                score = f"{mean(sample['visible_union_ssim'] for sample in subset):.5f}" if subset else "미측정"
                parts.append(f"블러 {'켬' if blur else '끔'}: {psnr} / {score}")
            r.text(f"{self.document['cases'][name]['label']}  ·  " + "    ·    ".join(parts), 24, 493+index*30, "small", c["text"])
        notes = ("실제 GPU Internal Format: BC7 0x8E8C / RGBA8 0x8058. 벡터는 무손실 RGBA8이다.",
                 "GPU Storage는 텍스처 저장량, 전용/공유는 WDDM 주기적 관측 최대(MiB)다. 로딩 전/후·RAM 피크는 JSON에 별도 기록한다.",
                 "기존 방식의 읽기/PNG 디코딩은 통합 측정한다. GPU 프레임은 비교 패널, 업로드는 glFinish 완료 대기를 포함한다.",
                 "각 방식은 별도 프로세스, OS 디스크 캐시는 유지한다. 첫 표시는 Python 진입부터 present 완료까지다.",
                 f"대상 {len(self.document['clips'])}클립 · {next(iter(cases.values())).get('gpu_device', {}).get('renderer', 'GPU 미확인')} · Tab 화면 비교 · Esc 종료",
                 "프레임·VRAM 표본은 지정한 한 클립의 재생 조건이다. 모든 페이지를 동시에 사용한 상주 메모리 검사는 아니다.")
        for index, note in enumerate(notes):
            r.text(note, 24, 716+index*28, "small", c["warning"] if index in (1, 4) else c["muted"])
        if self.capture_path:
            self.capture_path.parent.mkdir(parents=True, exist_ok=True)
            r.save_frame(self.capture_path, *WINDOW_SIZE)
            self.capture_path = None

    def after_present(self):
        self.frame += 1
        if self.first_present_seconds is None:
            self.first_present_seconds = perf_counter()-self.started
        if self.frame > 8:
            self.frame_times.append((perf_counter()-self.frame_started)*1000)
        if self.assets_loaded and (self.frame == 1 or self.frame % 30 == 0):
            self.gpu_memory_samples.append({"frame": self.frame, **self.gpu_memory.sample()})

    def gpu_report(self):
        if self.case != "legacy":
            return self.cache.report()
        textures = []
        s, cache = self.painter.sampler, self.cache
        with s.batch():
            for _, (_, handles) in self.legacy.interpolator.clip_cache.items():
                for handle in handles:
                    cache._bind(handle)
                    row = {}
                    for name, enum in (("internal_format", 0x1003), ("compressed", 0x86A1), ("width", 0x1000), ("height", 0x1001)):
                        value = ct.c_int()
                        cache.query_level(0x0DE1, 0, enum, ct.byref(value))
                        row[name] = value.value
                    row["storage_bytes"] = row["width"]*row["height"]*4
                    row["storage_semantics"] = "GPU 조회 크기의 RGBA8 논리 페이로드"
                    textures.append(row)
        return {"textures": textures, "unique_textures": len(textures),
                "gpu_storage_bytes": sum(row["storage_bytes"] for row in textures)}

    def exit(self):
        if self.cache and self.assets_loaded and self.report_path and self.first_present_seconds is not None:
            self.cache.finish()
            self.gpu_timer.collect()
            frames = self.gpu_timer.samples_ms[8:]
            final_gpu_memory = self.gpu_memory.sample()
            self.gpu_memory_samples.append({"frame": self.frame, **final_gpu_memory})
            valid_gpu = [row for row in self.gpu_memory_samples if row.get("available")]
            shared_gpu = [row["shared_bytes"] for row in valid_gpu if row.get("shared_available")]
            peak_gpu = {"available": bool(valid_gpu),
                        "dedicated_bytes": max((row["dedicated_bytes"] for row in valid_gpu), default=0),
                        "shared_available": bool(shared_gpu), "shared_bytes": max(shared_gpu, default=0),
                        "semantics": "주기적 표본의 전용/공유 각각 최대값. 연속 측정 피크 또는 같은 시점의 합계가 아니다."}
            report = {"version": 1, "case": self.loaded_case, "scope": self.document["scope"],
                      "coverage": self.document["coverage"], "pid": __import__("os").getpid(), "disk_bytes": self.disk_bytes,
                      "memory_before": self.memory_before, "memory_loaded": self.memory_loaded, "memory_end": process_memory(),
                      "process_gpu_before": self.gpu_before, "process_gpu_loaded": self.gpu_loaded,
                      "process_gpu_end": final_gpu_memory, "process_gpu_samples": self.gpu_memory_samples,
                      "process_gpu_peak_observed": peak_gpu,
                      "gpu": self.gpu_report(), "shared_clone_extra_gpu_bytes": self.clone_extra_gpu_bytes,
                      "gpu_device": self.gpu_device,
                      "first_present_seconds": self.first_present_seconds, "frames": self.frame,
                      "cpu_frame_ms": {"mean": mean(self.frame_times) if self.frame_times else None, "samples": len(self.frame_times)},
                      "gpu_interpolation_ms": {"available": self.gpu_timer.available,
                                                "mean": mean(frames) if frames else None, "samples": len(frames)},
                      "timings": self.timings.snapshot(), "quality_captures": self.captures,
                      "notes": ["앞의 8프레임은 GPU/CPU 프레임 평균에서 제외한다.", "업로드 시간은 glFinish 완료 대기를 포함한 CPU 경과 시간이다.",
                                "첫 표시는 Python 테스트 진입부터 present 완료까지다. 프로세스 생성 자체는 포함하지 않는다."]}
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            self.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if self.candidate:
            self.candidate.close()
        if self.legacy:
            self.legacy.close()
        if self.gpu_timer:
            self.gpu_timer.close()
        if self.gpu_memory:
            self.gpu_memory.close()
        if self.painter:
            self.painter.close()
        if self.ui:
            self.ui.close()
