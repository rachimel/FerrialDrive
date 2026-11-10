"""ui-concept-v2의 배치. 기존 Pico2D 표현·카운터·레이더를 재사용한다."""

from math import cos, pi, sin

from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.counter import CounterVisual
from ferrial_drive.ui.view import UiView


class UiV2View(UiView):
    @property
    def layout(self):
        return self.config.data["v2"]["layout"]

    def polygon(self, points, color, opacity=1, *, filled=False):
        if filled:
            for index in range(1, len(points) - 1):
                self.renderer.filled_triangle(points[0], points[index], points[index + 1],
                                               color, opacity)
        else:
            for first, second in zip(points, points[1:] + points[:1]):
                self.renderer.line(*first, *second, color, opacity)

    def meter(self, key, ratio, color, opacity, trailing_ratio=None):
        """형상은 고정하고 채움만 자른다. 실제 자원 규칙은 계산하지 않는다."""
        r, c = self.renderer, self.config.colors
        x, y, width, height = self.layout[key]
        cut = min(12, height / 2)
        points = ((x + cut, y), (x + width - cut, y), (x + width, y + height),
                  (x + cut, y + height), (x, y))
        self.polygon(points, c["panel_surface"], opacity, filled=True)
        ratio = max(0.0, min(1.0, ratio))
        trail = ratio if trailing_ratio is None else max(ratio, min(1.0, trailing_ratio))
        for fill, fill_color in ((trail, c["health_loss"]), (ratio, c[color])):
            if fill > 0:
                with r.clip(Rect(x, y, width * fill, height)):
                    self.polygon(points, fill_color, opacity, filled=True)
        self.polygon(points, self.ui_accent, opacity * 0.8)

    def minimap(self, hud, opacity):
        r, c = self.renderer, self.config.colors
        rect = Rect(*self.layout["minimap"])
        self.panel((rect.x, rect.y, rect.width, rect.height), opacity, fill_opacity=0.85)
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

    def target(self, hud, opacity, offset_x):
        r, c = self.renderer, self.config.colors
        x, y, radius = self.layout["lock_diamond"]
        x += offset_x
        points = ((x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y))
        self.polygon(points, self.ui_accent, opacity * (1 if hud.target else 0.3))
        r.text("LOCK ON" if hud.target else "NO TARGET", x - radius, y - radius - 40,
               "hud_small", c["muted"], opacity)
        if hud.target:
            r.text(hud.target.name, x, y + radius + 7, "target_name", c["text"], opacity,
                   align="center", max_width=200)

    def resources(self, state, opacity, offset_x, player_trailing_ratio):
        r, c = self.renderer, self.config.colors
        hud = state.hud
        self.meter("hp_bar", hud.player_health.ratio, "accent", opacity, player_trailing_ratio)
        self.meter("energy_bar", state.energy_ratio, "energy", opacity)
        x, y = self.layout["hp_text"]
        r.text(f"{hud.player_health.current:,.0f}", x, y, "v2_hp", c["text"], opacity)
        r.text("HP", x + r.text_size(f"{hud.player_health.current:,.0f}", "v2_hp")[0] + 9,
               y + 17, "hud_small", c["muted"], opacity)
        x, y, width, height = self.layout["energy_bar"]
        r.text("OVERDRIVE" if state.overdrive else "ENERGY", x + width / 2, y + 1,
               "v2_meter_label", c["text"], opacity, align="center")
        rect = self.layout["level_panel"]
        self.panel(rect, opacity, fill_opacity=0.9, corner_cut_ratio=(0.16, 0.2))
        x, y, width, height = rect
        r.text("LV", x + 10, y + 4, "hud_small", c["muted"], opacity)
        r.text(f"{state.energy_level:02}", x + width / 2, y + 22, "v2_level", c["text"],
               opacity, align="center")
        cx, cy, radius = self.layout["ultimate_icon"]
        self.polygon(((cx, cy - radius), (cx + radius, cy), (cx, cy + radius), (cx - radius, cy)),
                     c["panel_surface"], opacity, filled=True)
        self.polygon(((cx, cy - radius), (cx + radius, cy), (cx, cy + radius), (cx - radius, cy)),
                     self.ui_accent, opacity)
        # 교체 가능한 기본 도형 아이콘. 최종 필살기 아트가 아니다.
        for angle in (0, pi / 2, pi, 3 * pi / 2):
            r.line(cx - cos(angle) * 20, cy - sin(angle) * 20,
                   cx + cos(angle + 0.6) * 25, cy + sin(angle + 0.6) * 25,
                   c["energy"], opacity)
        r.text(self.config.data["v2"]["labels"]["ultimate_key"], cx - radius + 2, cy - radius - 18,
               "hud_small", c["text"], opacity)
        r.text("LV.01", cx, cy + radius + 3, "hud_small", c["muted"], opacity, align="center")
        x, y = self.layout["dash_label"]
        r.text("SPACE", x, y, "hud_small", c["text"], opacity * (1 if state.dash_ready else 0.35))

    def weapons(self, hud, opacity, offset_x):
        if not hud.loadouts:
            return
        r, c = self.renderer, self.config.colors
        x, y, width, height = self.layout["weapons"]
        x += offset_x
        for index in range(len(hud.loadouts)):
            tab = (x + width - 104 + index * 54, y - 29, 50, 24)
            self.panel(tab, opacity if index == hud.active_loadout_index else opacity * 0.4,
                       fill_opacity=0.8, corner_cut_ratio=(0.12, 0.2))
            r.text(f"{index + 1:02}", tab[0] + 25, tab[1] + 3, "equipment_number", c["text"],
                   opacity, align="center")
        loadout = hud.loadouts[hud.active_loadout_index]
        for index, (kind, weapon) in enumerate((("melee", loadout.melee), ("ranged", loadout.ranged))):
            top = y + index * (height + 8)
            active = kind == hud.active_weapon_kind
            alpha = opacity if active else opacity * 0.5
            self.panel((x, top, width, height), alpha, fill_opacity=0.85,
                       corner_cut_ratio=(0.06, 0.18))
            r.rect(Rect(x + 5, top + 8, 3, height - 16), c["energy"] if active else c["line"], alpha)
            self.weapon_image(weapon, kind, Rect(x + 19, top + 10, width - 94, height - 36), alpha)
            r.text("MELEE" if kind == "melee" else "RANGED", x + 17, top + height - 24,
                   "weapon_name", c["muted"], alpha)
            if weapon.rounds is not None:
                r.text(str(weapon.rounds), x + width - 14, top + 9, "v2_ammo", c["text"], alpha, align="right")

    def absorption(self, trails, opacity):
        r, color = self.renderer, self.config.colors["energy"]
        for trail in trails:
            head = trail.progress
            for index in range(18):
                a = head - 0.28 + index / 18 * 0.28
                b = a + 0.28 / 18
                if b <= 0 or a >= 1:
                    continue
                r.line(*trail.point(a), *trail.point(b), color, opacity * (index + 1) / 18)

    def combat(self, state, damage_visuals=(), opacity=1, offset_x=0, *,
               counter_visual=None, combo_visual=None, counters_opacity=1,
               cursor_position=None, player_trailing_ratio=None, target_trailing_ratio=None,
               absorption_trails=()):
        r, c, hud = self.renderer, self.config.colors, state.hud
        self.minimap(hud, opacity)
        self.radar(hud.radar_contacts, opacity)
        self.target(hud, opacity, offset_x)
        if hud.target:
            self.meter("target_hp", hud.target.health.ratio, "enemy", opacity, target_trailing_ratio)
        else:
            self.meter("target_hp", 0, "enemy", opacity)
        x, y, width, height = self.layout["target_hp"]
        r.text("TARGET", x + width, y + height + 4, "target_heading", c["muted"], opacity, align="right")
        self.resources(state, opacity, offset_x, player_trailing_ratio)
        self.weapons(hud, opacity, offset_x)
        alpha = opacity * counters_opacity
        combo_visual = combo_visual or CounterVisual(hud.combo_count, hud.combo_count, 1, 1)
        counter_visual = counter_visual or CounterVisual(hud.total_damage_dealt, hud.total_damage_dealt, 1, 1)
        for visual, role, label, y in ((combo_visual, "combo_number", "combo", self.layout["hit_y"]),
                                     (counter_visual, "damage_total", "damage", self.layout["damage_y"])):
            row_height = self.number_counter(visual, alpha, offset_x, number_role=role,
                                             label_key=label, label_role=f"{label}_label",
                                             color="text", anchor_y=y, group_digits=label == "damage")
            right = self.config.window["width"] - self.config.layout["counter_stack"]["right_margin_pixels"]
            r.line(right - 200, y + row_height - 27, right, y + row_height - 27, self.ui_accent, alpha * 0.6)
        if state.counter:
            r.text("COUNTER!", *self.layout["counter_message"], "v2_counter", c["warning"], opacity)
        for visual in damage_visuals:
            self.damage_number(visual, opacity, offset_x)
        self.absorption(absorption_trails, opacity)
        if cursor_position is not None:
            x, y = cursor_position
            r.ring(x, y, 18, 2, c["crosshair"], opacity)
            r.line(x - 24, y, x - 9, y, c["crosshair"], opacity)
            r.line(x + 9, y, x + 24, y, c["crosshair"], opacity)
