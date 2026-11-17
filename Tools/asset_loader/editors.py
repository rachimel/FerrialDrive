"""Pico2D 메인 루프에서 갱신하는 제작·조립 패널. 별도 창을 열지 않는다."""

from math import isfinite
from pathlib import Path

from ferrial_drive.assets.sprites import SpriteFrame, SpriteClip
from ferrial_drive.ui.components import Rect
from .assembly import SpriteAssembly
from .file_panel import FilePanel
from .library import asset_directory
from .widgets import Panel


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
