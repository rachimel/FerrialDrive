"""Pico2D 메인 루프에서 갱신하는 제작·조립 패널. 별도 창을 열지 않는다."""

from math import isfinite
from pathlib import Path

from ferrial_drive.assets.sprites import SpriteFrame, SpriteClip
from ferrial_drive.ui.components import Rect
from .assembly import SpriteAssembly
from .file_panel import FilePanel
from .production import ROOT, render_config, load_render_preset
from .library import asset_directory
from .widgets import Panel


class RenderPanel(Panel):
    title = "3D 프리렌더"
    rect = Rect(192, 88, 896, 624)
    button_surface = "input"
    sample_rect = Rect(216, 548, 380, 28)
    camera_rect = Rect(216, 500, 380, 28)
    automatic_rect = Rect(664, 500, 400, 28)
    sharpen_rect = Rect(664, 548, 380, 28)

    def __init__(self, app, source=None):
        super().__init__(app)
        self.labels = []
        self.sample, self.scene_camera, self.auto_fit = False, False, True
        self.sharpen = True
        self.render_preset = None
        self.add_field("source", source or "", Rect(216, 174, 716, 32))
        self.button("찾기", Rect(944, 174, 120, 32), self.browse)
        definitions = [("asset_id", "에셋 ID", app.asset_id or "model", 216, 242, 400),
            ("root", "모델 루트", "", 664, 242, 400),
            ("animation", "동작 이름", "idle", 216, 306, 400), ("frames", "프레임", "1,3,5,7", 664, 306, 400),
            ("width", "너비 (px)", "240", 216, 418, 120), ("height", "높이 (px)", "240", 352, 418, 120),
            ("fps", "FPS", "8", 488, 418, 128), ("scale", "정사영 범위", "4.5", 664, 418, 184),
            ("samples", "렌더 샘플", "32", 864, 418, 200)]
        for name, label, value, x, y, width in definitions:
            self.labels.append((label, x, y - 20))
            self.add_field(name, value, Rect(x, y, width, 32))
        self.focus = "source"
        self.button("렌더 시작", Rect(924, 656, 140, 32), self.submit, style="button")
        self.button("취소", Rect(812, 656, 100, 32), self.close)
        self.button("출력 설정 불러오기", Rect(216, 656, 220, 32), self.browse_preset)
        self.button("포즈 편집", Rect(448, 656, 136, 32), lambda: app.launch_pose(self.value("source")))

    def load_preset(self, path):
        data, source = load_render_preset(path)
        values = {"asset_id": data["asset_id"], "animation": data["animation_name"],
                  "frames": ",".join(map(str, data["frames"])), "fps": data["fps"],
                  "width": data["frame_size_pixels"][0], "height": data["frame_size_pixels"][1],
                  "scale": data["camera"]["ortho_scale"], "samples": data["render"]["samples"],
                  "root": data.get("root_object", "")}
        if source:
            values["source"] = str(source)
        for key, value in values.items():
            self.fields[key].text = str(value)
            self.fields[key].cursor = len(str(value))
        self.render_preset = data
        self.sample = False
        self.scene_camera = data.get("use_scene_camera", False)
        self.auto_fit = data.get("auto_fit", True)
        self.sharpen = data.get("postprocess", {}).get("sharpen", 0) > 0

    def browse_preset(self):
        self.app.set_panel(FilePanel(self.app, self.load_preset, extensions={".json"},
                                    initial=Path(self.value("source")).parent if self.value("source") else ROOT / "data/models",
                                    parent=self))

    def browse(self):
        def selected(path):
            field = self.fields["source"]
            field.text, field.cursor = str(path), len(str(path))
        self.app.set_panel(FilePanel(self.app, selected, extensions={".blend"},
                                    initial=self.value("source") or ROOT / "data/models", parent=self))

    def submit(self):
        source = None if self.sample else Path(self.value("source").strip('"')).expanduser().resolve()
        if source is not None and (source.suffix.lower() != ".blend" or not source.is_file()):
            raise ValueError("저장된 .blend 모델을 선택한다.")
        config = render_config(asset_id=self.value("asset_id"), animation_name=self.value("animation"),
            frames=self.value("frames"), fps=self.value("fps"), width=self.value("width"),
            height=self.value("height"), ortho_scale=self.value("scale"), samples=self.value("samples"),
            root_object=self.value("root"), use_scene_camera=self.scene_camera, auto_fit=self.auto_fit,
            sharpen=0.35 if self.sharpen else 0)
        if self.render_preset:
            for key in ("position", "target"):
                config["camera"][key] = self.render_preset["camera"][key]
            if self.render_preset.get("extra_root_objects"):
                config["extra_root_objects"] = list(self.render_preset["extra_root_objects"])
        self.app.start_render(source, config)
        self.close()

    def content_event(self, event):
        if event.type == self.app.pico.SDL_MOUSEBUTTONDOWN and event.button == self.app.pico.SDL_BUTTON_LEFT:
            if self.sample_rect.contains(event.x, event.y):
                self.sample = not self.sample
            elif self.camera_rect.contains(event.x, event.y):
                self.scene_camera = not self.scene_camera
                self.auto_fit = not self.scene_camera
            elif self.automatic_rect.contains(event.x, event.y) and not self.scene_camera:
                self.auto_fit = not self.auto_fit
            elif self.sharpen_rect.contains(event.x, event.y):
                self.sharpen = not self.sharpen

    def draw(self):
        super().draw()
        r, colors = self.app.renderer, self.app.theme["colors"]
        r.text("모델 (.blend)", 216, 154, "small", colors["muted"])
        r.text("이미지·재생", 216, 368, "body", colors["text"])
        r.text("카메라·품질", 664, 368, "body", colors["text"])
        for label, x, y in self.labels:
            r.text(label, x, y, "small", colors["text"])
        self.check(self.sample_rect, "기본 도형 샘플", self.sample)
        self.check(self.camera_rect, "모델에 저장된 카메라 사용", self.scene_camera)
        self.check(self.automatic_rect, "기체·그림자 자동 맞춤", self.auto_fit, disabled=self.scene_camera)
        self.check(self.sharpen_rect, "본체 샤프닝", self.sharpen)


class AssemblyPanel(Panel):
    title = "애니메이션 조립"
    rect = Rect(48, 72, 1184, 656)
    timeline = Rect(344, 506, 856, 116)
    preview = Rect(796, 144, 404, 320)
    together_rect = Rect(344, 370, 340, 28)
    playing_rect = Rect(344, 414, 140, 28)

    def __init__(self, app):
        super().__init__(app)
        resource = app.handle.resource
        self.assembly = SpriteAssembly(resource.definition, image_size=resource.sizes["body"])
        self.asset_id = app.asset_id
        self.source_name = app.clip_name
        self.source_offset = self.offset = self.selected = 0
        self.dragging = None
        self.elapsed = 0.0
        self.playing, self.together = True, self.assembly.bundle is not None
        self.labels = []
        for index, (name, label) in enumerate((("name", "동작 이름"), ("duration_ms", "유지 시간 ms"), ("px", "피봇 X"), ("py", "피봇 Y"))):
            y = 154 + index * 50
            self.labels.append((label, 344, y + 9))
            self.add_field(name, "", Rect(452, y, 308, 36))
        self.button("동작 적용", Rect(344, 660, 140, 36), self.apply)
        self.button("전체 시간 적용", Rect(500, 410, 200, 32), lambda: self.set_duration(all_frames=True))
        self.button("스프라이트 저장", Rect(1020, 660, 180, 36), self.submit)
        self.button("취소", Rect(888, 660, 120, 36), self.close)
        self.load_clip(self.source_name)

    def load_clip(self, name):
        self.source_name = name
        row = self.assembly.row(name)
        self.frames = row["frames"]
        self.order = list(range(len(self.frames)))
        self.durations_ms = [frame.get('duration_ms', 1000 / row.get('fps', 1)) for frame in self.frames]
        pivots = {tuple(frame["pivot"]) for frame in self.frames}
        values = {"name": name.rsplit("/", 1)[0], "duration_ms": f'{self.durations_ms[0]:g}',
                  "px": str(self.frames[0]["pivot"][0]) if len(pivots) == 1 else "",
                  "py": str(self.frames[0]["pivot"][1]) if len(pivots) == 1 else ""}
        for key, value in values.items():
            field = self.fields[key]
            field.text, field.cursor, field.selected, field.composition = value, len(value), False, ""
        self.offset = self.selected = 0
        self.elapsed = 0.0

    def set_duration(self, *, all_frames=False):
        duration = float(self.value('duration_ms'))
        if not isfinite(duration) or duration <= 0:
            raise ValueError('유지 시간은 0보다 큰 밀리초다.')
        if self.order:
            if all_frames:
                self.durations_ms = [duration] * len(self.order)
            else:
                self.durations_ms[self.selected] = duration

    def select_frame(self, index):
        self.set_duration()
        self.selected = index
        field = self.fields['duration_ms']
        field.text = f'{self.durations_ms[index]:g}'
        field.cursor = len(field.text)

    def preview_clip(self):
        durations = list(self.durations_ms)
        try:
            value = float(self.value('duration_ms'))
            if isfinite(value) and value > 0:
                durations[self.selected] = value
        except ValueError:
            pass
        return SpriteClip(1, tuple(SpriteFrame(tuple(self.frames[source]['rect']),
                          tuple(self.frames[source]['pivot']), duration)
                          for source, duration in zip(self.order, durations)))

    def apply(self):
        self.set_duration()
        pivot = None if not self.value("px") and not self.value("py") else (float(self.value("px")), float(self.value("py")))
        current = self.assembly.apply(self.source_name, self.value("name"), self.order,
                                      None, pivot, all_directions=self.together, durations_ms=self.durations_ms)
        self.load_clip(current)

    def submit(self):
        self.apply()
        folder = asset_directory(self.asset_id)
        result = self.assembly.save(folder, asset_id=self.asset_id)
        if not self.app.open_source(result, asset_id=self.asset_id):
            raise ValueError(self.app.message)
        self.app.clip_name = self.source_name
        self.close()

    def content_event(self, event):
        pico = self.app.pico
        if event.type == pico.SDL_MOUSEWHEEL:
            if self.app.mouse[0] < 320:
                self.source_offset = max(0, min(max(0, len(self.assembly.names) - 14), self.source_offset - event.y * 3))
            else:
                self.offset = max(0, min(max(0, len(self.order) - 8), self.offset - event.y * 2))
        elif event.type == pico.SDL_MOUSEBUTTONDOWN and event.button == pico.SDL_BUTTON_LEFT:
            if Rect(72, 154, 240, 448).contains(event.x, event.y):
                index = self.source_offset + int((event.y - 154) // 32)
                if index < len(self.assembly.names):
                    self.load_clip(self.assembly.names[index])
            elif self.together_rect.contains(event.x, event.y) and self.assembly.bundle:
                self.together = not self.together
            elif self.playing_rect.contains(event.x, event.y):
                self.playing = not self.playing
            elif self.timeline.contains(event.x, event.y):
                index = self.offset + int((event.x - self.timeline.x) // 104)
                if index < len(self.order):
                    self.attempt(lambda: self.select_frame(index))
                    if self.error:
                        return
                    self.selected, self.dragging, self.playing = index, index, False
        elif event.type == pico.SDL_MOUSEBUTTONUP and event.button == pico.SDL_BUTTON_LEFT and self.dragging is not None:
            if self.timeline.contains(event.x, event.y) and self.order:
                target = min(len(self.order) - 1, self.offset + int((event.x - self.timeline.x) // 104))
                self.order.insert(target, self.order.pop(self.dragging))
                self.durations_ms.insert(target, self.durations_ms.pop(self.dragging))
                self.selected = target
            self.dragging = None
        elif event.type == pico.SDL_KEYDOWN and self.order:
            if event.key == pico.SDLK_DELETE:
                self.order.pop(self.selected)
                self.durations_ms.pop(self.selected)
                self.selected = max(0, min(self.selected, len(self.order) - 1))
                self.offset = min(self.offset, max(0, len(self.order) - 8))
                if self.order:
                    self.fields['duration_ms'].text = f'{self.durations_ms[self.selected]:g}'
            elif event.key == pico.SDLK_d and getattr(event, "mod", 0) & pico.KMOD_CTRL:
                self.attempt(self.set_duration)
                if self.error:
                    return
                self.order.insert(self.selected + 1, self.order[self.selected])
                self.durations_ms.insert(self.selected + 1, self.durations_ms[self.selected])
                self.selected += 1
            elif event.key == pico.SDLK_SPACE:
                self.playing = not self.playing
            elif event.key in (pico.SDLK_LEFT, pico.SDLK_RIGHT):
                self.attempt(lambda: self.select_frame((self.selected + (-1 if event.key == pico.SDLK_LEFT else 1)) % len(self.order)))
                self.playing = False

    def update(self, delta_seconds):
        if self.playing:
            self.elapsed += delta_seconds

    def draw_frame(self, source_index, rect, *, pivot_override=False):
        data = self.frames[source_index]
        pivot = data["pivot"]
        if pivot_override:
            try:
                candidate = (float(self.value("px")), float(self.value("py")))
                if all(isfinite(value) for value in candidate):
                    pivot = candidate
            except ValueError:
                pass
        frame = SpriteFrame(tuple(data["rect"]), tuple(pivot))
        width, height = frame.rect[2:]
        scale = min((rect.width - 24) / width, (rect.height - 24) / height, 4)
        x = rect.x + rect.width / 2 + (pivot[0] - width / 2) * scale
        y = 800 - rect.y - rect.height / 2 + (pivot[1] - height / 2) * scale
        r, colors = self.app.renderer, self.app.theme["colors"]
        with r.clip(rect):
            self.app.handle.resource.draw_frame(frame, x, y, scale=scale)
            if pivot_override:
                r.line(x - 8, 800 - y, x + 8, 800 - y, colors["accent"])
                r.line(x, 800 - y - 8, x, 800 - y + 8, colors["accent"])

    def draw(self):
        super().draw()
        r, colors = self.app.renderer, self.app.theme["colors"]
        r.text("원본 동작 / 방향", 72, 126, "small", colors["muted"])
        for index, name in enumerate(self.assembly.names[self.source_offset:self.source_offset + 14]):
            y = 154 + index * 32
            r.rect(Rect(72, y, 240, 30), colors["selected"] if name == self.source_name else colors["input"])
            r.text(name, 82, y + 6, "small", colors["text"], max_width=220)
        for label, x, y in self.labels:
            r.text(label, x, y, "small", colors["text"])
        self.check(self.together_rect, "모든 방향에 적용", self.together, disabled=self.assembly.bundle is None)
        self.check(self.playing_rect, "재생", self.playing)
        r.rect(self.preview, colors["input"])
        if self.order:
            index = self.preview_clip().frame_at(self.elapsed) if self.playing else self.selected
            self.draw_frame(self.order[index], self.preview, pivot_override=True)
        for index, source in enumerate(self.order[self.offset:self.offset + 8]):
            slot = Rect(self.timeline.x + index * 104, self.timeline.y, 98, 112)
            r.rect(slot, colors["selected"] if self.offset + index == self.selected else colors["input"])
            self.draw_frame(source, Rect(slot.x, slot.y, slot.width, 84))
            duration = f'{self.durations_ms[self.offset + index]:.1f}'.rstrip('0').rstrip('.')
            r.text(f'{source + 1}: {duration}ms', slot.x + 4, slot.y + 88, "small", colors["text"], max_width=90)
        r.text("드래그 순서 변경 · Delete 제외 · Ctrl+D 반복", 344, 476, "small", colors["muted"])
