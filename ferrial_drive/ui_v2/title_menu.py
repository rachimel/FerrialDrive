"""타이틀의 세로 아코디언 메뉴. 배경 이미지와 게임 시작 기능은 소유하지 않는다."""

from dataclasses import replace
from math import isfinite

from ferrial_drive.animation import ScalarAnimation, exponential_out
from ferrial_drive.ui.components import Button, Rect


def submenu_buttons(settings):
    return tuple(Button(row["id"], row["action"], row["label"], Rect(*row["rect"]),
                        enabled=row.get("enabled", False)) for row in settings["submenu_buttons"])


class TitleMenuMotion:
    def __init__(self, buttons, settings):
        self.base_buttons = tuple(buttons)
        self.settings = settings
        hover_seconds = settings.get("hover_seconds", .18)
        if not isfinite(hover_seconds) or hover_seconds < 0:
            raise ValueError("호버 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        self.submenu = submenu_buttons(settings)
        self.reset()

    def reset(self):
        self.opened = False
        self.animation = ScalarAnimation(0, 0, 0)
        self.hover_phases = {}

    def toggle(self):
        self.opened = not self.opened
        self.animation = ScalarAnimation(self.expansion, float(self.opened),
                                         self.settings["duration_seconds"])

    @property
    def expansion(self):
        return self.animation.value

    @property
    def buttons(self):
        start_y = next(button.rect.y for button in self.base_buttons if button.action == "toggle_start")
        moved = tuple(replace(button, rect=button.rect.translated(0, self.settings["expand_pixels"] * self.expansion))
                      if button.rect.y > start_y else button for button in self.base_buttons)
        return moved + self.submenu if self.opened and self.animation.finished else moved

    def set_continue_available(self, available):
        self.base_buttons = tuple(replace(button, enabled=available) if button.action == "continue"
                                  else button for button in self.base_buttons)

    def update(self, delta_seconds, hovered_id=None):
        self.animation.update(delta_seconds)
        duration = self.settings.get("hover_seconds", .18)
        for button in self.base_buttons + self.submenu:
            target = float(button.enabled and button.button_id == hovered_id)
            phase = self.hover_phases.get(button.button_id, 0)
            # 표시값을 새 보간의 시작점으로 삼지 않고 같은 시간축을 되감는다.
            self.hover_phases[button.button_id] = (target if duration == 0 else
                max(0, min(1, phase + (1 if target else -1) * delta_seconds / duration)))

    @property
    def hover_amounts(self):
        return {key: exponential_out(phase) for key, phase in self.hover_phases.items()}


def draw_title_menu(view, opacity, offset_x, input_state, expansion, hover_amounts=None):
    config, r = view.config, view.renderer
    settings, c = config.data["title_menu"], config.colors
    if view.pause_logo_path is not None:
        r.image(view.pause_logo_path, Rect(*settings["logo_rect_pixels"]).translated(offset_x), opacity,
                source_rect=Rect(*settings["logo_source_rect_pixels"]))
    else:
        x, y = settings["fallback_logo_position_pixels"]
        r.text(config.labels["menu_title_first"] + " " + config.labels["menu_title_second"],
               x + offset_x, y, settings["font_role"], c["text"], opacity)
    children = submenu_buttons(settings)
    child_ids = {button.button_id for button in children}

    def label(button, role, alpha):
        box = button.rect.translated(offset_x)
        hovered = button.enabled and input_state.hovered_id == button.button_id
        pressed = hovered and input_state.pressed_id == button.button_id
        # SUITE는 위쪽 좌표로 표시한다. 클릭 영역은 글자와 같은 행을 사용한다.
        text_y = box.y + settings["text_top_pixels"] + (1 if pressed else 0)
        hover_ratio = float(hovered) if hover_amounts is None else hover_amounts.get(button.button_id, 0)
        tracking = round(settings.get("hover_tracking_pixels", 12) * hover_ratio)
        r.text(button.label, box.x, text_y, role, view.ui_accent if hovered else c["text"],
               alpha * (1 if button.enabled else settings["disabled_opacity"]),
               max_width=box.width - 40, letter_spacing_pixels=tracking)
        if hovered:
            r.rect(Rect(box.x - 18, text_y + 8, 3, 24), view.ui_accent, alpha)
        if button.action == "toggle_start":
            x, y = box.x + box.width - 28, box.y + box.height / 2
            if expansion > .5:
                view.stroke(((x - 6, y - 3), (x, y + 3), (x + 6, y - 3)), view.ui_accent, alpha, 1.5)
            else:
                view.stroke(((x - 3, y - 6), (x + 3, y), (x - 3, y + 6)), view.ui_accent, alpha, 1.5)

    for button in config.buttons["menu"]:
        if button.button_id not in child_ids:
            label(button, settings["font_role"], opacity)
    if expansion > 0:
        x, y, width, height = settings["submenu_clip_pixels"]
        with r.clip(Rect(x + offset_x, y, width, height * expansion)):
            for button in children:
                label(button, settings["submenu_font_role"], opacity * expansion)
    right, y = settings["version_position_pixels"]
    r.text(settings["version_label"], right + offset_x, y, settings["version_font_role"],
           c["muted"], opacity, align="right")
