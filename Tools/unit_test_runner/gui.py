"""파일을 창에 드롭해 독립 테스트를 실행하는 최소 GUI."""

from importlib.resources import files
from ctypes import byref, c_int
from pathlib import Path
import re
from time import perf_counter, sleep
import traceback

from .events import FilesDropped
from .interface import WindowSpec
from .processes import RunningTest, prepare_test
from .runner import PicoWindow


LAUNCHER_WINDOW = WindowSpec(title="Unit Test Runner | Drop .py")


def summarize_failure(detail):
    """실제 예외를 먼저 표시하고 긴 traceback 경로는 짧은 위치로 분리한다."""
    lines = [line for line in detail.splitlines() if line.strip()]
    if not lines:
        return "오류 출력 없음"
    summary = next((line.strip() for line in reversed(lines)
                    if re.match(r"^[\w.]*(?:Error|Exception|Exit|Interrupt)(?::|$)", line)),
                   lines[-1].strip())
    for line in reversed(lines):
        location = re.match(r'\s*File "([^"]+)", line (\d+)', line)
        if location:
            filename = location.group(1).replace("\\", "/").rsplit("/", 1)[-1]
            return f"{summary}\n위치: {filename}:{location.group(2)}"
    return summary


class DropSession:
    def __init__(self, *, prepare=None, start=None):
        self.prepare = prepare if prepare is not None else prepare_test
        self.start = start if start is not None else RunningTest.start
        self.child = None
        self.path: Path | None = None
        self.error = ""
        self.error_detail = ""

    def drop(self, paths):
        if len(paths) != 1:
            self.error = "테스트 .py 파일 하나만 드롭한다."
            return
        try:
            plan = self.prepare(Path(paths[0]))
        except Exception as error:
            self.error = f"불러오기 실패: {error}"
            traceback.print_exc()
            return
        try:
            self.close()
            self.child = self.start(plan)
        except Exception as error:
            self.error = f"실행 시작 실패: {error}"
            traceback.print_exc()
            return
        self.path = plan.path
        self.error = ""
        self.error_detail = ""

    def poll(self):
        if self.child is None:
            return
        exit_code = self.child.poll()
        if exit_code is None:
            return
        detail = self.child.output_tail() if exit_code else ""
        self.close()
        if exit_code:
            self.error_detail = detail
            self.error = f"테스트 실행 오류 ({exit_code}): {summarize_failure(detail)}"

    def close(self):
        if self.child is not None:
            self.child.close()
            self.child = None
        self.path = None


class DropView:
    def __init__(self, backend):
        self.backend = backend
        self.pico = backend.pico
        font_path = files("pico2d").joinpath("data", "ConsolaMalgun.ttf")
        self.font = self.pico.load_font(str(font_path), 22)
        self.error_layout_key = None
        self.error_lines = []

    def idle(self, active_path=None):
        pico = self.pico
        width, height = self.backend.spec.width, self.backend.spec.height
        pico.SDL_SetRenderDrawColor(pico.renderer, 12, 22, 29, 255)
        pico.SDL_RenderClear(pico.renderer)
        pico.draw_rectangle(56, 180, width - 56, height - 100, 90, 136, 126)
        self.font.draw(84, height - 64, "UNIT TEST RUNNER", (174, 222, 190))
        self.font.draw(84, height / 2 + 36, "테스트 .py 파일을 이 창에 드롭한다.", (226, 238, 233))
        self.font.draw(84, height / 2 - 8, "파일 하나 / 별도 테스트 창 실행", (154, 172, 178))
        if active_path is not None:
            self.font.draw(84, height / 2 - 52, f"실행 중: {active_path.name}", (226, 238, 233))
        self.font.draw(84, 138, "다시 드롭하면 기존 테스트를 종료하고 새로 실행한다.", (154, 172, 178))

    def _text_width(self, text):
        width, height = c_int(), c_int()
        result = self.pico.TTF_SizeUTF8(self.font.font, text.encode("utf-8"),
                                        byref(width), byref(height))
        return width.value if result == 0 else len(text) * 22

    def _wrap_error(self, message, max_width, max_lines):
        lines = []
        for paragraph in message.splitlines():
            current = ""
            for char in paragraph:
                if current and self._text_width(current + char) > max_width:
                    lines.append(current)
                    current = ""
                current += char
            lines.append(current)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            last = lines[-1]
            while last and self._text_width(last + "…") > max_width:
                last = last[:-1]
            lines[-1] = last + "…"
        return lines

    def error(self, message):
        if not message:
            return
        pico = self.pico
        width, height = self.backend.spec.width, self.backend.spec.height
        key = (message, width, height)
        if key != self.error_layout_key:
            max_lines = max(1, min(6, (height - 40) // 25))
            self.error_lines = self._wrap_error(message, max(1, width - 80), max_lines)
            self.error_layout_key = key
        lines = self.error_lines
        panel_height = min(height, max(120, len(lines) * 25 + 32))
        pico.SDL_SetRenderDrawColor(pico.renderer, 28, 16, 19, 255)
        target = pico.SDL_Rect(0, height - panel_height, width, panel_height)
        pico.SDL_RenderFillRect(pico.renderer, target)
        for index, line in enumerate(lines):
            self.font.draw(40, panel_height - 24 - index * 25, line, (245, 170, 150))

    def close(self):
        if self.font is not None:
            self.pico.TTF_CloseFont(self.font.font)
            self.font = None


def run_gui(*, frame_limit=None, backend=None, view_factory=DropView):
    if frame_limit is not None and (not isinstance(frame_limit, int) or frame_limit <= 0):
        raise ValueError("프레임 제한은 양수 정수여야 한다.")
    backend = backend if backend is not None else PicoWindow(accept_files=True)
    backend.open(LAUNCHER_WINDOW)
    session = DropSession()
    view = None
    try:
        view = view_factory(backend)
        running = True
        frames = 0
        while running:
            start_seconds = perf_counter()
            for event in backend.events():
                if backend.is_close_event(event):
                    running = False
                    break
                if isinstance(event, FilesDropped):
                    session.drop(event.paths)
            if not running:
                break
            session.poll()
            view.idle(session.path)
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
            session.close()
        finally:
            try:
                if view is not None:
                    view.close()
            finally:
                backend.close()
