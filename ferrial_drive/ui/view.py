"""표현 설정을 사용하는 UI 그리기. 게임 상태 갱신이나 입력 처리는 하지 않는다."""

from math import hypot

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
        style = self.config.data["panel_style"]
        rect = Rect(*rect).translated(offset_x)
        r.rect(rect, c["panel"], opacity * style["fill_opacity"])
        r.rect(rect, c["panel_border"], opacity * style["border_opacity"], filled=False)
        r.line(rect.x, rect.y, rect.x + min(72, rect.width), rect.y, c["accent"], opacity)

    def label(self, key, x, y, role="body", color="text", opacity=1,
              offset_x=0, **kwargs):
        self.renderer.text(self.config.labels[key], x + offset_x, y, role,
                           self.config.colors[color], opacity, **kwargs)

    def buttons(self, scene, input_state, opacity, offset_x, buttons=None):
        r, c = self.renderer, self.config.colors
        for index, button in enumerate(self.config.buttons[scene] if buttons is None else buttons):
            rect = button.rect.translated(offset_x)
            button_opacity = opacity if button.enabled else opacity * 0.45
            hovered = button.enabled and input_state.hovered_id == button.button_id
            pressed = input_state.pressed_id == button.button_id and hovered
            fill = c["panel_pressed"] if pressed else c["panel_hover"] if hovered else c["panel"]
            r.rect(rect, fill, button_opacity)
            r.rect(rect, c["accent"] if hovered else c["line"], button_opacity, filled=False)
            r.rect(Rect(rect.x, rect.y, 3, rect.height), c["accent"],
                   button_opacity if hovered else button_opacity * 0.45)
            if scene == "menu":
                r.text(f"{index + 1:02}", rect.x + 18, rect.y + 19,
                       "small", c["muted"], button_opacity)
            r.text(button.label, rect.x + (54 if scene == "menu" else 16),
                   rect.y + (rect.height - self.config.font_sizes["body"]) / 2 - 2,
                   "body", c["text"], button_opacity,
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

    def gauge(self, layout_key, ratio, opacity, offset_x, color="accent"):
        r, c = self.renderer, self.config.colors
        rect = Rect(*self.config.layout[layout_key]).translated(offset_x)
        r.rect(rect, c["background"], opacity)
        ratio = max(0.0, min(1.0, ratio))
        if ratio > 0:
            r.rect(Rect(rect.x, rect.y, rect.width * ratio, rect.height), c[color], opacity)
        r.rect(rect, c["line"], opacity, filled=False)

    def radar(self, contacts, opacity, offset_x):
        r, c = self.renderer, self.config
        self.panel(c.layout["radar_panel"], opacity, offset_x)
        self.label("radar", *c.layout["radar_heading"], "small", "muted", opacity, offset_x)
        x, y = c.layout["radar_center"]
        x += offset_x
        radius = c.layout["radar_radius"]
        for fraction in (0.5, 1.0):
            r.circle(x, y, radius * fraction, c.colors["line"], opacity)
        r.line(x - radius, y, x + radius, y, c.colors["line"], opacity)
        r.line(x, y - radius, x, y + radius, c.colors["line"], opacity)
        r.text("N", x, y - radius - 16, "small", c.colors["muted"], opacity, align="center")
        for contact in contacts:
            if hypot(contact.x, contact.y) > 1:
                continue
            color = c.colors["enemy" if contact.kind == "enemy" else "accent"]
            r.rect(Rect(x + contact.x * radius - 3, y - contact.y * radius - 3, 6, 6),
                   color, opacity)
        r.line(x - 5, y + 5, x, y - 5, c.colors["text"], opacity)
        r.line(x, y - 5, x + 5, y + 5, c.colors["text"], opacity)

    def placeholder(self, anchor, label, color, opacity, offset_x):
        r, c = self.renderer, self.config.colors
        x, y = anchor
        x += offset_x
        for rect in (Rect(x - 13, y - 46, 26, 17), Rect(x - 22, y - 25, 44, 44),
                     Rect(x - 38, y - 19, 12, 35), Rect(x + 26, y - 19, 12, 35),
                     Rect(x - 20, y + 23, 15, 24), Rect(x + 5, y + 23, 15, 24)):
            r.rect(rect, c["panel"], opacity)
            r.rect(rect, c[color], opacity * 0.8, filled=False)
        r.text(label, x, y + 58, "small", c["muted"], opacity, max_width=180, align="center")

    def combat(self, state, damage_visuals, opacity, offset_x, input_state, buttons=None):
        c, r = self.config, self.renderer
        self.label("combat_heading", *c.layout["combat_heading"], "heading",
                   opacity=opacity, offset_x=offset_x)
        self.label("sample_notice", *c.layout["combat_notice"], "small", "muted", opacity, offset_x)
        self.placeholder(c.layout["player_anchor"], c.labels["player_name"], "accent", opacity, offset_x)
        if state.target is not None:
            self.placeholder(c.layout["target_anchor"], state.target.name, "enemy", opacity, offset_x)
        x, y = c.layout["crosshair_center"]
        x += offset_x
        radius = c.layout["crosshair_radius"]
        r.circle(x, y, radius, c.colors["accent"], opacity * 0.8)
        r.line(x - 18, y, x + 18, y, c.colors["accent"], opacity)
        r.line(x, y - 18, x, y + 18, c.colors["accent"], opacity)
        self.panel(c.layout["player_panel"], opacity, offset_x)
        self.label("player", *c.layout["player_heading"], "small", "muted", opacity, offset_x)
        x, y = c.layout["player_value"]
        r.text(f"{state.player_health.current:g} / {state.player_health.maximum:g}",
               x + offset_x, y, "value", c.colors["text"], opacity, max_width=292)
        self.gauge("player_gauge", state.player_health.ratio, opacity, offset_x)
        self.panel(c.layout["target_panel"], opacity, offset_x)
        self.label("target", *c.layout["target_heading"], "small", "muted", opacity, offset_x)
        if state.target is None:
            self.label("no_target", *c.layout["target_name"], "hud", "muted", opacity, offset_x)
            self.gauge("target_gauge", 0, opacity, offset_x, "enemy")
        else:
            x, y = c.layout["target_name"]
            r.text(state.target.name, x + offset_x, y, "hud", c.colors["text"], opacity, max_width=220)
            x, y = c.layout["target_value"]
            health = state.target.health
            r.text(f"{health.current:g} / {health.maximum:g}", x + offset_x, y,
                   "hud", c.colors["text"], opacity, max_width=150, align="right")
            self.gauge("target_gauge", health.ratio, opacity, offset_x, "enemy")
        x, y = c.layout["combo_value"]
        combo = str(state.combo_count)
        number_width, _ = r.text_size(combo, "combo_number")
        label_y = y + r.text_ascent("combo_number") - r.text_ascent("combo_label")
        r.text(combo, x + offset_x, y, "combo_number", c.colors["accent"], opacity)
        self.label("combo", x + number_width + c.layout["combo_label_gap"], label_y,
                   "combo_label", "muted", opacity, offset_x)
        self.label("damage", *c.layout["damage_heading"], "hud", "muted", opacity, offset_x)
        x, y = c.layout["damage_value"]
        r.text(f"{state.total_damage_dealt:,}", x + offset_x, y,
               "damage_total", c.colors["warning"], opacity, max_width=312)
        self.radar(state.radar_contacts, opacity, offset_x)
        self.buttons("combat", input_state, opacity, offset_x, buttons)
        for visual in damage_visuals:
            r.text(str(visual.amount), visual.x + offset_x, visual.y, "damage_number",
                   c.colors["damage_number"], opacity * visual.opacity, align="center")
