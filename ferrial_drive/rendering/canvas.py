"""Pico2D 원본을 유지하며 SDL OpenGL 캔버스의 수명을 관리한다."""

from contextlib import contextmanager
from ctypes import byref, c_int
from dataclasses import dataclass
import os


_active_canvas = None


@contextmanager
def prepare_output_resolution(resolution, logical_size):
    """출력 크기를 준비하고 저장 실패 시 이전 창·논리 크기로 복귀한다."""
    canvas = _active_canvas
    if resolution is None or canvas is None:
        yield lambda: None
        return
    previous = (canvas.width, canvas.height), canvas.logical_size
    canvas.resize_output(*resolution, logical_size=logical_size)
    committed = False

    def commit():
        nonlocal committed
        committed = True

    try:
        yield commit
    finally:
        if not committed:
            canvas.resize_output(*previous[0], logical_size=previous[1])


def apply_output_resolution(resolution, logical_size):
    with prepare_output_resolution(resolution, logical_size) as commit:
        commit()


@dataclass(frozen=True)
class RendererInfo:
    name: str
    accelerated: bool
    vsync_flag: bool
    target_textures: bool


def renderer_info(pico):
    info = pico.SDL_RendererInfo()
    if pico.SDL_GetRendererInfo(pico.renderer, byref(info)) != 0:
        raise RuntimeError('렌더러 정보 조회 실패')
    return RendererInfo(info.name.decode('utf-8'), bool(info.flags & pico.SDL_RENDERER_ACCELERATED),
                        bool(info.flags & pico.SDL_RENDERER_PRESENTVSYNC),
                        bool(info.flags & pico.SDL_RENDERER_TARGETTEXTURE))


def renderer_name(pico):
    return renderer_info(pico).name


class PicoCanvas:
    """한 프로세스의 렌더 스레드에서 사용한다. 에셋은 캔버스보다 먼저 닫는다."""

    def __init__(self, width, height, title, *, driver='opengl', vsync=False):
        if not all(type(value) is int and value > 0 for value in (width, height)):
            raise ValueError('창 크기는 양수인 정수 픽셀이어야 한다.')
        if not isinstance(title, str) or not title or '\0' in title:
            raise ValueError('창 제목은 비어 있지 않은 문자열이어야 한다.')
        if driver is not None and (not isinstance(driver, str) or not driver or '\0' in driver):
            raise ValueError('렌더 드라이버 이름 오류')
        if type(vsync) is not bool:
            raise ValueError('vsync는 bool이어야 한다.')
        self.width, self.height, self.title = width, height, title
        self.logical_size = width, height
        self.driver, self.vsync = driver, vsync
        self.pico = self.info = None
        self.opened = False

    def open(self):
        global _active_canvas
        if self.opened:
            return self
        if _active_canvas is not None:
            raise RuntimeError('Pico2D 캔버스는 한 번에 하나만 열 수 있다.')
        import pico2d.pico2d as pico

        self.pico = pico
        driver = None if os.environ.get('SDL_VIDEODRIVER') == 'dummy' else self.driver
        previous = pico.SDL_GetHint(pico.SDL_HINT_RENDER_DRIVER)
        try:
            if os.name == 'nt':
                # 비디오 초기화 전에 지정한다. SDL 좌표를 물리 픽셀로 유지한다.
                pico.SDL_SetHint(pico.SDL_HINT_WINDOWS_DPI_AWARENESS, b'permonitorv2')
                pico.SDL_SetHint(pico.SDL_HINT_WINDOWS_DPI_SCALING, b'0')
            if driver:
                pico.SDL_SetHint(pico.SDL_HINT_RENDER_DRIVER, driver.encode('utf-8'))
            pico.open_canvas(self.width, self.height, sync=self.vsync)
            # Pico2D의 일부 버전은 null 포인터의 None 검사로 fallback을 놓친다.
            if not pico.renderer and pico.window:
                pico.SDL_ResetHint(pico.SDL_HINT_RENDER_DRIVER)
                pico.renderer = pico.SDL_CreateRenderer(pico.window, -1, pico.SDL_RENDERER_SOFTWARE)
            if not pico.window or not pico.renderer:
                raise RuntimeError('Pico2D 창 또는 렌더러 생성 실패')
            self.info = renderer_info(pico)
            pico.hide_lattice()
            pico.SDL_SetWindowTitle(pico.window, self.title.encode('utf-8'))
        except BaseException:
            try:
                pico.close_canvas()
            finally:
                pico.renderer = pico.window = None
            raise
        finally:
            if previous is None:
                pico.SDL_ResetHint(pico.SDL_HINT_RENDER_DRIVER)
            else:
                pico.SDL_SetHint(pico.SDL_HINT_RENDER_DRIVER, previous)
        self.opened = True
        _active_canvas = self
        return self

    def present(self):
        if not self.opened:
            raise RuntimeError('닫힌 캔버스다.')
        self.pico.update_canvas()

    def resize_output(self, width, height, *, logical_size):
        """UI·월드 논리 좌표를 유지하며 실제 출력 픽셀 수와 창 크기를 바꾼다."""
        if not self.opened:
            raise RuntimeError('닫힌 캔버스다.')
        if not all(type(value) is int and value > 0 for value in (width, height, *logical_size)):
            raise ValueError('출력·논리 크기는 양수 정수 픽셀이어야 한다.')
        p = self.pico
        if p.SDL_RenderFlush(p.renderer) != 0:
            raise RuntimeError('해상도 변경 전 렌더 제출 실패')
        previous = (self.width, self.height), self.logical_size
        p.SDL_SetWindowSize(p.window, width, height)
        if p.SDL_RenderSetLogicalSize(p.renderer, *logical_size) != 0:
            p.SDL_SetWindowSize(p.window, *previous[0])
            p.SDL_RenderSetLogicalSize(p.renderer, *previous[1])
            raise RuntimeError('화면 해상도 적용 실패')
        actual_width, actual_height = c_int(), c_int()
        p.SDL_GetWindowSize(p.window, byref(actual_width), byref(actual_height))
        self.width, self.height = actual_width.value, actual_height.value
        self.logical_size = tuple(logical_size)

    def close(self):
        global _active_canvas
        if self.opened:
            try:
                self.pico.close_canvas()
            finally:
                self.pico.renderer = self.pico.window = None
                self.opened = False
                _active_canvas = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *_):
        self.close()
