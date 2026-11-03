"""창·실행 루프·화면 교체만 관리한다. 테스트별 표현과 정책은 알지 못한다."""

from time import perf_counter, sleep

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
    def __init__(self):
        self.pico = None
        self.spec = None

    def open(self, spec: WindowSpec):
        import pico2d.pico2d as pico

        self.pico, self.spec = pico, spec
        pico.open_canvas(spec.width, spec.height)
        try:
            # SDL dummy 환경에서도 라이브러리 원본 수정 없이 실행한다.
            if not pico.renderer:
                pico.renderer = pico.SDL_CreateRenderer(pico.window, -1, pico.SDL_RENDERER_SOFTWARE)
            if not pico.window or not pico.renderer:
                raise RuntimeError("Pico2D 창 또는 렌더러 생성에 실패했다.")
            pico.hide_lattice()
            self._set_title()
        except BaseException:
            self.close()
            raise

    def _set_title(self):
        self.pico.SDL_SetWindowTitle(self.pico.window, self.spec.title.encode("utf-8"))

    def events(self):
        events = self.pico.get_events()
        self._set_title()
        return events

    def is_close_event(self, event):
        return event.type == self.pico.SDL_QUIT

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
