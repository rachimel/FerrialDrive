"""창·실행 루프·화면 교체만 관리한다. 테스트별 표현과 정책은 알지 못한다."""

from ctypes import POINTER, byref, c_void_p, cast, string_at
from pathlib import Path
from time import perf_counter, sleep

from .events import FilesDropped
from .interface import FlowRequest, Stop, SwitchTo, TestProgram, WindowSpec


class TestHost:
    def __init__(self):
        self.current: TestProgram | None = None

    def switch_to(self, program: TestProgram):
        if not isinstance(program, TestProgram):
            raise TypeError("실행 대상은 TestProgram이어야 한다.")
        self.close()
        self.current = program
        try:
            program.enter()
        except BaseException:
            self.close()
            raise

    def apply(self, request: FlowRequest | None):
        if request is None:
            return
        if isinstance(request, SwitchTo):
            self.switch_to(request.program)
        elif isinstance(request, Stop):
            self.close()
        else:
            raise TypeError("반환값은 None, SwitchTo 또는 Stop이어야 한다.")

    def handle_event(self, event: object):
        if self.current is not None:
            self.apply(self.current.handle_event(event))

    def update(self, delta_seconds: float):
        if self.current is not None:
            self.apply(self.current.update(delta_seconds))

    def draw(self):
        if self.current is not None:
            self.current.draw()

    def close(self):
        program, self.current = self.current, None
        if program is not None:
            program.exit()


class PicoWindow:
    def __init__(self, accept_files=False):
        self.pico = None
        self.spec = None
        self.accept_files = accept_files
        self._drop_files = []
        self._drop_active = False

    def open(self, spec: WindowSpec):
        import pico2d.pico2d as pico

        self.pico, self.spec = pico, spec
        self._drop_files.clear()
        self._drop_active = False
        pico.open_canvas(spec.width, spec.height)
        try:
            # SDL dummy 환경에서도 라이브러리 원본 수정 없이 실행한다.
            if not pico.renderer:
                pico.renderer = pico.SDL_CreateRenderer(pico.window, -1, pico.SDL_RENDERER_SOFTWARE)
            if not pico.window or not pico.renderer:
                raise RuntimeError("Pico2D 창 또는 렌더러 생성에 실패했다.")
            pico.hide_lattice()
            for event_type in (pico.SDL_DROPBEGIN, pico.SDL_DROPFILE, pico.SDL_DROPCOMPLETE):
                pico.SDL_EventState(event_type, pico.SDL_ENABLE)
            self._set_title()
        except BaseException:
            self.close()
            raise

    def _set_title(self):
        self.pico.SDL_SetWindowTitle(self.pico.window, self.spec.title.encode("utf-8"))

    def events(self):
        # Pico2D.get_events는 드롭 이벤트를 버리므로 어댑터에서 직접 확장한다.
        # 라이브러리 원본과 전역 함수는 수정하지 않는다.
        pico = self.pico
        events = []
        raw = pico.SDL_Event()
        while pico.SDL_PollEvent(byref(raw)):
            if raw.type in (pico.SDL_DROPBEGIN, pico.SDL_DROPFILE,
                            pico.SDL_DROPTEXT, pico.SDL_DROPCOMPLETE):
                self._collect_drop(raw, events)
                continue
            event = pico.Event(raw.type)
            if raw.type == pico.SDL_QUIT:
                events.append(event)
            elif raw.type in (pico.SDL_KEYDOWN, pico.SDL_KEYUP):
                if not raw.key.repeat:
                    event.key = raw.key.keysym.sym
                    events.append(event)
            elif raw.type == pico.SDL_MOUSEMOTION:
                event.x, event.y = raw.motion.x, raw.motion.y
                events.append(event)
            elif raw.type in (pico.SDL_MOUSEBUTTONDOWN, pico.SDL_MOUSEBUTTONUP):
                event.button = raw.button.button
                event.x, event.y = raw.button.x, raw.button.y
                events.append(event)
            elif raw.type == pico.SDL_MOUSEWHEEL:
                event.x, event.y = raw.wheel.x, raw.wheel.y
                events.append(event)
        if self._drop_files and not self._drop_active:
            self._finish_drop(events)
        return events

    def _collect_drop(self, raw, events):
        pico = self.pico
        value = None
        if raw.type in (pico.SDL_DROPFILE, pico.SDL_DROPTEXT):
            # c_char_p 필드 접근은 bytes로 변환되므로 실제 포인터를 따로 읽는다.
            pointer = cast(byref(raw.drop, type(raw.drop).file.offset), POINTER(c_void_p))[0]
            if pointer:
                try:
                    value = string_at(pointer).decode("utf-8", errors="replace")
                finally:
                    pico.SDL_free(c_void_p(pointer))
        if not self.accept_files or raw.drop.windowID not in (0, pico.SDL_GetWindowID(pico.window)):
            return
        if raw.type == pico.SDL_DROPBEGIN:
            self._drop_files.clear()
            self._drop_active = True
        elif raw.type == pico.SDL_DROPFILE and value:
            self._drop_files.append(Path(value))
        elif raw.type == pico.SDL_DROPCOMPLETE:
            self._drop_active = False
            self._finish_drop(events)

    def _finish_drop(self, events):
        if self._drop_files:
            events.append(FilesDropped(tuple(self._drop_files)))
            self._drop_files.clear()

    def resize(self, spec: WindowSpec):
        if (self.spec.width, self.spec.height) != (spec.width, spec.height):
            self.pico.resize_canvas(spec.width, spec.height)
        self.spec = spec
        self._set_title()

    def is_close_event(self, event):
        return getattr(event, "type", None) == self.pico.SDL_QUIT

    def present(self):
        self.pico.update_canvas()

    def close(self):
        if self.pico is not None:
            pico, self.pico = self.pico, None
            pico.close_canvas()


def run(program: TestProgram, window: WindowSpec | None = None, *,
        frame_limit: int | None = None, backend=None) -> None:
    """frame_limit은 자동 실행 확인용이다. 기본은 종료 요청까지 계속 실행한다."""
    if not isinstance(program, TestProgram):
        raise TypeError("실행 대상은 TestProgram이어야 한다.")
    if frame_limit is not None and (not isinstance(frame_limit, int) or frame_limit <= 0):
        raise ValueError("프레임 제한은 양수 정수여야 한다.")
    window = window if window is not None else WindowSpec()
    backend = backend if backend is not None else PicoWindow()
    host = TestHost()
    backend.open(window)
    try:
        host.switch_to(program)
        previous_seconds = perf_counter()
        frame_count = 0
        while host.current is not None:
            frame_start_seconds = perf_counter()
            delta_seconds = frame_start_seconds - previous_seconds
            previous_seconds = frame_start_seconds
            for event in backend.events():
                if backend.is_close_event(event):
                    host.close()
                else:
                    host.handle_event(event)
                if host.current is None:
                    break
            host.update(delta_seconds)
            if host.current is None:
                break
            host.draw()
            backend.present()
            frame_count += 1
            if frame_limit is not None and frame_count >= frame_limit:
                break
            remaining_seconds = 1 / window.frames_per_second - (perf_counter() - frame_start_seconds)
            if remaining_seconds > 0:
                sleep(remaining_seconds)
    finally:
        try:
            host.close()
        finally:
            backend.close()
