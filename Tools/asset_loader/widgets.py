"""에셋 로더 화면 안에서만 사용하는 입력 필드와 패널. 별도 창·대기 루프가 없다."""

from ctypes import CFUNCTYPE, c_void_p, cast, string_at
from dataclasses import dataclass

from ferrial_drive.ui.components import Rect


@dataclass
class Field:
    text: str
    rect: Rect
    cursor: int = 0
    selected: bool = False
    composition: str = ""

    def insert(self, text):
        text = text.replace("\r", " ").replace("\n", " ")
        if self.selected:
            self.text, self.cursor, self.selected = "", 0, False
        self.text = self.text[:self.cursor] + text + self.text[self.cursor:]
        self.cursor += len(text)
        self.composition = ""

    def key(self, event, pico):
        key = event.key
        ctrl = getattr(event, "mod", 0) & pico.KMOD_CTRL
        if self.composition and not ctrl:
            return
        if ctrl and key == pico.SDLK_a:
            self.selected, self.cursor = True, len(self.text)
        elif ctrl and key in (pico.SDLK_c, pico.SDLK_x):
            if self.selected:
                pico.SDL_SetClipboardText(self.text.encode("utf-8"))
                if key == pico.SDLK_x:
                    self.text, self.cursor, self.selected = "", 0, False
        elif ctrl and key == pico.SDLK_v:
            get_text = CFUNCTYPE(c_void_p)(cast(pico.SDL_GetClipboardText, c_void_p).value)
            pointer = get_text()
            if pointer:
                try:
                    self.insert(string_at(pointer).decode("utf-8", errors="replace"))
                finally:
                    pico.SDL_free(c_void_p(pointer))
        elif key in (pico.SDLK_LEFT, pico.SDLK_RIGHT, pico.SDLK_HOME, pico.SDLK_END):
            self.selected = False
            if key == pico.SDLK_HOME:
                self.cursor = 0
            elif key == pico.SDLK_END:
                self.cursor = len(self.text)
            else:
                self.cursor = max(0, min(len(self.text), self.cursor + (-1 if key == pico.SDLK_LEFT else 1)))
        elif key in (pico.SDLK_BACKSPACE, pico.SDLK_DELETE):
            if self.selected:
                self.text, self.cursor, self.selected = "", 0, False
            elif key == pico.SDLK_BACKSPACE and self.cursor:
                self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
                self.cursor -= 1
            elif key == pico.SDLK_DELETE:
                self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]


class Panel:
    title = ""
    rect = Rect(120, 82, 1040, 636)
    button_surface = "button"

    def __init__(self, app, *, parent=None):
        self.app, self.parent = app, parent
        self.fields = {}
        self.focus = None
        self.error = ""
        self.buttons = []
        self.button_styles = {}
        self.button_markers = {}
        self.choice_popup = None
        self.close_rect = Rect(self.rect.x + self.rect.width - 48, self.rect.y + 12, 32, 32)

    def add_field(self, name, value, rect):
        self.fields[name] = Field(str(value), rect, len(str(value)))

    def value(self, name):
        return self.fields[name].text.strip()

    def close(self):
        self.app.set_panel(self.parent)

    def button(self, label, rect, callback, *, style=None):
        self.buttons.append((label, rect, callback))
        if style:
            self.button_styles[(rect.x, rect.y)] = style

    def choice(self, label, options, rect, callback):
        """값/표시 이름의 목록을 한 번에 선택한다. 옵션마다 별도 버튼을 늘리지 않는다."""
        def open_choice():
            height = len(options) * 28
            top = min(rect.y + rect.height + 2, 790 - height)
            self.choice_popup = (Rect(rect.x, top, rect.width, height), options, callback)
        self.button(label, rect, open_choice)
        self.button_markers[(rect.x, rect.y)] = "down"

    def disclosure(self, label, rect, callback, *, expanded=False):
        self.button(label, rect, callback)
        self.button_markers[(rect.x, rect.y)] = "down" if expanded else "right"

    def attempt(self, callback):
        try:
            callback()
            self.error = ""
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, StopIteration) as problem:
            self.error = str(problem)

    def handle_event(self, event):
        pico = self.app.pico
        if event.type == pico.SDL_KEYDOWN and event.key == pico.SDLK_F4 and getattr(event, "mod", 0) & pico.KMOD_ALT:
            self.app.running = False
            return
        if self.choice_popup:
            if event.type == pico.SDL_KEYDOWN and event.key == pico.SDLK_ESCAPE:
                self.choice_popup = None
                return
            if event.type == pico.SDL_MOUSEBUTTONDOWN and event.button == pico.SDL_BUTTON_LEFT:
                rect, options, callback = self.choice_popup
                self.choice_popup = None
                if rect.contains(event.x, event.y):
                    value, _ = options[int((event.y - rect.y) // 28)]
                    self.attempt(lambda: callback(value))
                    return
            elif event.type in (pico.SDL_KEYDOWN, pico.SDL_TEXTINPUT, pico.SDL_TEXTEDITING):
                return
        if event.type == pico.SDL_KEYDOWN:
            if event.key == pico.SDLK_ESCAPE:
                self.close()
                return
            if event.key == pico.SDLK_F4 and getattr(event, "mod", 0) & pico.KMOD_ALT:
                self.app.running = False
                return
            if event.key == pico.SDLK_TAB and self.fields:
                names = list(self.fields)
                step = -1 if getattr(event, "mod", 0) & pico.KMOD_SHIFT else 1
                self.focus = names[(names.index(self.focus) + step) % len(names)] if self.focus in names else names[0]
                return
            if event.key in (pico.SDLK_RETURN, pico.SDLK_KP_ENTER):
                if self.focus is None or not self.fields[self.focus].composition:
                    self.attempt(self.submit)
                return
            if self.focus is not None:
                self.fields[self.focus].key(event, pico)
                return
        elif event.type == pico.SDL_TEXTINPUT and self.focus is not None:
            self.fields[self.focus].insert(event.text)
            return
        elif event.type == pico.SDL_TEXTEDITING and self.focus is not None:
            self.fields[self.focus].composition = event.text
            return
        elif event.type == pico.SDL_MOUSEBUTTONDOWN and event.button == pico.SDL_BUTTON_LEFT:
            if self.close_rect.contains(event.x, event.y):
                self.close()
                return
            for name, field in self.fields.items():
                if field.rect.contains(event.x, event.y):
                    self.focus = name
                    field.cursor, field.selected = len(field.text), False
                    return
            self.focus = None
            for _, rect, callback in self.buttons:
                if rect.contains(event.x, event.y):
                    self.attempt(callback)
                    return
        self.content_event(event)

    def submit(self):
        pass

    def content_event(self, event):
        pass

    def update(self, delta_seconds):
        pass

    def draw(self):
        r, colors = self.app.renderer, self.app.theme["colors"]
        r.rect(Rect(0, 0, 1280, 800), colors["background"], opacity=0.88)
        r.rect(self.rect, colors["panel"])
        r.text(self.title, self.rect.x + 24, self.rect.y + 20, "body", colors["text"])
        box = self.close_rect
        r.line(box.x + 9, box.y + 9, box.x + 23, box.y + 23, colors["text"])
        r.line(box.x + 23, box.y + 9, box.x + 9, box.y + 23, colors["text"])
        for name, field in self.fields.items():
            rect, focused = field.rect, name == self.focus
            r.rect(rect, colors["input"])
            r.rect(rect, colors["accent"] if focused else colors["line"], filled=False)
            prefix = r.text_size(field.text[:field.cursor], "small")[0]
            offset = max(0, prefix - rect.width + 24) if focused else 0
            with r.clip(Rect(rect.x + 4, rect.y + 2, rect.width - 8, rect.height - 4)):
                if focused and field.selected:
                    r.rect(Rect(rect.x + 4, rect.y + 3, rect.width - 8, rect.height - 6), colors["selected"])
                r.text(field.text, rect.x + 8 - offset, rect.y + 9, "small", colors["text"])
                if focused:
                    x = rect.x + 8 + prefix - offset
                    r.line(x, rect.y + 7, x, rect.y + rect.height - 7, colors["accent"])
                    if field.composition:
                        r.text(field.composition, x, rect.y + 9, "small", colors["accent"])
            if focused:
                import pico2d.pico2d as pico
                from ctypes import byref
                target = pico.SDL_Rect(round(rect.x), round(rect.y), round(rect.width), round(rect.height))
                pico.SDL_SetTextInputRect(byref(target))
        for label, rect, _ in self.buttons:
            style = self.button_styles.get((rect.x, rect.y), self.button_surface)
            r.rect(rect, colors[style])
            marker = self.button_markers.get((rect.x, rect.y))
            r.text(label, rect.x + 10, rect.y + 8, "small",
                   colors["button_text"] if style == "button" else colors["text"], max_width=rect.width - (36 if marker else 20))
            if marker:
                x, y = rect.x + rect.width - 18, rect.y + rect.height / 2
                points = ((x - 4, y - 2, x, y + 2), (x, y + 2, x + 4, y - 2)) if marker == "down" else (
                    (x - 2, y - 4, x + 2, y), (x + 2, y, x - 2, y + 4))
                for x1, y1, x2, y2 in points:
                    r.line(x1, y1, x2, y2, colors["muted"])
        if self.error:
            r.text(self.error, getattr(self, "error_x", self.rect.x + 24),
                   getattr(self, "error_y", self.rect.y + self.rect.height - 88),
                   "small", colors["error"], max_width=getattr(self, "error_width", self.rect.width - 48))

    def draw_choices(self):
        if self.choice_popup:
            r, colors = self.app.renderer, self.app.theme["colors"]
            rect, options, _ = self.choice_popup
            r.rect(rect, colors["panel"])
            r.rect(rect, colors["line"], filled=False)
            for index, (_, label) in enumerate(options):
                r.text(label, rect.x + 10, rect.y + index * 28 + 6, "small", colors["text"], max_width=rect.width - 20)

    def check(self, rect, label, enabled, *, disabled=False):
        r, colors = self.app.renderer, self.app.theme["colors"]
        color = colors["disabled"] if disabled else colors["text"]
        box = Rect(rect.x, rect.y + 3, 18, 18)
        r.rect(box, colors["input"])
        r.rect(box, color, filled=False)
        if enabled:
            r.line(box.x + 3, box.y + 9, box.x + 7, box.y + 14, color)
            r.line(box.x + 7, box.y + 14, box.x + 15, box.y + 4, color)
        r.text(label, rect.x + 28, rect.y + 3, "small", color)
