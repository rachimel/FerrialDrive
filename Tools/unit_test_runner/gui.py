"""폴더 탐색·파일 드롭으로 독립 테스트를 실행하는 GUI."""

from importlib.resources import files
from ctypes import byref, c_int
from pathlib import Path
import re
from time import perf_counter, sleep
import traceback

from .events import FilesDropped
from .browser import FileBrowser
from .interface import WindowSpec
from .processes import RunningTest, prepare_test
from .runner import PicoWindow
from .theme import RUNNER_COLORS, RUNNER_FONTS


LAUNCHER_WINDOW = WindowSpec(title="Unit Test Runner | 파일 탐색")
BROWSER_TOP = 124
BROWSER_ROW_HEIGHT = 32
BROWSER_VISIBLE_ROWS = 11


def handle_browser_event(browser, event, pico, width):
    """선택·탐색만 처리하고 실행 요청 경로는 호출자에게 돌려준다."""
    if event.type == pico.SDL_KEYDOWN:
        if event.key == pico.SDLK_UP:
            browser.move_selection(-1)
        elif event.key == pico.SDLK_DOWN:
            browser.move_selection(1)
        elif event.key == pico.SDLK_PAGEUP:
            browser.move_selection(-browser.visible_rows)
        elif event.key == pico.SDLK_PAGEDOWN:
            browser.move_selection(browser.visible_rows)
        elif event.key == pico.SDLK_BACKSPACE:
            browser.navigate(browser.directory.parent)
        elif event.key == pico.SDLK_F5:
            browser.refresh()
        elif event.key in (pico.SDLK_RETURN, pico.SDLK_KP_ENTER):
            return browser.activate()
    elif event.type == pico.SDL_MOUSEWHEEL:
        browser.scroll(-event.y * 3)
    elif event.type == pico.SDL_MOUSEBUTTONDOWN and event.button == pico.SDL_BUTTON_LEFT:
        x, y = event.x, event.y
        if (28 <= x < width - 28
              and BROWSER_TOP <= y < BROWSER_TOP + BROWSER_ROW_HEIGHT * browser.visible_rows):
            index = browser.offset + (y - BROWSER_TOP) // BROWSER_ROW_HEIGHT
            browser.select(index)
            if index < len(browser.entries) and getattr(event, "clicks", 1) >= 2:
                return browser.activate()
    return None


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
        return True

    def close(self):
        if self.child is not None:
            self.child.close()
            self.child = None
        self.path = None


class DropView:
    def __init__(self, backend):
        self.backend = backend
        self.pico = backend.pico
        font_root = Path(__file__).resolve().parents[2] / "data/fonts"
        self.fonts = {}
        try:
            for role, (relative_path, size) in RUNNER_FONTS.items():
                font_path = font_root / relative_path
                if not font_path.is_file():
                    # 툴 폴더만 복사한 독립 실행 환경의 기존 동작을 유지한다.
                    font_path = files("pico2d").joinpath("data", "ConsolaMalgun.ttf")
                self.fonts[role] = self.pico.load_font(str(font_path), size)
        except BaseException:
            self.close()
            raise
        self.error_layout_key = None
        self.error_lines = []

    def _fill(self, x, y, width, height, color):
        pico = self.pico
        pico.SDL_SetRenderDrawColor(pico.renderer, *color, 255)
        pico.SDL_RenderFillRect(pico.renderer, pico.SDL_Rect(x, y, width, height))

    def _label(self, text, x, y, color, max_width, *, role="body"):
        # Pico2D Font.draw의 y는 이미지 세로 중앙이다. 크기 보정을 더하지 않는다.
        self.fonts[role].draw(x, self.backend.spec.height - y,
                              self._fit_text(text, max_width, role), color)

    def _section(self, x, y, width, height, color):
        self._fill(x, y, width, height, color)
        border = RUNNER_COLORS["line"]
        self._fill(x, y, width, 1, border)
        self._fill(x, y + height - 1, width, 1, border)
        self._fill(x, y, 1, height, border)
        self._fill(x + width - 1, y, 1, height, border)

    def _fit_text(self, text, max_width, role="body"):
        if self._text_width(text, role) <= max_width:
            return text
        left, right = 0, len(text)
        while left < right:
            middle = (left + right + 1) // 2
            if self._text_width(text[:middle] + "…", role) <= max_width:
                left = middle
            else:
                right = middle - 1
        return text[:left] + "…"

    def browser(self, browser, active_path=None):
        pico = self.pico
        width, height = self.backend.spec.width, self.backend.spec.height
        colors = RUNNER_COLORS
        pico.SDL_SetRenderDrawColor(pico.renderer, *colors["background"], 255)
        pico.SDL_RenderClear(pico.renderer)
        normal, muted = colors["text"], colors["muted"]
        self._section(16, 12, width - 32, 72, colors["panel_surface"])
        self._section(16, 96, width - 32, 424, colors["panel"])
        self._section(16, 532, width - 32, 108, colors["panel"])
        self._section(16, height - 68, width - 32, 60, colors["panel_surface"])
        self._label("UNIT TEST RUNNER", 32, 32, colors["accent"], width - 64, role="title")
        self._label(browser.directory.as_posix(), 32, 60, normal, width - 64)
        selected = browser.selected
        status_x = width - 290
        self._fill(28, BROWSER_TOP - 1, width - 56, 1, colors["accent"])
        self._label("이름", 44, 110, muted, status_x - 56)
        self._label("실행 상태", status_x, 110, muted, 220)
        for row, entry in enumerate(browser.entries[browser.offset:browser.offset + browser.visible_rows]):
            index, y = browser.offset + row, BROWSER_TOP + row * BROWSER_ROW_HEIGHT
            if index == browser.selected_index:
                self._fill(28, y, width - 56, BROWSER_ROW_HEIGHT, colors["selected"])
                self._fill(28, y, 3, BROWSER_ROW_HEIGHT, colors["accent"])
            self._fill(28, y + BROWSER_ROW_HEIGHT - 1, width - 56, 1, colors["line"])
            color = normal if entry.is_directory or entry.runnable else colors["disabled"]
            prefix = "[폴더] " if entry.is_directory and not entry.is_parent else ""
            self._label(prefix + entry.display_name, 44, y + 16, color, status_x - 64)
            state = "상위 폴더" if entry.is_parent else "폴더 열기" if entry.is_directory else (
                "실행 가능 · " + entry.mode if entry.runnable else "실행 불가")
            self._label(state, status_x, y + 16, color, 230)
        self._fill(status_x - 16, 97, 1, BROWSER_TOP + BROWSER_ROW_HEIGHT * browser.visible_rows - 97,
                   colors["line"])
        if not browser.entries:
            self._label("폴더 또는 .py 파일 없음", 44, BROWSER_TOP + 20, muted, width - 88)
        if len(browser.entries) > browser.visible_rows:
            track_height = BROWSER_ROW_HEIGHT * browser.visible_rows
            thumb_height = max(12, track_height * browser.visible_rows // len(browser.entries))
            thumb_y = BROWSER_TOP + (track_height - thumb_height) * browser.offset // (
                len(browser.entries) - browser.visible_rows)
            self._fill(width - 34, thumb_y, 4, thumb_height, colors["accent"])
        count = sum(not entry.is_parent for entry in browser.entries)
        self._label(f"폴더·.py {count}개  |  더블클릭 / Enter: 열기·실행  |  F5: 새로고침",
                    28, 504, muted, width - 56)
        if selected:
            title = selected.title or selected.display_name
            self._label(title, 28, 548, colors["accent"], width - 56, role="title")
            description = selected.description or (
                "상위 폴더로 이동한다." if selected.is_parent else
                "폴더를 열어 이동한다." if selected.is_directory else "등록된 소개 없음")
            for row, line in enumerate(self._wrap_error(description, width - 56, 2)):
                self._label(line, 28, 575 + row * 24, normal, width - 56)
            status = selected.reason or ("상위 폴더" if selected.is_parent else
                                         "폴더" if selected.is_directory else
                                         "실행 가능 · " + selected.mode)
            self._label(status + "  |  " + selected.display_name,
                        28, 621, muted, width - 56)
        else:
            self._label("테스트 소개", 28, 548, colors["accent"], width - 56, role="title")
            self._label("항목을 선택하면 소개와 실행 가능 여부를 표시한다.",
                        28, 577, muted, width - 56)
        running = "실행 중: " + active_path.name if active_path else "실행 중인 테스트 없음"
        self._label(running, 28, height - 50, colors["text"], width - 56)
        self._label(".py 파일 드롭도 지원 · 새 실행 시 기존 테스트 종료", 28, height - 26, muted, width - 56)

    def _text_width(self, text, role="body"):
        width, height = c_int(), c_int()
        result = self.pico.TTF_SizeUTF8(self.fonts[role].font, text.encode("utf-8"),
                                        byref(width), byref(height))
        return width.value if result == 0 else len(text) * RUNNER_FONTS[role][1]

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
        pico.SDL_SetRenderDrawColor(pico.renderer, *RUNNER_COLORS["error_surface"], 255)
        target = pico.SDL_Rect(0, height - panel_height, width, panel_height)
        pico.SDL_RenderFillRect(pico.renderer, target)
        for index, line in enumerate(lines):
            self._label(line, 40, height - panel_height + 24 + index * 25,
                        RUNNER_COLORS["error"], width - 80)

    def close(self):
        for font in self.fonts.values():
            self.pico.TTF_CloseFont(font.font)
        self.fonts.clear()


def run_gui(*, frame_limit=None, backend=None, view_factory=DropView, browser=None):
    if frame_limit is not None and (not isinstance(frame_limit, int) or frame_limit <= 0):
        raise ValueError("프레임 제한은 양수 정수여야 한다.")
    backend = backend if backend is not None else PicoWindow(accept_files=True)
    backend.open(LAUNCHER_WINDOW)
    session = DropSession()
    view = None
    try:
        browser = browser if browser is not None else FileBrowser(
            Path(__file__).resolve().parents[2] / "tests", BROWSER_VISIBLE_ROWS)
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
                else:
                    path = handle_browser_event(browser, event, backend.pico, backend.spec.width)
                    if path is not None:
                        session.drop((path,))
            if not running:
                break
            if session.poll():
                backend.raise_window()
            view.browser(browser, session.path)
            view.error(session.error or browser.error)
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
