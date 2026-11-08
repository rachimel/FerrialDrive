"""본편·도구·독립 테스트 공통 실행부. 특정 장면이나 도구를 import하지 않는다."""

from ctypes import byref
from math import isfinite
from time import perf_counter, sleep

from .rendering import PicoCanvas


def poll_events(pico, *, accept_text=False):
    """Pico2D 이벤트를 전달하되 FPS 제목 덮어쓰기와 실행기 의존은 피한다."""
    raw = pico.SDL_Event()
    while pico.SDL_PollEvent(byref(raw)):
        event = pico.Event(raw.type)
        if raw.type == pico.SDL_QUIT:
            yield event
        elif raw.type == pico.SDL_WINDOWEVENT:
            event.window_event = raw.window.event
            yield event
        elif raw.type in (pico.SDL_KEYDOWN, pico.SDL_KEYUP):
            if not raw.key.repeat or accept_text:
                event.key = raw.key.keysym.sym
                event.mod = raw.key.keysym.mod
                event.repeat = bool(raw.key.repeat)
                yield event
        elif accept_text and raw.type in (pico.SDL_TEXTINPUT, pico.SDL_TEXTEDITING):
            event.text = bytes(raw.text.text if raw.type == pico.SDL_TEXTINPUT else raw.edit.text).split(b"\0", 1)[0].decode("utf-8", errors="replace")
            yield event
        elif raw.type == pico.SDL_MOUSEMOTION:
            event.x, event.y = raw.motion.x, raw.motion.y
            yield event
        elif raw.type in (pico.SDL_MOUSEBUTTONDOWN, pico.SDL_MOUSEBUTTONUP):
            event.button, event.x, event.y = raw.button.button, raw.button.x, raw.button.y
            event.clicks = raw.button.clicks
            yield event
        elif raw.type == pico.SDL_MOUSEWHEEL:
            event.x, event.y = raw.wheel.x, raw.wheel.y
            yield event


def run_application(program, *, width, height, title, frames_per_second=60, frame_limit=None,
                    timings=None, vsync=False):
    if not isfinite(frames_per_second) or frames_per_second <= 0:
        raise ValueError("초당 프레임 수는 양수여야 한다.")
    if frame_limit is not None and (not isinstance(frame_limit, int) or frame_limit <= 0):
        raise ValueError("프레임 제한은 양수 정수여야 한다.")
    import pico2d.pico2d as pico

    with PicoCanvas(width, height, title, driver=getattr(program, 'render_driver', 'opengl'), vsync=vsync) as canvas:
        for event_type in (pico.SDL_DROPBEGIN, pico.SDL_DROPFILE,
                           pico.SDL_DROPTEXT, pico.SDL_DROPCOMPLETE):
            pico.SDL_EventState(event_type, pico.SDL_DISABLE)
        try:
            program.enter()
            present, frame_wait = canvas.present, sleep
            if timings is not None and timings.enabled:
                present = timings.wrap(present, name="loop.present")
                frame_wait = timings.wrap(frame_wait, name="loop.frame_wait")
            previous_seconds = perf_counter()
            frames = 0
            while program.running:
                frame_start = perf_counter()
                delta_seconds = frame_start - previous_seconds
                previous_seconds = frame_start
                for event in poll_events(pico, accept_text=getattr(program, "accept_text", False)):
                    if event.type == pico.SDL_QUIT:
                        program.running = False
                    else:
                        program.handle_event(event)
                    if not program.running:
                        break
                if not program.running:
                    break
                program.update(delta_seconds)
                if not program.running:
                    break
                program.draw()
                present()
                frames += 1
                if frame_limit is not None and frames >= frame_limit:
                    break
                remaining = 1 / frames_per_second - (perf_counter() - frame_start)
                if remaining > 0:
                    frame_wait(remaining)
        finally:
            program.exit()
