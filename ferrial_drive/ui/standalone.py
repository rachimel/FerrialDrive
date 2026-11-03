"""Runner와 무관한 UI 미리보기 실행 루프. Pico2D 원본은 수정하지 않는다."""

from ctypes import byref
from math import isfinite
from time import perf_counter, sleep


def _events(pico):
    """Pico2D 이벤트를 전달하되 FPS 제목 덮어쓰기와 실행기 의존은 피한다."""
    raw = pico.SDL_Event()
    while pico.SDL_PollEvent(byref(raw)):
        event = pico.Event(raw.type)
        if raw.type == pico.SDL_QUIT:
            yield event
        elif raw.type in (pico.SDL_KEYDOWN, pico.SDL_KEYUP):
            if not raw.key.repeat:
                event.key = raw.key.keysym.sym
                yield event
        elif raw.type == pico.SDL_MOUSEMOTION:
            event.x, event.y = raw.motion.x, raw.motion.y
            yield event
        elif raw.type in (pico.SDL_MOUSEBUTTONDOWN, pico.SDL_MOUSEBUTTONUP):
            event.button, event.x, event.y = raw.button.button, raw.button.x, raw.button.y
            yield event
        elif raw.type == pico.SDL_MOUSEWHEEL:
            event.x, event.y = raw.wheel.x, raw.wheel.y
            yield event


def run_preview(program, *, width, height, title, frames_per_second=60, frame_limit=None, timings=None):
    if not all(isinstance(value, int) and value > 0 for value in (width, height)):
        raise ValueError("창 크기는 양수인 정수 픽셀이어야 한다.")
    if not isfinite(frames_per_second) or frames_per_second <= 0:
        raise ValueError("초당 프레임 수는 양수여야 한다.")
    if frame_limit is not None and (not isinstance(frame_limit, int) or frame_limit <= 0):
        raise ValueError("프레임 제한은 양수 정수여야 한다.")
    import pico2d.pico2d as pico

    pico.open_canvas(width, height)
    try:
        if not pico.renderer:
            pico.renderer = pico.SDL_CreateRenderer(pico.window, -1, pico.SDL_RENDERER_SOFTWARE)
        if not pico.window or not pico.renderer:
            raise RuntimeError("UI 미리보기 창 또는 렌더러 생성에 실패했다.")
        pico.hide_lattice()
        for event_type in (pico.SDL_DROPBEGIN, pico.SDL_DROPFILE,
                           pico.SDL_DROPTEXT, pico.SDL_DROPCOMPLETE):
            pico.SDL_EventState(event_type, pico.SDL_DISABLE)
        pico.SDL_SetWindowTitle(pico.window, title.encode("utf-8"))
        try:
            program.enter()
            present, frame_wait = pico.update_canvas, sleep
            if timings is not None and timings.enabled:
                present = timings.wrap(present, name="loop.present")
                frame_wait = timings.wrap(frame_wait, name="loop.frame_wait")
            previous_seconds = perf_counter()
            frames = 0
            while program.running:
                frame_start = perf_counter()
                delta_seconds = frame_start - previous_seconds
                previous_seconds = frame_start
                for event in _events(pico):
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
    finally:
        pico.close_canvas()
