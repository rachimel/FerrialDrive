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


def run_application(program, *, width=None, height=None, title, frames_per_second=60, frame_limit=None,
                    timings=None, vsync=False):
    """앱 팩터리를 받으면 종료 로딩 전에 앱을 놓고 같은 창에서 새 앱을 만들 수 있다."""
    if not isfinite(frames_per_second) or frames_per_second <= 0:
        raise ValueError("초당 프레임 수는 양수여야 한다.")
    if frame_limit is not None and (not isinstance(frame_limit, int) or frame_limit <= 0):
        raise ValueError("프레임 제한은 양수 정수여야 한다.")
    import pico2d.pico2d as pico

    factory = program if callable(program) else None
    if factory is not None:
        program = factory()
        width = program.window_size[0] if width is None else width
        height = program.window_size[1] if height is None else height
    with PicoCanvas(width, height, title, driver=getattr(program, 'render_driver', 'opengl'), vsync=vsync) as canvas:
        if getattr(program, "preview_hidden", False):
            pico.SDL_HideWindow(pico.window)
        for event_type in (pico.SDL_DROPBEGIN, pico.SDL_DROPFILE,
                           pico.SDL_DROPTEXT, pico.SDL_DROPCOMPLETE):
            pico.SDL_EventState(event_type, pico.SDL_DISABLE)
        while True:
            prepare_collection = getattr(program, "prepare_combat_collection", None) if factory is not None else None
            collection = prepare_collection() if prepare_collection else None
            del prepare_collection
            try:
                try:
                    program.enter()
                    recorder = getattr(program, "timings", None) if factory is not None and timings is None else timings
                    frames = _run_frames(program, canvas, frames_per_second, frame_limit, recorder)
                    reload_requested = factory is not None and getattr(program, "reload_on_exit", False)
                finally:
                    program.exit()
                    program = None
                if collection:
                    reload_requested = collection.finish() and reload_requested
            finally:
                if collection:
                    collection.restore()
            if not reload_requested:
                break
            if frame_limit is not None:
                frame_limit -= frames
                if frame_limit <= 0:
                    break
            program = factory()


def _run_frames(program, canvas, frames_per_second, frame_limit, timings):
    pico = canvas.pico
    present, frame_wait = canvas.present, sleep
    if timings is not None and timings.enabled:
        present = timings.wrap(present, name="loop.present")
        frame_wait = timings.wrap(frame_wait, name="loop.frame_wait")
    previous_seconds = perf_counter()
    after_present = getattr(program, "after_present", None)
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
        if after_present is not None:
            after_present()
        frames += 1
        if frame_limit is not None and frames >= frame_limit:
            break
        remaining = 1 / frames_per_second - (perf_counter() - frame_start)
        if remaining > 0:
            frame_wait(remaining)
    return frames
