"""현재 Pico2D 창의 로고·실제 로딩 단계 표시. 창과 게임 실행 루프는 소유하지 않는다."""

from ctypes import byref

from .components import Rect
from .pico_renderer import PicoRenderer


class LoadingCancelled(Exception):
    pass


class LoadingScreen:
    def __init__(self, pico, window_size, font, settings, logo=None):
        self.pico, self.window_size, self.settings, self.logo = pico, window_size, settings, logo
        self.renderer = PicoRenderer({"body": font}, {"body": settings["font_size"]})
        self.progress = 0

    def show(self, progress, label, *, before_present=None):
        p, r, settings = self.pico, self.renderer, self.settings
        event = p.SDL_Event()
        while p.SDL_PollEvent(byref(event)):
            if event.type == p.SDL_QUIT:
                raise LoadingCancelled()
        self.progress = max(self.progress, min(1, max(0, progress)))
        width, height = self.window_size
        r.clear(settings["background"])
        logo_width = min(settings["logo_width"], width * 0.7)
        logo_height = settings["logo_height"]
        box = Rect((width - logo_width) / 2, height * 0.38 - logo_height / 2, logo_width, logo_height)
        if self.logo is not None:
            r.image(self.logo, box)
        else:
            r.text("FERRIAL DRIVE", width / 2, height * 0.38, "body", settings["text"], align="center", scale=2)
        bar_width = min(settings["bar_width"], width * 0.65)
        left, top = (width - bar_width) / 2, height * 0.64
        r.rect(Rect(left, top, bar_width, settings["bar_height"]), settings["track"])
        r.rect(Rect(left, top, bar_width * self.progress, settings["bar_height"]), settings["accent"])
        r.text("LOADING", left, top - 34, "body", settings["text"])
        r.text(f"{round(self.progress * 100):02d}%", left + bar_width, top - 34, "body", settings["accent"], align="right")
        r.text(label, width / 2, top + 24, "body", settings["muted"], align="center")
        if before_present is not None:
            before_present()
        p.SDL_RenderPresent(p.renderer)

    def close(self):
        self.renderer.close()
