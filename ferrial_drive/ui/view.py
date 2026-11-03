"""표현 설정을 사용하는 UI 그리기. 게임 상태 갱신이나 입력 처리는 하지 않는다."""

from math import hypot

from .components import Rect
from .counter import CounterVisual


class UiView:
    def __init__(self, config, renderer):
        self.config = config
        self.renderer = renderer
        self.ui_accent = config.colors.get("ui_accent", config.colors["accent"])

    def background(self):
        r, c = self.renderer, self.config.colors
        width, height = self.config.window["width"], self.config.window["height"]
        r.clear(c["background"])
        for x in range(0, width, 40):
            r.line(x, 0, x, height, c["grid"], 0.65)
        for y in range(0, height, 40):
            r.line(0, y, width, y, c["grid"], 0.65)

    def panel(self, rect, opacity, offset_x=0, *, fill_opacity=None):
        r, c = self.renderer, self.config.colors
        style = self.config.data["panel_style"]
        rect = Rect(*rect).translated(offset_x)
        fill = style["fill_opacity"] if fill_opacity is None else fill_opacity
        color = c.get("panel_surface", c["panel"])
        metal = style.get("metallic", {})
        if metal.get("enabled", False):
            r.metallic_rect(rect, color, opacity * fill, contrast=metal["contrast"],
                            highlight_center=metal.get("highlight_center", (0.5, 1.15)),
                            highlight_radius=metal.get("highlight_radius", (1.25, 1.3)))
        else:
            r.rect(rect, color, opacity * fill)
        r.rect(rect, c["panel_border"], opacity * style["border_opacity"], filled=False)
        r.line(rect.x, rect.y, rect.x + min(72, rect.width), rect.y, self.ui_accent, opacity)

    def label(self, key, x, y, role="body", color="text", opacity=1,
              offset_x=0, **kwargs):
        self.renderer.text(self.config.labels[key], x + offset_x, y, role,
                           self.config.colors[color], opacity, **kwargs)

    def buttons(self, scene, input_state, opacity, offset_x, buttons=None):
        r, c = self.renderer, self.config.colors
        body_role = "hud_body" if scene == "combat" else "body"
        palette = "hud_button" if scene == "combat" else "menu_button"
        normal_fill = c.get(palette, c["panel"])
        hover_fill = c.get(f"{palette}_hover", c["panel_hover"])
        pressed_fill = c.get(f"{palette}_pressed", c["panel_pressed"])
        text_color = c.get(f"{palette}_text", c["text"])
        marker_color = self.ui_accent if scene == "combat" else text_color
        for index, button in enumerate(self.config.buttons[scene] if buttons is None else buttons):
            rect = button.rect.translated(offset_x)
            button_opacity = opacity if button.enabled else opacity * 0.45
            hovered = button.enabled and input_state.hovered_id == button.button_id
            pressed = input_state.pressed_id == button.button_id and hovered
            fill = pressed_fill if pressed else hover_fill if hovered else normal_fill
            r.rect(rect, fill, button_opacity)
            r.rect(rect, marker_color if hovered else c["line"], button_opacity, filled=False)
            r.rect(Rect(rect.x, rect.y, 3, rect.height), marker_color,
                   button_opacity if hovered else button_opacity * 0.45)
            if scene == "menu":
                index_y = rect.y + (rect.height - self.config.font_sizes["button_index"]) / 2 - 2
                r.text(f"{index + 1:02}", rect.x + 18, index_y,
                       "button_index", text_color, button_opacity)
            r.text(button.label, rect.x + (54 if scene == "menu" else 16),
                   rect.y + (rect.height - self.config.font_sizes[body_role]) / 2 - 2,
                   body_role, text_color, button_opacity,
                   max_width=rect.width - (80 if scene == "menu" else 32))

    def menu(self, opacity, offset_x, input_state):
        c, r = self.config, self.renderer
        x, y = c.layout["menu_title"]
        self.label("menu_title_first", x, y, "title", opacity=opacity, offset_x=offset_x)
        r.text(c.labels["menu_title_second"], x + offset_x, y + 72, "title", self.ui_accent, opacity)
        r.line(x + offset_x, y + 168, x + 104 + offset_x, y + 168, self.ui_accent, opacity)
        self.label("menu_subtitle", x, y + 198, "body", "muted", opacity, offset_x)
        self.panel(c.layout["menu_panel"], opacity, offset_x)
        self.label("menu_heading", *c.layout["menu_heading"], "heading",
                   opacity=opacity, offset_x=offset_x)
        self.label("menu_description", *c.layout["menu_description"], "small", "muted",
                   opacity, offset_x)
        self.label("menu_notice", *c.layout["menu_notice"], "small", "muted", opacity, offset_x)
        self.buttons("menu", input_state, opacity, offset_x)

    def pause(self, opacity, input_state):
        c = self.config
        self.renderer.rect(Rect(0, 0, c.window["width"], c.window["height"]),
                           c.colors["background"], opacity * c.data["pause"]["dim_opacity"])
        self.panel(c.layout["pause_panel"], opacity,
                   fill_opacity=c.data["pause"]["panel_fill_opacity"])
        self.label("pause_heading", *c.layout["pause_heading"], "pause_heading", opacity=opacity)
        self.buttons("pause", input_state, opacity, 0)

    def gauge(self, layout_key, ratio, opacity, offset_x, color="accent", trailing_ratio=None):
        r, c = self.renderer, self.config.colors
        rect = Rect(*self.config.layout[layout_key]).translated(offset_x)
        r.rect(rect, c["background"], opacity)
        ratio = max(0.0, min(1.0, ratio))
        trail = ratio if trailing_ratio is None else max(ratio, min(1.0, trailing_ratio))
        if trail > ratio:
            r.rect(Rect(rect.x + rect.width * ratio, rect.y, rect.width * (trail - ratio), rect.height),
                   c["health_loss"], opacity)
        if ratio > 0:
            r.rect(Rect(rect.x, rect.y, rect.width * ratio, rect.height), c[color], opacity)
        r.rect(rect, c["line"], opacity, filled=False)

    def radar(self, contacts, opacity):
        r, c = self.renderer, self.config
        settings = c.data["radar"]
        x, y = c.actor_anchor("player")
        radius = settings["radius_pixels"]
        distance_limit = settings["range_units"]
        length = settings["arrow_length_pixels"]
        half_width = settings["arrow_half_width_pixels"]
        min_scale = settings.get("arrow_min_scale", 0.45)
        min_opacity = settings.get("arrow_min_opacity", 0.3)
        thickness = settings["ring_thickness_pixels"]
        r.ring(x, y, radius, thickness, c.colors["accent"], opacity * settings["ring_opacity"])
        for contact in contacts:
            distance = hypot(contact.x, contact.y)
            if contact.kind != "enemy" or distance == 0 or distance > distance_limit:
                continue
            screen_dx, screen_dy = contact.screen_x - x, contact.screen_y - y
            screen_distance = hypot(screen_dx, screen_dy)
            if screen_distance <= radius:
                continue
            distance_ratio = min(1.0, distance / distance_limit)
            scale = 1.0 + (min_scale - 1.0) * distance_ratio
            arrow_opacity = opacity * (1.0 + (min_opacity - 1.0) * distance_ratio)
            direction_x, direction_y = screen_dx / screen_distance, screen_dy / screen_distance
            tip_x, tip_y = x + direction_x * radius, y + direction_y * radius
            base_x = tip_x - direction_x * length * scale
            base_y = tip_y - direction_y * length * scale
            side_x, side_y = -direction_y * half_width * scale, direction_x * half_width * scale
            color = c.colors["enemy"]
            r.filled_triangle((tip_x, tip_y), (base_x + side_x, base_y + side_y),
                              (base_x - side_x, base_y - side_y), color, arrow_opacity)

    def player_health_bar(self, state, opacity, trailing_ratio=None):
        r, c = self.renderer, self.config
        settings = c.data["player_hp_bar"]
        x, y = c.actor_anchor("player")
        width, height = settings["width_pixels"], settings["height_pixels"]
        x -= state.attack_direction_x * settings["side_offset_pixels"]
        rect = Rect(x - width / 2, y - height / 2, width, height)
        r.rect(rect, c.colors["background"], opacity)
        ratio = state.player_health.ratio
        fill_height = (height - 2) * ratio
        trail = ratio if trailing_ratio is None else max(ratio, min(1.0, trailing_ratio))
        trail_height = (height - 2) * trail
        if trail_height > fill_height:
            r.rect(Rect(rect.x + 1, rect.y + height - 1 - trail_height,
                        width - 2, trail_height - fill_height), c.colors["health_loss"], opacity)
        if fill_height > 0:
            r.rect(Rect(rect.x + 1, rect.y + height - 1 - fill_height, width - 2, fill_height),
                   c.colors["accent"], opacity)
        r.rect(rect, c.colors["line"], opacity, filled=False)

    def number_counter(self, visual, opacity, offset_x, *, number_role, label_key,
                       label_role, color, anchor_y, align_bottom=False, group_digits=False):
        c, r = self.config, self.renderer
        settings = c.data["damage_counter"]
        format_spec = "," if group_digits else "d"
        previous = format(visual.previous_value, format_spec)
        current = format(visual.value, format_spec)
        slots = max(len(previous), len(current))
        previous, current = previous.rjust(slots), current.rjust(slots)
        digit_width = max(r.text_size(str(digit), number_role)[0] for digit in range(10))
        comma_width = r.text_size(",", number_role)[0]
        widths = [comma_width if char == "," else digit_width for char in current]
        label = c.labels[label_key]
        label_widths = [r.text_size(char, label_role)[0] for char in label]
        label_height = r.text_size(label, label_role)[1]
        tracking = c.layout["counter_stack"].get("label_letter_spacing_pixels", 0)
        label_width = sum(label_widths) + tracking * max(0, len(label) - 1)
        gap = c.layout[f"{label_key}_label_gap"]
        available_width = max(1, c.layout[f"{label_key}_max_width"])
        scale = min(1.0, available_width / sum(widths))
        number_width = sum(widths) * scale
        height = r.text_size("0", number_role)[1] * scale
        row_height = height + gap + label_height
        stack = c.layout["counter_stack"]
        right = c.window["width"] - stack["right_margin_pixels"] + offset_x
        x = right - number_width
        y = anchor_y - row_height if align_bottom else anchor_y
        viewport = Rect(x, y, number_width, height)
        samples = settings["blur_samples"]
        shutter = settings["blur_shutter_seconds"]
        effect_progress = visual.progress
        vertical_progress = visual.vertical_progress
        moving = visual.moving
        outgoing_opacity = (1 - effect_progress) ** settings["outgoing_fade_power"] if moving else 0.0
        strength = (settings["blur_opacity"] * 4 * effect_progress * (1 - effect_progress)
                    if samples > 0 and shutter > 0 else 0.0)
        direction_x, direction_y = settings["blur_direction"]
        direction_length = hypot(direction_x, direction_y)
        direction_x, direction_y = direction_x / direction_length, direction_y / direction_length
        motion_pixels = height * max(0.0, effect_progress - visual.progress_before(shutter))
        blur_length = min(settings["blur_length_pixels"] * scale, motion_pixels)

        def draw_face(char, center_x, offset_y, alpha, smear_x=0, smear_y=0):
            if char == " ":
                return
            r.text(char, center_x + smear_x, y + offset_y + smear_y,
                   number_role, c.colors[color],
                   alpha, align="center", scale_x=scale, scale_y=scale, clip_rect=viewport)

        def draw_pair(old, new, center_x, alpha, smear_x=0, smear_y=0):
            # 한 글자 높이 간격을 유지해 새 숫자가 이전 숫자를 밀어 올린다.
            draw_face(old, center_x, -height * vertical_progress,
                      alpha * outgoing_opacity, smear_x, smear_y)
            draw_face(new, center_x, height * (1 - vertical_progress), alpha, smear_x, smear_y)

        for old, new, width in zip(previous, current, widths):
            center_x = x + width * scale / 2
            if old == new or not moving or new == ",":
                r.text(new, center_x, y, number_role, c.colors[color], opacity,
                       align="center", scale_x=scale, scale_y=scale, clip_rect=viewport)
            else:
                # 현재 글자를 지정 방향으로 쓸어 늘이고, 끝으로 갈수록 잔상을 약하게 한다.
                smear_strength = strength if blur_length > 0 else 0.0
                if samples > 0 and smear_strength > 0:
                    total_weight = samples * (samples + 1) / 2
                    for sample in range(samples, 0, -1):
                        distance = blur_length * sample / samples
                        alpha = opacity * smear_strength * (samples + 1 - sample) / total_weight
                        draw_pair(old, new, center_x, alpha,
                                  direction_x * distance, direction_y * distance)
                draw_pair(old, new, center_x, opacity * (1 - smear_strength))
            x += width * scale
        label_x, label_y = right - label_width, y + height + gap
        for char, width in zip(label, label_widths):
            r.text(char, label_x, label_y, label_role, c.colors["muted"], opacity)
            label_x += width + tracking
        return row_height

    def damage_number(self, visual, opacity, offset_x):
        r, c = self.renderer, self.config
        text = str(visual.amount)
        width, height = r.text_size(text, "damage_number")
        x = visual.x + (0 if visual.owner == "player" else offset_x)
        center_y = visual.y + height / 2
        alpha = opacity * visual.opacity
        if visual.height_progress == 0:
            # 가로가 펼쳐지거나 접히는 동안에는 정확히 1px 높이의 선을 유지한다.
            line_width = max(1, width * visual.width_progress)
            r.rect(Rect(x - line_width / 2, center_y - 0.5, line_width, 1),
                   c.colors["damage_number"], alpha)
            return
        draw_height = 1 + (height - 1) * visual.height_progress
        r.text(text, x, center_y - draw_height / 2, "damage_number",
               c.colors["damage_number"], alpha, align="center",
               scale_x=visual.width_progress, scale_y=draw_height / height)

    def combat(self, state, damage_visuals, opacity, offset_x,
               counter_visual=None, combo_visual=None, counters_opacity=0.0,
               cursor_position=None, player_trailing_ratio=None, target_trailing_ratio=None):
        c, r = self.config, self.renderer
        self.label("combat_heading", *c.layout["combat_heading"], "combat_title",
                   opacity=opacity, offset_x=offset_x)
        x, y = c.actor_anchor("player") if cursor_position is None else cursor_position
        radius = c.layout["crosshair_radius"]
        thickness = c.layout["crosshair_thickness_pixels"]
        r.ring(x, y, radius, thickness, c.colors["crosshair"], opacity)
        # 교차점의 알파가 겹치지 않도록 십자를 세 영역으로 나눈다.
        stroke = max(1, round(c.layout["crosshair_cross_thickness_pixels"]))
        left, top = round(x - stroke / 2), round(y - stroke / 2)
        upper, lower = round(y - 18), round(y + 18)
        r.rect(Rect(round(x - 18), top, 36, stroke), c.colors["crosshair"], opacity)
        r.rect(Rect(left, upper, stroke, top - upper), c.colors["crosshair"], opacity)
        r.rect(Rect(left, top + stroke, stroke, lower - top - stroke), c.colors["crosshair"], opacity)
        self.player_health_bar(state, opacity, player_trailing_ratio)
        self.panel(c.layout["target_panel"], opacity, offset_x)
        self.label("target", *c.layout["target_heading"], "target_heading", "muted", opacity, offset_x)
        x, y = c.layout["target_name"]
        name = c.labels["no_target"] if state.target is None else state.target.name
        heading_height = r.text_size(c.labels["target"], "target_heading")[1]
        name_height = r.text_size(name, "target_name")[1]
        # 공통 상단 앵커에서 글자 높이 차이의 절반만 보정해 세로 중심을 맞춘다.
        y += (heading_height - name_height) / 2
        name_width = c.layout["target_name_max_width"]
        if state.target is None:
            self.label("no_target", x, y, "target_name", "muted", opacity, offset_x,
                       max_width=name_width, align="right")
            self.gauge("target_gauge", 0, opacity, offset_x, "enemy")
        else:
            r.text(state.target.name, x + offset_x, y, "target_name", c.colors["text"], opacity,
                   max_width=name_width, align="right")
            self.gauge("target_gauge", state.target.health.ratio, opacity, offset_x, "enemy",
                       trailing_ratio=target_trailing_ratio)
        counters_alpha = opacity * max(0.0, min(1.0, counters_opacity))
        if counters_alpha > 0:
            if combo_visual is None:
                combo_visual = CounterVisual(state.combo_count, state.combo_count, 1, 1)
            # 카운터들 사이 여백의 중심을 화면 중앙 높이에 고정한다.
            gap_center_y = c.window["height"] / 2
            half_gap = c.layout["counter_stack"]["row_gap_pixels"] / 2
            self.number_counter(combo_visual, counters_alpha, offset_x, number_role="combo_number",
                                label_key="combo", label_role="combo_label", color="accent",
                                anchor_y=gap_center_y - half_gap, align_bottom=True)
            if counter_visual is None:
                counter_visual = CounterVisual(state.total_damage_dealt, state.total_damage_dealt, 1, 1)
            self.number_counter(counter_visual, counters_alpha, offset_x, number_role="damage_total",
                                label_key="damage", label_role="damage_label", color="warning",
                                group_digits=True, anchor_y=gap_center_y + half_gap)
        self.radar(state.radar_contacts, opacity)
        for visual in damage_visuals:
            self.damage_number(visual, opacity, offset_x)
