"""표현 설정을 사용하는 UI 그리기. 게임 상태 갱신이나 입력 처리는 하지 않는다."""

from .components import Rect


class UiView:
    def __init__(self, config, renderer):
        self.config = config
        self.renderer = renderer

    def background(self):
        r, c = self.renderer, self.config.colors
        width, height = self.config.window["width"], self.config.window["height"]
        r.clear(c["background"])
        for x in range(0, width, 40):
            r.line(x, 0, x, height, c["grid"], 0.65)
        for y in range(0, height, 40):
            r.line(0, y, width, y, c["grid"], 0.65)

    def panel(self, rect, opacity, offset_x=0):
        r, c = self.renderer, self.config.colors
        rect = Rect(*rect).translated(offset_x)
        r.rect(rect, c["panel"], opacity * 0.94)
        r.rect(rect, c["line"], opacity, filled=False)
        r.line(rect.x, rect.y, rect.x + min(72, rect.width), rect.y, c["accent"], opacity)

    def label(self, key, x, y, role="body", color="text", opacity=1,
              offset_x=0, **kwargs):
        self.renderer.text(self.config.labels[key], x + offset_x, y, role,
                           self.config.colors[color], opacity, **kwargs)

    def header(self):
        c, r = self.config, self.renderer
        x, y, width, height = c.layout["header"]
        self.label("brand", x, y, "body")
        self.label("test_badge", x + width, y + 2, "small", "accent", align="right")
        r.line(x, y + height, x + width, y + height, c.colors["line"])

    def buttons(self, scene, input_state, opacity, offset_x):
        r, c = self.renderer, self.config.colors
        for index, button in enumerate(self.config.buttons[scene]):
            rect = button.rect.translated(offset_x)
            hovered = input_state.hovered_id == button.button_id
            pressed = input_state.pressed_id == button.button_id and hovered
            fill = c["panel_pressed"] if pressed else c["panel_hover"] if hovered else c["panel"]
            r.rect(rect, fill, opacity)
            r.rect(rect, c["accent"] if hovered else c["line"], opacity, filled=False)
            r.rect(Rect(rect.x, rect.y, 3, rect.height), c["accent"], opacity if hovered else opacity * 0.45)
            if scene == "menu":
                r.text(f"{index + 1:02}", rect.x + 18, rect.y + 19,
                       "small", c["muted"], opacity)
            r.text(button.label, rect.x + (54 if scene == "menu" else 16),
                   rect.y + (rect.height - self.config.font_sizes["body"]) / 2 - 2,
                   "body", c["text"], opacity,
                   max_width=rect.width - (80 if scene == "menu" else 32))

    def menu(self, opacity, offset_x, input_state):
        c, r = self.config, self.renderer
        x, y = c.layout["menu_title"]
        self.label("menu_title_first", x, y, "title", opacity=opacity, offset_x=offset_x)
        self.label("menu_title_second", x, y + 72, "title", "accent", opacity, offset_x)
        r.line(x + offset_x, y + 168, x + 104 + offset_x, y + 168, c.colors["accent"], opacity)
        self.label("menu_subtitle", x, y + 198, "body", "muted", opacity, offset_x)
        self.panel(c.layout["menu_panel"], opacity, offset_x)
        self.label("menu_heading", *c.layout["menu_heading"], "heading",
                   opacity=opacity, offset_x=offset_x)
        self.label("menu_description", *c.layout["menu_description"], "small", "muted",
                   opacity, offset_x)
        self.label("menu_notice", *c.layout["menu_notice"], "small", "muted", opacity, offset_x)
        self.buttons("menu", input_state, opacity, offset_x)

    def footer(self, scene, transitioning=False):
        x, y, width, _ = self.config.layout["footer"]
        self.label("menu_hint" if scene == "menu" else "combat_hint", x, y,
                   "small", "muted")
        if transitioning:
            self.label("transition", x + width, y, "small", "accent", align="right")
