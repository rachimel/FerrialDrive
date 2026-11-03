"""도형·문구·입력·샘플 시간은 모두 이 테스트 파일에 둔다."""

from importlib.resources import files

from unit_test_runner import Stop, SwitchTo, TestProgram, WindowSpec


WINDOW = WindowSpec(1280, 720, "Unit Test Runner | Basic Flow")


class FlowDemo(TestProgram):
    def __init__(self, page=0):
        self.page = page
        self.elapsed_seconds = 0.0
        self.pico = None
        self.font = None
        self.hovered = None
        self.pressed = None
        self.buttons = ((440, 260, 840, 330), (440, 160, 840, 230))

    def enter(self):
        import pico2d.pico2d as pico

        self.pico = pico
        # 게임 폰트나 에셋 대신 설치된 Pico2D의 기본 폰트를 사용한다.
        font_path = files("pico2d").joinpath("data", "ConsolaMalgun.ttf")
        self.font = pico.load_font(str(font_path), 24)

    def handle_event(self, event):
        pico = self.pico
        if event.type == pico.SDL_KEYDOWN and event.key == pico.SDLK_ESCAPE:
            return SwitchTo(FlowDemo(1 - self.page))
        if event.type not in (pico.SDL_MOUSEMOTION, pico.SDL_MOUSEBUTTONDOWN, pico.SDL_MOUSEBUTTONUP):
            return None
        x, y = event.x, WINDOW.height - 1 - event.y
        self.hovered = next((index for index, (left, bottom, right, top) in enumerate(self.buttons)
                             if left <= x <= right and bottom <= y <= top), None)
        if event.type == pico.SDL_MOUSEBUTTONDOWN and event.button == pico.SDL_BUTTON_LEFT:
            self.pressed = self.hovered
        elif event.type == pico.SDL_MOUSEBUTTONUP and event.button == pico.SDL_BUTTON_LEFT:
            pressed, self.pressed = self.pressed, None
            if pressed is not None and pressed == self.hovered:
                return SwitchTo(FlowDemo(1 - self.page)) if pressed == 0 else Stop()
        return None

    def update(self, delta_seconds):
        self.elapsed_seconds += delta_seconds

    def draw(self):
        pico = self.pico
        accent = (150, 222, 193) if self.page == 0 else (236, 186, 118)
        pico.SDL_SetRenderDrawColor(pico.renderer, 12, 22, 29, 255)
        pico.SDL_RenderClear(pico.renderer)
        pico.draw_line(80, 610, 1200, 610, *accent)
        self.font.draw(80, 650, "공통 실행기 / 독립 흐름 테스트", accent)
        self.font.draw(440, 500, "시작 화면" if self.page == 0 else "두 번째 화면", (228, 238, 235))
        self.font.draw(440, 450, f"화면 경과 시간: {self.elapsed_seconds:.1f}초", (154, 172, 178))
        self.font.draw(440, 405, "화면 전환 테스트", (154, 172, 178))
        labels = ("다음 화면" if self.page == 0 else "이전 화면", "종료")
        for index, (left, bottom, right, top) in enumerate(self.buttons):
            color = accent if self.hovered == index else (73, 101, 111)
            pico.draw_rectangle(left, bottom, right, top, *color)
            if self.pressed == index and self.hovered == index:
                pico.draw_rectangle(left + 3, bottom + 3, right - 3, top - 3, *accent)
            self.font.draw(left + 28, (bottom + top) / 2, labels[index], (228, 238, 235))
        self.font.draw(80, 60, "Esc: 화면 전환    마우스 좌클릭: 버튼 선택    창 X: 종료", (154, 172, 178))

    def exit(self):
        if self.font is not None:
            self.pico.TTF_CloseFont(self.font.font)
            self.font = None


def create_test():
    return FlowDemo()
