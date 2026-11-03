"""파일을 창에 드롭해 독립 테스트를 실행하는 최소 GUI."""

from importlib.resources import files
from pathlib import Path
from textwrap import wrap
from time import perf_counter, sleep
import traceback

from .events import FilesDropped
from .interface import WindowSpec
from .loader import load_test
from .runner import PicoWindow, TestHost


LAUNCHER_WINDOW = WindowSpec(title="Unit Test Runner | Drop .py")


class DropSession:
    def __init__(self, backend, loader=load_test):
        self.backend = backend
        self.loader = loader
        self.host = TestHost()
        self.path: Path | None = None
        self.error = ""

    def drop(self, paths):
        if len(paths) != 1:
            self.error = "테스트 .py 파일 하나만 드롭한다."
            return
        try:
            program, window = self.loader(Path(paths[0]))
        except Exception as error:
            self.error = f"불러오기 실패: {error}"
            traceback.print_exc()
            return
        try:
            self.host.close()
            self.backend.resize(window)
            self.host.switch_to(program)
        except Exception as error:
            self.fail(error)
            return
        self.path = Path(paths[0])
        self.error = ""

    def fail(self, error):
        traceback.print_exc()
        self.error = f"실행 오류: {error}"
        try:
            self.host.close()
        except Exception as cleanup_error:
            self.error += f" / 정리 오류: {cleanup_error}"
            traceback.print_exc()
        self.path = None
        self.backend.resize(LAUNCHER_WINDOW)

    def return_to_idle(self):
        self.path = None
        self.backend.resize(LAUNCHER_WINDOW)


class DropView:
    def __init__(self, backend):
        self.backend = backend
        self.pico = backend.pico
        font_path = files("pico2d").joinpath("data", "ConsolaMalgun.ttf")
        self.font = self.pico.load_font(str(font_path), 22)

    def idle(self):
        pico = self.pico
        width, height = self.backend.spec.width, self.backend.spec.height
        pico.SDL_SetRenderDrawColor(pico.renderer, 12, 22, 29, 255)
        pico.SDL_RenderClear(pico.renderer)
        pico.draw_rectangle(56, 180, width - 56, height - 100, 90, 136, 126)
        self.font.draw(84, height - 64, "UNIT TEST RUNNER", (174, 222, 190))
        self.font.draw(84, height / 2 + 36, "테스트 .py 파일을 이 창에 드롭한다.", (226, 238, 233))
        self.font.draw(84, height / 2 - 8, "파일 하나 / create_test() 실행 규약", (154, 172, 178))
        self.font.draw(84, 138, "테스트 종료 후 이 화면으로 돌아온다.", (154, 172, 178))

    def error(self, message):
        if not message:
            return
        pico = self.pico
        width = self.backend.spec.width
        lines = wrap(message, max(12, (width - 100) // 22))[:4]
        pico.SDL_SetRenderDrawColor(pico.renderer, 28, 16, 19, 255)
        target = pico.SDL_Rect(0, self.backend.spec.height - 120, width, 120)
        pico.SDL_RenderFillRect(pico.renderer, target)
        for index, line in enumerate(lines):
            self.font.draw(40, 100 - index * 25, line, (245, 170, 150))

    def close(self):
        if self.font is not None:
            self.pico.TTF_CloseFont(self.font.font)
            self.font = None


def run_gui(*, frame_limit=None, backend=None, view_factory=DropView):
    if frame_limit is not None and (not isinstance(frame_limit, int) or frame_limit <= 0):
        raise ValueError("프레임 제한은 양수 정수여야 한다.")
    backend = backend if backend is not None else PicoWindow(accept_files=True)
    backend.open(LAUNCHER_WINDOW)
    session = DropSession(backend)
    view = None
    try:
        view = view_factory(backend)
        running = True
        frames = 0
        previous_seconds = perf_counter()
        while running:
            start_seconds = perf_counter()
            delta_seconds = start_seconds - previous_seconds
            previous_seconds = start_seconds
            for event in backend.events():
                if backend.is_close_event(event):
                    running = False
                    break
                if isinstance(event, FilesDropped):
                    previous_program = session.host.current
                    session.drop(event.paths)
                    if session.host.current is not previous_program:
                        previous_seconds = perf_counter()
                        delta_seconds = 0.0
                elif session.host.current is not None:
                    try:
                        session.host.handle_event(event)
                    except Exception as error:
                        session.fail(error)
            if not running:
                break
            if session.host.current is not None:
                try:
                    session.host.update(delta_seconds)
                    session.host.draw()
                except Exception as error:
                    session.fail(error)
            if session.host.current is None:
                if session.path is not None:
                    session.return_to_idle()
                view.idle()
            view.error(session.error)
            backend.present()
            frames += 1
            if frame_limit is not None and frames >= frame_limit:
                break
            remaining_seconds = 1 / backend.spec.frames_per_second - (perf_counter() - start_seconds)
            if remaining_seconds > 0:
                sleep(remaining_seconds)
    finally:
        try:
            session.host.close()
        finally:
            try:
                if view is not None:
                    view.close()
            finally:
                backend.close()
