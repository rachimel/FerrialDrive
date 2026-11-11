"""v2 도안의 사선·연결형 자원부·원근 카운터를 그린다."""

from math import atan2, cos, hypot, pi, sin

from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.counter import CounterVisual
from ferrial_drive.ui.view import UiView
from .geometry import (PerspectivePlane, body_diamond, counter_plaque, quad_fill,
                       resource_geometry, slanted_meter, tapered_stroke_mesh)
from .panels import build_panel_geometry, build_scanlines


class UiV2View(UiView):
    @property
    def layout(self):
        return self.config.data["v2"]["layout"]

    @property
    def style(self):
        return self.config.data["v2"]["style"]

    def background(self):
        self.renderer.clear(self.config.colors["background"])

    def stroke(self, points, color, opacity=1, width=1):
        for a, b in zip(points, points[1:]):
            if width <= 1:
                self.renderer.line(*a, *b, color, opacity)
                continue
            distance = hypot(b[0] - a[0], b[1] - a[1])
            if not distance:
                continue
            nx, ny = -(b[1] - a[1]) / distance * width / 2, (b[0] - a[0]) / distance * width / 2
            self.polygon(((a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny),
                          (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)),
                         color, opacity, filled=True)

    def slanted_text(self, text, x, y, role, color, opacity=1, *, scale=1, slope=0, lean=0.15, align="left"):
        r = self.renderer
        width, height = r.text_size(text, role)
        if align == "right":
            x -= (width + max(0, lean * height / 2)) * scale
        plane = PerspectivePlane(x, y, max(1, width * scale), max(1, height * scale),
                                 depth=0, lean=lean, slope=slope)
        r.warped_text(text, 0, 0, role, color, plane.point, opacity, scale_x=scale, scale_y=scale)

    def panel(self, rect, opacity, offset_x=0, *, fill_opacity=None, corner_cut_ratio=None,
              fill_color=None, draw_border=True, slant_right=False):
        """v2 전용 비대칭 외곽. 기존 금속 사각 패널을 호출하지 않는다."""
        x, y, width, height = rect
        x += offset_x
        c = self.config.colors
        cut = min(self.style["panel_cut_pixels"], width / 5, height / 3)
        points = (((x, y), (x + width - cut, y), (x + width, y + height), (x + cut, y + height))
                  if slant_right else
                  ((x + cut, y), (x + width, y), (x + width - cut, y + height), (x, y + height)))
        fill = self.style["surface_opacity"] if fill_opacity is None else fill_opacity
        settings = self.style["panel_border"]
        self.renderer.filtered_polygons((points,), c["panel"] if fill_color is None else fill_color,
                                        opacity * fill, settings["filter_samples"])
        if draw_border:
            for path, corners, alpha in (
                    ((points[3], points[0], (x + width * 0.45, y)), (1,), 0.8),
                    (((x + width * 0.55, y + height), points[2], points[1]), (1,), 0.5)):
                quads = tapered_stroke_mesh(path, corners, settings["thin_width_pixels"],
                                            settings["corner_width_pixels"], settings["reach_pixels"],
                                            settings["corner_hold_pixels"])
                self.renderer.filtered_polygons(quads, self.ui_accent, opacity * alpha,
                                                settings["filter_samples"])

    def panel_surface(self, geometry, opacity, *, fill_opacity=None, fill_color=None):
        """패널 면만 그린다. 테두리 표시와 독립이다."""
        fill = self.style["surface_opacity"] if fill_opacity is None else fill_opacity
        self.renderer.filtered_polygons((geometry.surface,),
                                        self.config.colors["panel"] if fill_color is None else fill_color,
                                        opacity * fill, self.style["panel_border"]["filter_samples"])

    def panel_border(self, parts, opacity, *, part_opacities=None):
        """테두리만 그린다. 각 조각의 표시값은 외부 효과 제어부가 공급할 수 있다."""
        for part in parts:
            visibility = 1 if part_opacities is None else part_opacities.get(part.part_id, 1)
            alpha = opacity * part.opacity * visibility
            if alpha > 0:
                self.renderer.filtered_polygons(part.polygons, self.ui_accent, alpha,
                                                self.style["panel_border"]["filter_samples"])

    def panel_scanlines(self, geometry, opacity, settings):
        """배경 위에 고정 Scanline을 그린다. 글자·지형·표식은 이후 그린다."""
        alpha = opacity * settings["line_opacity"]
        if alpha <= 0:
            return
        scanline = self.style["panel_scanlines"]
        strips = build_scanlines(geometry.surface, scanline["spacing_pixels"], scanline["thickness_pixels"])
        if strips:
            self.renderer.filtered_polygons(strips, self.ui_accent, alpha,
                                            self.style["panel_border"]["filter_samples"])

    def framed_panel(self, rect, opacity, *, fill_opacity=None, draw_border=True, scanline_settings=None):
        geometry = build_panel_geometry(rect, self.style["panel_cut_pixels"],
                                        self.style["panel_frame"], self.style["panel_border"])
        self.panel_surface(geometry, opacity, fill_opacity=fill_opacity)
        if scanline_settings is not None:
            self.panel_scanlines(geometry, opacity, scanline_settings)
        if draw_border:
            self.panel_border(geometry.border_parts, opacity)

    def dialogue(self, info, opacity):
        if info is None:
            return
        x, y, width, height = self.layout["dialogue"]
        settings = self.style["panel_scanlines"]["dialogue"]
        self.framed_panel((x, y, width, height), opacity, fill_opacity=settings["surface_opacity"],
                          scanline_settings=settings)
        padding_x, padding_y = self.style["dialogue_padding_pixels"]
        self.renderer.text(info.speaker, x + padding_x, y + padding_y, "target_name",
                           self.ui_accent, opacity)
        for index, line in enumerate(info.lines):
            self.renderer.text(line, x + padding_x, y + padding_y + 30 + index * 26,
                               "body", self.config.colors["text"], opacity,
                               max_width=width - padding_x * 2)

    def ultimate_label(self, text, right, y, color, opacity, *, scale=1, slant_right=False):
        """필살기 문구와 작은 사선 패널을 같은 위치·투명도로 그린다."""
        width, height = self.renderer.text_size(text, "hud_small")
        padding_x, padding_y = self.style["ultimate_label_padding_pixels"]
        width, height = (width + 0.15 * height) * scale, height * scale
        self.panel((right - width - padding_x, y - padding_y,
                    width + padding_x * 2, height + padding_y * 2), opacity, fill_opacity=0.98,
                   fill_color=self.config.colors["panel_surface"], draw_border=False, slant_right=slant_right)
        self.slanted_text(text, right, y, "hud_small", color, opacity, scale=scale, align="right")

    def buttons(self, scene, input_state, opacity, offset_x, buttons=None, *, offset_y=0):
        r, c = self.renderer, self.config.colors
        for index, button in enumerate(self.config.buttons[scene] if buttons is None else buttons):
            rect = button.rect.translated(offset_x, offset_y)
            x, y, width, height = rect.x, rect.y, rect.width, rect.height
            hovered = button.enabled and input_state.hovered_id == button.button_id
            pressed = hovered and input_state.pressed_id == button.button_id
            alpha = opacity * (1 if button.enabled else 0.3)
            points = ((x + 16, y + 2), (x + width, y + 2),
                      (x + width - 18, y + height - 2), (x, y + height - 2))
            self.polygon(points, c["ui_accent"] if hovered else c["panel_surface"],
                         alpha * (0.6 if pressed else 0.25 if hovered else 0.12), filled=True)
            self.stroke(((x + 22, y + height - 3), (x + width - 18, y + height - 3),
                         (x + width - 5, y + 10)), self.ui_accent, alpha * (1 if hovered else 0.5))
            self.stroke(((x + 5, y + height - 13), (x + 15, y + 11), (x + 25, y + 11)),
                         c["energy"] if hovered else self.ui_accent, alpha, 2)
            if scene == "menu":
                r.text(f"{index + 1:02}", x + 34, y + 15, "button_index", c["muted"], alpha)
            r.text(button.label, x + (74 if scene == "menu" else 38), y + 13,
                   "body", c["text"], alpha)

    def polygon(self, points, color, opacity=1, *, filled=False):
        if filled:
            for index in range(1, len(points) - 1):
                self.renderer.filled_triangle(points[0], points[index], points[index + 1],
                                               color, opacity)
        else:
            for first, second in zip(points, points[1:] + points[:1]):
                self.renderer.line(*first, *second, color, opacity)

    def meter(self, key, ratio, color, opacity, trailing_ratio=None, *, shape=None, border=None, rect=None):
        """형상은 고정하고 채움만 자른다. 실제 자원 규칙은 계산하지 않는다."""
        r, c = self.renderer, self.config.colors
        x, y, width, height = self.layout[key] if rect is None else rect
        cut = min(18, height * 0.65)
        points = slanted_meter((x, y, width, height)) if shape is None else shape
        self.polygon(points, c["panel_surface"], opacity * 0.7, filled=True)
        ratio = max(0.0, min(1.0, ratio))
        trail = ratio if trailing_ratio is None else max(ratio, min(1.0, trailing_ratio))
        for fill, fill_color in ((trail, c["health_loss"]), (ratio, c[color])):
            if fill > 0:
                self.polygon(quad_fill(points, fill), fill_color, opacity, filled=True)
        if border is not None:
            self.stroke(border + border[:1], self.ui_accent, opacity * 0.85, 1.5)
            return
        self.stroke(((x - cut - 7, y - 4), (x + width - cut + 3, y - 4),
                     (x + width + 7, y + height + 2)), self.ui_accent, opacity * 0.8)
        self.stroke(((x + 5, y + height + 4), (x + width * 0.63, y + height + 4)),
                     self.ui_accent, opacity * 0.35)

    def minimap(self, hud, opacity):
        r, c = self.renderer, self.config.colors
        rect = Rect(*self.layout["minimap"])
        settings = self.style["panel_scanlines"]["minimap"]
        self.framed_panel((rect.x, rect.y, rect.width, rect.height), opacity,
                          fill_opacity=settings["surface_opacity"], draw_border=False,
                          scanline_settings=settings)
        with r.clip(rect):
            for wall in self.config.data["v2"]["map_walls"]:
                a, b, d, e = wall
                r.line(rect.x + a * rect.width, rect.y + b * rect.height,
                       rect.x + d * rect.width, rect.y + e * rect.height, self.ui_accent, opacity * 0.5)
            cx, cy = rect.x + rect.width / 2, rect.y + rect.height / 2
            r.filled_triangle((cx, cy - 6), (cx - 4, cy + 4), (cx + 4, cy + 4),
                              c["accent"], opacity)
            for contact in hud.radar_contacts:
                if abs(contact.x) <= 1 and abs(contact.y) <= 1:
                    px, py = cx + contact.x * rect.width * 0.43, cy - contact.y * rect.height * 0.43
                    r.rect(Rect(px - 2, py - 2, 4, 4), c["enemy" if contact.kind == "enemy" else "accent"], opacity)
        r.text("MAP", rect.x, rect.y + rect.height + 6, "hud_small", c["muted"], opacity)

    def target(self, state, opacity, offset_x):
        r, c = self.renderer, self.config.colors
        hud, body = state.hud, state.target_body
        if body is None:
            return
        x, y, rx, ry = body_diamond((body.x, body.y, body.width, body.height), self.style["lock_body_scale"])
        x += offset_x
        points = ((x, y - ry), (x + rx, y), (x, y + ry), (x - rx, y))
        alpha = opacity * (1 if hud.target else 0.3)
        self.stroke(points + points[:1], self.ui_accent, alpha, self.style["lock_thickness_pixels"])
        # 마름모 안으로 파고드는 꼬리를 빼고 강조선을 왼쪽 위 변에 붙인다.
        self.stroke((points[3], points[0]), c["text"], alpha, self.style["lock_accent_pixels"])
        angle = -atan2(ry, rx)
        label = "LOCK ON" if hud.target else "NO TARGET"
        label_width, label_height = r.text_size(label, "target_heading")
        ux, uy = cos(angle), sin(angle)
        nx, ny = -uy, ux
        gap, end_gap = self.style["lock_text_gap_pixels"], self.style["lock_text_end_gap_pixels"]
        label_end = (points[0][0] - nx * gap - ux * end_gap,
                     points[0][1] - ny * gap - uy * end_gap)
        origin = (label_end[0] - ux * label_width - nx * label_height,
                  label_end[1] - uy * label_width - ny * label_height)
        def label_point(px, py):
            return origin[0] + px * ux + py * nx, origin[1] + px * uy + py * ny
        r.warped_text(label, 0, 0, "target_heading",
                      c["text"], label_point, alpha)
        if hud.target:
            r.text(hud.target.name, x, y + max(ry + 7, body.height * 2), "target_name", c["text"], opacity,
                   align="center", max_width=200)

    def resources(self, state, opacity, offset_x, player_trailing_ratio):
        r, c = self.renderer, self.config.colors
        hud = state.hud
        geometry = resource_geometry(self.layout, self.style["level_curve_radius_pixels"])
        self.meter("hp_bar", hud.player_health.ratio, "accent", opacity, player_trailing_ratio,
                   shape=geometry.hp_shape, border=geometry.hp_outline)
        value = f"{hud.player_health.current:,.0f}"
        value_width, value_height = r.text_size(value, "v2_hp")
        x, top = geometry.hp_outline[0]
        gap = self.style["resource_label_gap_pixels"]
        r.text(value, x, top - value_height - gap, "v2_hp", c["text"], opacity)
        hp_height = r.text_size("HP", "hud_small")[1]
        r.text("HP", x + value_width + 9, top - hp_height - gap, "hud_small", c["muted"], opacity)
        x, y, width, height = self.layout["energy_bar"]
        outline, channel = geometry.energy_outline, geometry.energy_channel
        self.polygon(geometry.energy_body, c["panel"], opacity * 0.96, filled=True)
        self.polygon(geometry.level_shape, c["panel"], opacity * 0.96, filled=True)
        self.stroke(outline + outline[:1], c["text"], opacity * 0.75, 1.5)
        self.polygon(channel, c["energy"], opacity * 0.1, filled=True)
        if state.energy_ratio > 0:
            filled = quad_fill(channel, state.energy_ratio)
            self.polygon(filled, c["energy_fill"], opacity, filled=True)
            self.stroke((filled[1], filled[2]), c["energy"], opacity, 2)
        self.stroke((outline[-1], geometry.level_shape[-2]),
                     c["energy"] if state.overdrive else self.ui_accent, opacity, 2)
        label = "O V E R D R I V E" if state.overdrive else "E N E R G Y"
        label_width = r.text_size(label, "v2_meter_label")[0]
        label_center = sum(point[0] for point in channel) / 4
        self.slanted_text(label, label_center - label_width / 2, y + 2,
                          "v2_meter_label", c["text"], opacity)
        level_right = x + width + self.layout["energy_level_width_pixels"]
        level_text_right = level_right - 8
        self.slanted_text("LV", level_text_right, geometry.level_top + 4,
                          "hud_small", c["ui_accent"], opacity, scale=0.65, align="right")
        self.slanted_text(f"{state.energy_level:02}", level_text_right, geometry.level_top + 15,
                          "v2_level", c["muted"], opacity, scale=0.85, lean=0.1, align="right")
        cx, cy = geometry.icon_center
        radius = geometry.icon_radius
        diamond = ((cx, cy - radius), (cx + radius, cy), (cx, cy + radius), (cx - radius, cy))
        self.polygon(diamond, c["panel"], opacity * 0.8, filled=True)
        self.stroke(diamond + diamond[:1], c["text"], opacity * 0.9, 1.5)
        # 기본 도형으로 만든 비대칭 네 갈래 칼날. 원본 아이콘 아트는 별도 제작한다.
        for angle in (-0.3, pi / 2 - 0.3, pi - 0.3, 3 * pi / 2 - 0.3):
            def blade_point(dx, dy):
                return cx + cos(angle) * dx - sin(angle) * dy, cy + sin(angle) * dx + cos(angle) * dy
            icon_scale = self.style["ultimate_icon_scale"]
            blade = tuple(blade_point(point[0] * icon_scale, point[1] * icon_scale)
                          for point in ((-5, -5), (radius + 5, -10), (12, 4), (1, 18)))
            self.polygon(blade, c["energy_fill"], opacity * 0.75, filled=True)
            self.stroke(blade + blade[:1], c["text"], opacity * 0.9, 1.5)
        key = self.config.data["v2"]["labels"]["ultimate_key"]
        level = "LV. 01"
        key_height = r.text_size(key, "hud_small")[1]
        gap = self.style["ultimate_label_gap_pixels"]
        label_right = cx - radius / 2 - gap
        self.ultimate_label(key, label_right, cy - radius / 2 - key_height - gap,
                            c["text"], opacity)
        self.ultimate_label(level, label_right, cy + radius / 2 + gap,
                            c["muted"], opacity, scale=0.85, slant_right=True)
        x, y = self.layout["dash_label"]
        alpha = opacity * (1 if state.dash_ready else 0.25)
        self.stroke(((x + 16, y - 24), (x + 25, y - 43), (x + 32, y - 39), (x + 21, y - 18),
                     (x + 32, y - 15)), c["text"], alpha, 2)
        self.stroke(((x + 10, y - 31), (x + 7, y - 19), (x + 2, y - 14)), self.ui_accent, alpha)
        self.slanted_text("SPACE", x, y, "hud_small", c["text"], alpha, scale=0.9)

    def weapons(self, hud, opacity, offset_x):
        if not hud.loadouts:
            return
        r, c = self.renderer, self.config.colors
        x, y, width, height = self.layout["weapons"]
        x += offset_x
        for index in range(len(hud.loadouts)):
            tab = (x + width - 104 + index * 54, y - 29, 50, 24)
            tx, ty, tw, th = tab
            alpha = opacity * (1 if index == hud.active_loadout_index else 0.35)
            shape = ((tx + 10, ty), (tx + tw, ty), (tx + tw - 9, ty + th), (tx, ty + th))
            self.polygon(shape, c["panel_surface"], alpha * 0.5, filled=True)
            self.stroke(shape + shape[:1], self.ui_accent, alpha)
            r.text(f"{index + 1:02}", tx + 15, ty + 3, "equipment_number", c["text"], alpha)
        loadout = hud.loadouts[hud.active_loadout_index]
        for index, (kind, weapon) in enumerate((("melee", loadout.melee), ("ranged", loadout.ranged))):
            top = y + index * (height + 8)
            active = kind == hud.active_weapon_kind
            alpha = opacity if active else opacity * 0.5
            left = x + (0 if active else 22)
            amount = 1 if active else self.style["inactive_weapon_scale"]
            with r.scaled(amount, (x + width, top + height / 2)):
                shape = ((left + 18, top), (x + width, top),
                         (x + width - 18, top + height), (left, top + height))
                self.polygon(shape, c["panel_surface"], alpha * 0.65, filled=True)
                self.stroke((shape[0], shape[3], shape[2], shape[1]),
                             self.ui_accent, alpha * 0.85)
                self.stroke((shape[0], shape[3]), self.ui_accent,
                             alpha * 0.95, self.style["weapon_outer_edge_pixels"])
                self.stroke(((left + 28, top + 4), (x + width - 4, top + 4)), self.ui_accent, alpha * 0.3)
                self.weapon_image(weapon, kind, Rect(left + 18, top + 11, width - 112, height - 39), alpha)
                r.text("MELEE" if kind == "melee" else "RANGED", left + 17, top + height - 23,
                       "weapon_name", c["text"], alpha)
                if weapon.rounds is not None:
                    text = str(weapon.rounds)
                    r.text(text, x + width - r.text_size(text, "v2_ammo")[0] - 16,
                           top + 10, "v2_ammo", c["text"], alpha)

    def absorption(self, trails, opacity):
        r, color = self.renderer, self.config.colors["energy"]
        for trail in trails:
            head = trail.progress
            for index in range(18):
                a = head - 0.28 + index / 18 * 0.28
                b = a + 0.28 / 18
                if b <= 0 or a >= 1:
                    continue
                alpha = opacity * ((index + 1) / 18) ** 1.5
                segment = (trail.point(a), trail.point(b))
                self.stroke(segment, color, alpha * 0.12, 5)
                self.stroke(segment, color, alpha * 0.5, 2)
                self.stroke(segment, self.config.colors["text"], alpha)

    def counter_base(self, project, width, ink_bottom, opacity):
        thickness = self.style["counter_plaque_height_pixels"]
        slant = self.style["counter_plaque_slant_pixels"]
        left, right = project(-14, ink_bottom - 1), project(width + 3, ink_bottom - 1)
        color = self.config.colors["counter_plaque"]
        self.polygon(counter_plaque(left, right, thickness, slant), color, opacity, filled=True)
        distance = hypot(right[0] - left[0], right[1] - left[1])
        ux, uy = (right[0] - left[0]) / distance, (right[1] - left[1]) / distance
        cursor = left
        for index, (length, size, alpha) in enumerate(((13, 0.85, 0.55), (10, 0.65, 0.3), (7, 0.45, 0.12))):
            end = (cursor[0] - ux * 5, cursor[1] - uy * 5 - index * 0.8)
            start = (end[0] - ux * length, end[1] - uy * length)
            self.polygon(counter_plaque(start, end, thickness * size, slant * size),
                         color, opacity * alpha, filled=True)
            cursor = start

    def perspective_counter(self, visual, role, label, y, opacity):
        """회전 숫자를 평면에서 자르고 한 투영면에 올려 원근을 유지한다."""
        r, c = self.renderer, self.config.colors
        settings = self.style["counters"][label]
        spec = "," if label == "damage" else "d"
        old, new = format(visual.previous_value, spec), format(visual.value, spec)
        if not visual.moving:
            old = new
        slots = max(len(old), len(new))
        old, new = old.rjust(slots), new.rjust(slots)
        digit_width = max(r.text_size(str(digit), role)[0] for digit in range(10))
        comma_width = r.text_size(",", role)[0]
        widths = [comma_width if char == "," else digit_width for char in new]
        scale = settings["text_scale"]
        width, height = sum(widths) * scale, r.text_size("0", role)[1] * scale
        right = self.config.window["width"] - settings["right_margin_pixels"]
        reference_width = settings["perspective_width_pixels"]
        origin = right - reference_width - height * settings["lean"] / 2 - 2
        plane = PerspectivePlane(origin, y, reference_width, height,
                                 settings["depth"], settings["lean"], settings["slope"])
        project = lambda px, py: plane.point(reference_width - width + px, py)
        shadow = lambda px, py: (project(px, py)[0] + 2, project(px, py)[1] + 3)
        ink_bottom = r.digit_ink_bottom(role) * scale
        viewport = Rect(0, 0, width, ink_bottom)
        self.counter_base(project, width, ink_bottom, opacity)
        x = 0
        for before, after, slot_width in zip(old, new, widths):
            moving = visual.moving and before != after and after != ","
            faces = ((before, -height * visual.vertical_progress, 1 - visual.progress),
                     (after, height * (1 - visual.vertical_progress), 1)) if moving else ((after, 0, 1),)
            for char, top, alpha in faces:
                if char == " ":
                    continue
                left = x + (slot_width - r.text_size(char, role)[0]) * scale / 2
                for projection, color in ((shadow, c["counter_shadow"]), (project, c["text"])):
                    r.warped_text(char, left, top, role, color, projection, opacity * alpha,
                                  scale_x=scale, scale_y=scale, clip_rect=viewport)
            x += slot_width * scale
        label_text = self.config.labels[label]
        label_role = f"{label}_label"
        label_width = r.text_size(label_text, label_role)[0]
        r.warped_text(label_text, width - label_width - 6,
                      ink_bottom + self.style["counter_plaque_height_pixels"] + 5,
                      label_role, c["muted"], project, opacity)

    def combat(self, state, damage_visuals=(), opacity=1, offset_x=0, *,
               counter_visual=None, combo_visual=None, counters_opacity=1,
               cursor_position=None, player_trailing_ratio=None, target_trailing_ratio=None,
               absorption_trails=()):
        r, c, hud = self.renderer, self.config.colors, state.hud
        scale = self.style["hud_scale"]
        width, height = self.config.window["width"], self.config.window["height"]
        with r.scaled(self.style["map_scale"], self.layout["minimap"][:2]):
            self.minimap(hud, opacity)
        self.radar(hud.radar_contacts, opacity)
        body = state.target_body
        target_anchor = ((body.x + body.width / 2, body.y + body.height / 2)
                         if body is not None else self.config.actor_anchor("target"))
        with r.scaled(scale, target_anchor):
            self.target(state, opacity, offset_x)
            x, y, bar_width, bar_height = self.layout["target_hp"]
            dx, dy = self.layout["target_hp_offset_pixels"]
            x, y = target_anchor[0] + dx, target_anchor[1] + dy
            target_rect = (x, y, bar_width, bar_height)
            if hud.target:
                self.meter("target_hp", hud.target.health.ratio, "enemy", opacity, target_trailing_ratio,
                           rect=target_rect)
            else:
                self.meter("target_hp", 0, "enemy", opacity, rect=target_rect)
            r.text("TARGET", x + bar_width, y + bar_height + 4, "target_heading", c["muted"], opacity, align="right")
        with r.scaled(scale, (width / 2, height)):
            self.resources(state, opacity, offset_x, player_trailing_ratio)
        with r.scaled(self.style["equipment_scale"], (width, height)):
            self.weapons(hud, opacity, offset_x)
        alpha = opacity * counters_opacity
        combo_visual = combo_visual or CounterVisual(hud.combo_count, hud.combo_count, 1, 1)
        counter_visual = counter_visual or CounterVisual(hud.total_damage_dealt, hud.total_damage_dealt, 1, 1)
        for visual, role, label, y in ((combo_visual, "combo_number", "combo", self.layout["hit_y"]),
                                     (counter_visual, "damage_total", "damage", self.layout["damage_y"])):
            right = width - self.style["counters"][label]["right_margin_pixels"]
            with r.scaled(scale, (right, y)):
                self.perspective_counter(visual, role, label, y, alpha)
        if state.counter:
            text_scale = self.style["counter_text_scale"]
            with r.scaled(scale, self.layout["counter_message"]):
                r.text("COUNTER!", *self.layout["counter_message"], "v2_counter", c["warning"],
                       opacity, scale_x=text_scale, scale_y=text_scale)
        for visual in damage_visuals:
            with r.scaled(scale, (visual.x, visual.y)):
                self.damage_number(visual, opacity, offset_x)
        self.absorption(absorption_trails, opacity)
        self.dialogue(state.dialogue, opacity)
        if cursor_position is not None:
            x, y = cursor_position
            with r.scaled(scale, (x, y)):
                r.ring(x, y, 18, 2, c["crosshair"], opacity)
                r.line(x - 24, y, x - 9, y, c["crosshair"], opacity)
                r.line(x + 9, y, x + 24, y, c["crosshair"], opacity)
