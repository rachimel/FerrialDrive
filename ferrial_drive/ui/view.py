"""표현 설정을 사용하는 UI 그리기. 게임 상태 갱신이나 입력 처리는 하지 않는다."""

from math import hypot

from .components import Rect
from .counter import CounterVisual
from .weapon_swap import diamond_offset
from .weapon_icons import fit_weapon_icon


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

    def panel(self, rect, opacity, offset_x=0, *, fill_opacity=None, corner_cut_ratio=(0.0, 0.0)):
        r, c = self.renderer, self.config.colors
        style = self.config.data["panel_style"]
        rect = Rect(*rect).translated(offset_x)
        fill = style["fill_opacity"] if fill_opacity is None else fill_opacity
        color = c.get("panel_surface", c["panel"])
        metal = style.get("metallic", {})
        cut_x, cut_y = corner_cut_ratio
        clipped_corner = cut_x > 0 and cut_y > 0
        if metal.get("enabled", False) or clipped_corner:
            r.metallic_rect(rect, color, opacity * fill,
                            contrast=metal["contrast"] if metal.get("enabled", False) else 0,
                            highlight_center=metal.get("highlight_center", (0.5, 1.15)),
                            highlight_radius=metal.get("highlight_radius", (1.25, 1.3)),
                            corner_cut_ratio=corner_cut_ratio)
        else:
            r.rect(rect, color, opacity * fill)
        cut = rect.width * cut_x if clipped_corner else 0
        if clipped_corner:
            vertices = ((rect.x + cut, rect.y), (rect.x + rect.width, rect.y),
                        (rect.x + rect.width, rect.y + rect.height * (1 - cut_y)),
                        (rect.x + rect.width - cut, rect.y + rect.height), (rect.x, rect.y + rect.height),
                        (rect.x, rect.y + rect.height * cut_y))
            for first, second in zip(vertices, vertices[1:] + vertices[:1]):
                r.line(*first, *second, c["panel_border"], opacity * style["border_opacity"])
        else:
            r.rect(rect, c["panel_border"], opacity * style["border_opacity"], filled=False)
        r.line(rect.x + cut, rect.y, rect.x + min(cut + 72, rect.width), rect.y, self.ui_accent, opacity)

    def label(self, key, x, y, role="body", color="text", opacity=1,
              offset_x=0, **kwargs):
        self.renderer.text(self.config.labels[key], x + offset_x, y, role,
                           self.config.colors[color], opacity, **kwargs)

    def buttons(self, scene, input_state, opacity, offset_x, buttons=None, *, offset_y=0):
        r, c = self.renderer, self.config.colors
        body_role = "hud_body" if scene == "combat" else "body"
        palette = "hud_button" if scene == "combat" else "menu_button"
        normal_fill = c.get(palette, c["panel"])
        hover_fill = c.get(f"{palette}_hover", c["panel_hover"])
        pressed_fill = c.get(f"{palette}_pressed", c["panel_pressed"])
        text_color = c.get(f"{palette}_text", c["text"])
        marker_color = self.ui_accent if scene == "combat" else text_color
        for index, button in enumerate(self.config.buttons[scene] if buttons is None else buttons):
            rect = button.rect.translated(offset_x, offset_y)
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
        r.ring(x, y, radius, thickness, self.ui_accent, opacity * settings["ring_opacity"])
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
            color = self.ui_accent
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

    def equipment(self, state, opacity, offset_x, ranged_weight=None, *,
                  swap_visual=None, loadout_visual=None):
        if not state.loadouts:
            return
        c, r = self.config, self.renderer
        x, y, width, height = c.layout["equipment_panel"]
        x += offset_x
        right = x + width - 16
        displayed_index = (state.active_loadout_index if loadout_visual is None
                           else loadout_visual.incoming_index)
        if swap_visual is not None:
            ranged_weight = swap_visual.weight_before()
        if ranged_weight is None:
            ranged_weight = 1.0 if state.active_weapon_kind == "ranged" else 0.0
        ranged_weight = max(0.0, min(1.0, ranged_weight))
        sliding = loadout_visual is not None and loadout_visual.moving
        swapping = swap_visual is not None and swap_visual.moving
        progress = loadout_visual.progress_before() if sliding else 1.0
        orbit_direction = swap_visual.orbit_direction if swap_visual is not None else -1
        slots = c.layout["equipment_slots"]
        leftmost = min(entry["panel"][0] for entry in slots.values())
        exit_distance = (c.window["width"] - (x + leftmost)
                         + c.data["loadout_slide"]["exit_padding_pixels"])

        def paint(weight, amount, alpha):
            if sliding:
                shift, fade, index = loadout_visual.pose(exit_distance, amount)
                if fade > 0:
                    self.equipment_loadout(state.loadouts[index], weight, x + shift, y, alpha * fade,
                                           orbit_direction=orbit_direction)
            else:
                self.equipment_loadout(state.loadouts[displayed_index], weight, x, y, alpha,
                                       orbit_direction=orbit_direction)

        # 화면 끝까지 이동할 수 있게 HUD 테두리 대신 실제 화면에서 잘라낸다.
        with r.clip(Rect(0, 0, c.window["width"], c.window["height"])):
            settings = c.data["equipment_motion_blur"]
            shutter, maximum = settings["shutter_seconds"], settings["max_length_pixels"]
            old_weight = swap_visual.weight_before(shutter) if swapping else ranged_weight
            old_progress = loadout_visual.progress_before(shutter) if sliding else progress
            slots = c.layout["equipment_slots"]
            active_panel = slots["active"]["panel"]
            swap_distance = max(hypot(entry["panel"][0] - active_panel[0],
                                      entry["panel"][1] - active_panel[1])
                                for key, entry in slots.items() if key.endswith("inactive"))
            diamond = c.data["weapon_swap"]["diamond_half_width_pixels"]
            inset = max(0, x + width + diamond - c.window["width"]
                        + c.data["weapon_swap"]["screen_edge_margin_pixels"])
            swap_distance += 2 * (diamond + inset)
            # 반 구간 easeInOutQuint의 전체 시간 대비 최대 기울기는 10이다.
            loadout_distance = exit_distance * 10
            extent = (abs(ranged_weight - old_weight) * swap_distance
                      + abs(progress - old_progress) * loadout_distance)
            samples = settings["samples"]
            strength = settings["opacity"] * min(1.0, extent / maximum) if maximum > 0 and samples else 0
            if strength > 0:
                total = samples * (samples + 1) / 2
                for sample in range(samples, 0, -1):
                    seconds_ago = shutter * sample / samples
                    weight = swap_visual.weight_before(seconds_ago) if swapping else ranged_weight
                    amount = loadout_visual.progress_before(seconds_ago) if sliding else progress
                    # 정지 직전이나 긴 프레임에서도 잔상 길이를 상한 안에 유지한다.
                    travel = (abs(weight - ranged_weight) * swap_distance
                              + abs(amount - progress) * loadout_distance)
                    ratio = min(1.0, maximum / travel) if travel > 0 else 1.0
                    weight = ranged_weight + (weight - ranged_weight) * ratio
                    amount = progress + (amount - progress) * ratio
                    alpha = opacity * strength * (samples + 1 - sample) / total
                    paint(weight, amount, alpha)
            paint(ranged_weight, progress, opacity * (1 - strength))
        tab_offset, tab_opacity = 0.0, 1.0
        if loadout_visual is not None:
            tab_offset, tab_opacity, displayed_index = loadout_visual.pose(exit_distance)
        tabs_alpha = opacity * tab_opacity
        for index in range(2):
            tab = Rect(right - 76 + index * 40 + tab_offset, y + c.layout["equipment_tabs_y"], 34, 24)
            active = index == displayed_index
            available = index < len(state.loadouts)
            r.rect(tab, self.ui_accent if active else c.colors["line"], tabs_alpha,
                   filled=active)
            r.text(f"{index + 1:02}" if available else "—", tab.x + 17, tab.y + 3,
                   "equipment_number", c.colors["menu_button_text"] if active else c.colors["muted"],
                   tabs_alpha, align="center")

    def equipment_loadout(self, loadout, ranged_weight, x, y, opacity, *, scale_y=1.0, orbit_direction=-1):
        rows = ((loadout.melee, "melee", 1 - ranged_weight),
                (loadout.ranged, "ranged", ranged_weight))
        # 크게 표시되는 쪽을 나중에 그린다. 교차 구간은 흐리게 해 겹침을 줄인다.
        for weapon, kind, weight in sorted(rows, key=lambda row: row[2]):
            self.equipment_weapon(weapon, kind, weight, x, y, opacity, scale_y=scale_y,
                                  orbit_direction=orbit_direction)

    def equipment_weapon(self, weapon, kind, weight, x, y, opacity, *, scale_y=1.0, orbit_direction=-1):
        c, r = self.config, self.renderer
        slots = c.layout["equipment_slots"]
        small = slots.get(f"{kind}_inactive", slots["inactive"])
        large = slots.get(f"{kind}_active", slots["active"])

        def blend(key):
            return tuple(first + (second - first) * weight
                         for first, second in zip(small[key], large[key]))

        settings = c.data["weapon_swap"]
        base_x, _, hud_width, _ = c.layout["equipment_panel"]
        spread = settings["diamond_half_width_pixels"]
        inset = max(0, base_x + hud_width + spread - c.window["width"]
                    + settings["screen_edge_margin_pixels"])
        x += diamond_offset(kind, weight, spread, inset, orbit_direction)
        crossing = settings["crossing_opacity"]
        alpha = opacity * (settings["inactive_opacity"] + (1 - settings["inactive_opacity"]) * weight)
        alpha *= crossing + (1 - crossing) * abs(2 * weight - 1)
        panel_x, panel_y, panel_width, panel_height = blend("panel")
        self.panel((x + panel_x, y + panel_y * scale_y, panel_width, panel_height * scale_y),
                   alpha, corner_cut_ratio=c.data["equipment_style"]["corner_cut_ratio"])
        name_x, name_y = blend("name")
        name_scale = small["name_scale"] + (large["name_scale"] - small["name_scale"]) * weight
        name_width = small["name_max_width"] + (large["name_max_width"] - small["name_max_width"]) * weight
        name_right = panel_x + panel_width - 12
        ammo_layout = None
        if weapon.rounds is not None:
            ammo_x, ammo_y = blend("ammo")
            scale = small["ammo_scale"] + (large["ammo_scale"] - small["ammo_scale"]) * weight
            ammo_width, ammo_height = r.text_size(str(weapon.rounds), "ammo_number")
            # ammo의 y는 카드 중앙 앵커다. 실제 글자 높이로 위쪽 좌표를 구한다.
            ammo_y -= ammo_height * scale / 2
            ammo_layout = (ammo_x, ammo_y, scale)
            name_right = min(name_right, ammo_x - ammo_width * scale - 12)
        name_width = min(name_width, max(0, (name_right - name_x) / name_scale))
        style = c.data["equipment_style"]
        padding_x, padding_y = style["name_plate_padding_pixels"]
        text_width, text_height = r.text_size(weapon.name, "weapon_name")
        plate_width = min(name_width, max(text_width, style["name_plate_min_width_pixels"])) * name_scale
        plate = Rect(x + name_x - padding_x * name_scale,
                     y + (name_y - padding_y * name_scale) * scale_y,
                     plate_width + 2 * padding_x * name_scale,
                     (text_height + 2 * padding_y) * name_scale * scale_y)
        r.rect(plate, c.colors["weapon_name_plate"], alpha)
        r.text(weapon.name, x + name_x, y + name_y * scale_y, "weapon_name", c.colors["text"], alpha,
               max_width=name_width, scale_x=name_scale, scale_y=name_scale * scale_y)
        image_x, image_y, width, height = blend("image")
        self.weapon_image(weapon, kind, Rect(x + image_x, y + image_y * scale_y, width, height * scale_y),
                          alpha, vertical_scale=scale_y)
        if ammo_layout is not None:
            ammo_x, ammo_y, scale = ammo_layout
            r.text(str(weapon.rounds), x + ammo_x, y + ammo_y * scale_y, "ammo_number",
                   c.colors["text"], alpha, align="right", max_width=100,
                   scale_x=scale, scale_y=scale * scale_y)

    def weapon_image(self, weapon, kind, rect, opacity, *, vertical_scale=1.0):
        """에셋 없는 독립 시연용 무기 실루엣. 좌표는 아이콘 영역에 대한 비율이다."""
        if weapon.image_path is not None:
            self.renderer.image(weapon.image_path, rect, opacity, vertical_scale=vertical_scale)
            return
        rect = fit_weapon_icon(kind, rect, vertical_scale)
        outline = self.config.data["equipment_style"]["silhouette_outline_pixels"] if kind == "ranged" else 0
        self.renderer.weapon_silhouette(kind, rect, self.ui_accent, opacity,
                                        self.config.colors["weapon_outline"], outline)

    def combat(self, state, damage_visuals, opacity, offset_x,
               counter_visual=None, combo_visual=None, counters_opacity=0.0,
               cursor_position=None, player_trailing_ratio=None, target_trailing_ratio=None,
               weapon_swap_amount=None, weapon_swap_visual=None, loadout_visual=None):
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
        self.equipment(state, opacity, offset_x, weapon_swap_amount,
                       swap_visual=weapon_swap_visual, loadout_visual=loadout_visual)
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
