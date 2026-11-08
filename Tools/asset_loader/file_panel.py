"""메인 창 안의 파일 선택·ID 입력. 운영체제의 자식 창을 생성하지 않는다."""

import os
from pathlib import Path

from ferrial_drive.ui.components import Rect
from .widgets import Panel


class FilePanel(Panel):
    title = "파일 열기"

    def __init__(self, app, callback, *, extensions, initial=None, parent=None):
        super().__init__(app, parent=parent)
        self.callback, self.extensions = callback, set(extensions)
        self.directory = Path(initial or Path(__file__).resolve().parents[2]).resolve()
        if not self.directory.is_dir():
            self.directory = self.directory.parent
        self.items, self.offset, self.selected = [], 0, None
        self.add_field("path", self.directory, Rect(144, 146, 992, 36))
        self.focus = "path"
        self.button("상위 폴더", Rect(144, 194, 118, 34), lambda: self.navigate(self.directory.parent))
        self.button("열기", Rect(1016, 660, 120, 36), self.submit)
        self.button("취소", Rect(884, 660, 120, 36), self.close)
        self.refresh()

    def refresh(self):
        entries = [entry for entry in self.directory.iterdir()
                   if entry.is_dir() or entry.suffix.lower() in self.extensions]
        self.items = sorted(entries, key=lambda entry: (not entry.is_dir(), entry.name.casefold()))
        self.offset, self.selected = 0, None

    def navigate(self, path):
        path = Path(path).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("폴더를 찾을 수 없다.")
        old = self.directory
        self.directory = path
        try:
            self.refresh()
        except OSError:
            self.directory = old
            raise
        field = self.fields["path"]
        field.text, field.cursor = str(path), len(str(path))

    def submit(self):
        text = self.value("path").strip('"')
        path = Path(os.path.expandvars(text)).expanduser()
        if not path.is_absolute():
            path = self.directory / path
        path = path.resolve()
        if path.is_dir():
            self.navigate(path)
            return
        if not path.is_file() or path.suffix.lower() not in self.extensions:
            raise ValueError("지원하는 파일을 선택한다.")
        self.app.set_panel(self.parent)
        try:
            self.callback(path)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            self.app.set_panel(self)
            raise

    def content_event(self, event):
        pico = self.app.pico
        if event.type == pico.SDL_MOUSEWHEEL:
            self.offset = max(0, min(max(0, len(self.items) - 12), self.offset - event.y * 3))
        elif event.type == pico.SDL_MOUSEBUTTONDOWN and event.button == pico.SDL_BUTTON_LEFT:
            if Rect(144, 242, 992, 384).contains(event.x, event.y):
                index = self.offset + int((event.y - 242) // 32)
                if index < len(self.items):
                    path = self.items[index]
                    self.selected = path
                    field = self.fields["path"]
                    field.text, field.cursor = str(path), len(str(path))
                    if getattr(event, "clicks", 1) >= 2:
                        self.attempt(self.submit)

    def draw(self):
        super().draw()
        r, colors = self.app.renderer, self.app.theme["colors"]
        for row, path in enumerate(self.items[self.offset:self.offset + 12]):
            y = 242 + row * 32
            if path == self.selected:
                r.rect(Rect(144, y, 992, 30), colors["selected"])
            label = ("▸ " if path.is_dir() else "  ") + path.name
            r.text(label, 154, y + 6, "small", colors["text"], max_width=972)


class IdPanel(Panel):
    title = "에셋 ID"
    rect = Rect(340, 252, 600, 280)

    def __init__(self, app):
        super().__init__(app)
        self.add_field("id", app.asset_id, Rect(364, 326, 552, 36))
        self.focus = "id"
        self.fields["id"].selected = True
        self.button("적용", Rect(796, 472, 120, 36), self.submit)
        self.button("취소", Rect(664, 472, 120, 36), self.close)

    def submit(self):
        from ferrial_drive.assets import AssetDefinition
        AssetDefinition(self.value("id"), "image", self.app.source or Path.cwd())
        self.app.asset_id = self.value("id")
        self.close()
