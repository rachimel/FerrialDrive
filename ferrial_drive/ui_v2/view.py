"""v2 도안의 사선·연결형 자원부·원근 카운터를 그린다."""

from math import atan2, cos, hypot, pi, sin
from dataclasses import replace
from contextlib import contextmanager, nullcontext

from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.counter import CounterVisual
from ferrial_drive.ui.energy import energy_color
from ferrial_drive.ui.view import UiView
from .geometry import (PerspectivePlane, body_diamond, counter_plaque, hatched_stroke_mesh, quad_fill,
                       resource_geometry, slanted_meter, tapered_stroke_mesh)
from .panels import (PanelGeometry, build_panel_geometry, merge_panel_y_ranges,
                     panel_bright_band_top, scale_panel_geometry)
from .panel_probe import PanelProbeRenderer
from .effects import (DialoguePanelVisual, HealthHitVisual, OverdriveVisual, ScanlineVisual,
                      UltimateReadyVisual, breathing_opacity, subtle_flicker)
from .lock_on import LockOnVisual, accent_position, outline_segment


class UiV2View(UiView):
    def text_flicker(self):
        return subtle_flicker(self._scanline_visual.elapsed_seconds, **self.style["text_flicker"])

    def __init__(self, config, renderer):
        super().__init__(config, renderer)
        self._scanline_visual = ScanlineVisual()
        self._panel_probe = None
        self._panel_y_ranges = None

    def prepare_panel_effects(self, draw_panels):
        """이번 프레임의 같은 UI 경로를 그리기 없이 살펴 전역 띠 경로를 만든다."""
        original = self.renderer
        probe = PanelProbeRenderer(original)
        self.renderer, self._panel_probe = probe, probe
        try:
            draw_panels()
        finally:
            self.renderer, self._panel_probe = original, None
        self._panel_y_ranges = merge_panel_y_ranges(probe.ranges)

    @contextmanager
    def scanline_frame(self, visual):
        """호출한 장면의 위상을 공유하고 중첩 호출·예외 뒤에는 복원한다."""
        previous = self._scanline_visual
        self._scanline_visual = visual or ScanlineVisual()
        try:
            yield
        finally:
            self._scanline_visual = previous

    def menu(self, opacity, offset_x, input_state, *, scanline_visual=None):
        with self.scanline_frame(scanline_visual):
            super().menu(opacity, offset_x, input_state)

    def pause(self, opacity, input_state, *, scanline_visual=None):
        with self.scanline_frame(scanline_visual):
            super().pause(opacity, input_state)

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

    def accent_stroke(self, points, color, opacity):
        width = self.style['lock_accent_pixels']
        self.stroke(points, color, opacity, width)
        pattern = self.style['accent_hatching']
        if pattern['enabled']:
            shapes = hatched_stroke_mesh(points, width, pattern['pitch_start_pixels'],
                                          pattern['pitch_end_pixels'], pattern['width_pixels'])
            for shape in shapes:
                self.polygon(shape, self.config.colors['background'], opacity * pattern['opacity'], filled=True)

    def slanted_text(self, text, x, y, role, color, opacity=1, *, scale=1, slope=0, lean=0.15, align="left"):
        r = self.renderer
        width, height = r.text_size(text, role)
        if align == "right":
            x -= (width + max(0, lean * height / 2)) * scale
        plane = PerspectivePlane(x, y, max(1, width * scale), max(1, height * scale),
                                 depth=0, lean=lean, slope=slope)
        r.warped_text(text, 0, 0, role, color, plane.point, opacity, scale_x=scale, scale_y=scale)

    def panel(self, rect, opacity, offset_x=0, *, fill_opacity=None, corner_cut_ratio=None,
              fill_color=None, draw_border=True, slant_right=False, scanlines=True):
        """v2 전용 비대칭 외곽. 기존 금속 사각 패널을 호출하지 않는다."""
        x, y, width, height = rect
        x += offset_x
        c = self.config.colors
        cut = min(self.style["panel_cut_pixels"], width / 5, height / 3)
        points = (((x, y), (x + width - cut, y), (x + width, y + height), (x + cut, y + height))
                  if slant_right else
                  ((x + cut, y), (x + width, y), (x + width - cut, y + height), (x, y + height)))
        fill = self.style["surface_opacity"] if fill_opacity is None else min(fill_opacity, self.style["surface_opacity"])
        settings = self.style["panel_border"]
        self.renderer.filtered_polygons((points,), c["panel"] if fill_color is None else fill_color,
                                        opacity * fill, settings["filter_samples"])
        if scanlines:
            self.panel_scanlines(PanelGeometry(points, ()), opacity, self.style["panel_scanlines"]["panels"])
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

    def panel_layer(self, points, color, opacity, *, fill_opacity=None, grain=False, effect_surface=None):
        """임의 패널의 배경만 반투명·스캔 처리한다. 내용은 호출자가 이후 그린다."""
        fill = self.style["surface_opacity"] if fill_opacity is None else min(fill_opacity, self.style["surface_opacity"])
        self.polygon(points, color, opacity * fill, filled=True)
        mask = points if effect_surface is None else effect_surface
        self.panel_scanlines(PanelGeometry(mask, ()), opacity, self.style["panel_scanlines"]["panels"])
        if grain:
            settings = self.style["panel_film_grain"]
            frame = int(self._scanline_visual.elapsed_seconds * settings["frames_per_second"] + 1e-9) % settings["frame_count"]
            self.renderer.film_grain(mask, opacity * settings["opacity"], frame,
                                     tile_pixels=settings["tile_pixels"], cell_pixels=settings["cell_pixels"], seed=settings["seed"])

    def panel_border(self, parts, opacity, *, part_opacities=None):
        """테두리만 그린다. 각 조각의 표시값은 외부 효과 제어부가 공급할 수 있다."""
        for part in parts:
            visibility = 1 if part_opacities is None else part_opacities.get(part.part_id, 1)
            alpha = opacity * part.opacity * visibility
            if alpha > 0:
                self.renderer.filtered_polygons(part.polygons, self.ui_accent, alpha,
                                                self.style["panel_border"]["filter_samples"])

    def panel_scanlines(self, geometry, opacity, settings, visual=None):
        """느린 패턴 위에 빠른 밝은 띠를 겹친다. 내용·테두리는 이후 그린다."""
        alpha = opacity * settings["line_opacity"]
        if alpha <= 0:
            return
        if self._panel_probe is not None:
            self._panel_probe.include(geometry.surface)
            return
        scanline = self.style["panel_scanlines"]
        visual = visual or self._scanline_visual
        r = self.renderer
        r.scanline_layer(geometry.surface, self.ui_accent, alpha, scanline["spacing_pixels"],
                         scanline["thickness_pixels"], visual.line_offset_pixels)
        motion = scanline["motion"]
        band_height = motion["highlight_height_pixels"]
        band_top = visual.highlight_travel_pixels % (self.config.window["height"] + band_height) - band_height
        if self._panel_y_ranges is not None:
            bounds = r.panel_y_range(geometry.surface)
            if bounds is None:
                return
            band_top = panel_bright_band_top(self._panel_y_ranges, visual.highlight_travel_pixels,
                                             band_height, sum(bounds) / 2)
            if band_top is None:
                return
        r.scanline_layer(geometry.surface, self.config.colors["text"], opacity * motion["highlight_opacity"],
                         scanline["spacing_pixels"], scanline["thickness_pixels"], visual.line_offset_pixels,
                         bright_band=(band_top, band_height))

    def framed_panel(self, rect, opacity, *, fill_opacity=None, draw_border=True,
                     scanline_settings=None, scanline_visual=None):
        geometry = build_panel_geometry(rect, self.style["panel_cut_pixels"],
                                        self.style["panel_frame"], self.style["panel_border"])
        self.panel_surface(geometry, opacity, fill_opacity=fill_opacity)
        if scanline_settings is not None:
            self.panel_scanlines(geometry, opacity, scanline_settings, scanline_visual)
        if draw_border:
            self.panel_border(geometry.border_parts, opacity)

    def dialogue(self, info, opacity, scanline_visual=None, *, panel_visual=None):
        if info is None:
            return
        visual = panel_visual or DialoguePanelVisual()
        x, y, width, height = self.layout["dialogue"]
        center = x + width / 2, y + height / 2
        settings = self.style["panel_scanlines"]["dialogue"]
        if visual.height_ratio > 0 and visual.width_ratio > 0:
            geometry = build_panel_geometry((x, y, width, height), self.style["panel_cut_pixels"],
                                            self.style["panel_frame"], self.style["panel_border"])
            geometry = scale_panel_geometry(geometry, center, visual.width_ratio, visual.height_ratio)
            self.panel_surface(geometry, opacity, fill_opacity=settings["surface_opacity"])
            self.panel_scanlines(geometry, opacity, settings, scanline_visual)
            self.panel_border(geometry.border_parts, opacity)
        if visual.flash_opacity > 0 or (visual.height_ratio == 0 and visual.width_ratio > 0):
            self.dialogue_shutdown_line(center, width * visual.width_ratio, opacity,
                                        visual.flash_opacity or 0.4)
        if visual.text_opacity <= 0:
            return
        opacity *= visual.text_opacity
        padding_x, padding_y = self.style["dialogue_padding_pixels"]
        self.renderer.text(info.speaker, x + padding_x, y + padding_y, "dialogue_heading",
                           self.ui_accent, opacity)
        role = self.style["dialogue_body_role"]
        first_line = y + padding_y + self.style["dialogue_body_offset_pixels"]
        for index, line in enumerate(info.lines):
            self.renderer.rich_text(line, x + padding_x, first_line + index * self.style["dialogue_line_spacing_pixels"],
                                    role, self.config.colors["text"], opacity,
                                    max_width=width - padding_x * 2,
                                    bold_color=self.style["dialogue_key_color"],
                                    regular_opacity=self.style["dialogue_description_opacity"])

    def dialogue_shutdown_line(self, center, width, opacity, flash):
        """TV 종료의 얇은 가로 빛과 마지막 점. 면·테두리·본문과 분리한다."""
        x, y = center
        width = max(self.style["dialogue_motion"]["dot_width_pixels"], width)
        thickness = self.style["dialogue_motion"]["line_thickness_pixels"]
        for spread, alpha, color in ((5, 0.12, self.ui_accent), (2.5, 0.3, self.ui_accent),
                                      (1, 1, self.config.colors["text"])):
            half = thickness * spread / 2
            points = ((x - width / 2, y - half), (x + width / 2, y - half),
                      (x + width / 2, y + half), (x - width / 2, y + half))
            self.renderer.filtered_polygons((points,), color, opacity * flash * alpha,
                                            self.style["panel_border"]["filter_samples"])

    def ultimate_label(self, text, right, y, color, opacity, *, scale=1, slant_right=False):
        """필살기 문구와 작은 사선 패널을 같은 위치·투명도로 그린다."""
        width, height = self.renderer.text_size(text, "hud_small")
        padding_x, padding_y = self.style["ultimate_label_padding_pixels"]
        width, height = (width + 0.15 * height) * scale, height * scale
        self.panel((right - width - padding_x, y - padding_y,
                    width + padding_x * 2, height + padding_y * 2), opacity, fill_opacity=0.98,
                   fill_color=self.config.colors["panel_surface"], draw_border=False,
                   slant_right=slant_right, scanlines=False)
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
            self.panel_layer(points, c["ui_accent"] if hovered else c["panel_surface"], alpha,
                             fill_opacity=0.6 if pressed else 0.25 if hovered else 0.12)
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

    def meter(self, key, ratio, color, opacity, trailing_ratio=None, *, shape=None, border=None, rect=None,
              damage_flashes=()):
        """형상은 고정하고 채움만 자른다. 실제 자원 규칙은 계산하지 않는다."""
        r, c = self.renderer, self.config.colors
        x, y, width, height = self.layout[key] if rect is None else rect
        cut = min(18, height * 0.65)
        points = slanted_meter((x, y, width, height)) if shape is None else shape
        self.polygon(points, c["panel_surface"], opacity * self.style["surface_opacity"], filled=True)
        ratio = max(0.0, min(1.0, ratio))
        trail = ratio if trailing_ratio is None else max(ratio, min(1.0, trailing_ratio))
        for fill, fill_color in ((trail, c["health_loss"]), (ratio, c[color])):
            if fill > 0:
                self.polygon(quad_fill(points, fill), fill_color, opacity, filled=True)
        for flash in damage_flashes:
            low, high = max(ratio, flash.start_ratio), min(trail, flash.end_ratio)
            if high > low and flash.opacity > 0:
                left, right = quad_fill(points, low), quad_fill(points, high)
                self.polygon((left[1], right[1], right[2], left[2]), self.style["health_damage_flash"]["color"],
                             opacity * flash.opacity, filled=True)
        if border is not None:
            self.stroke(border + border[:1], self.ui_accent, opacity * 0.85, 1.5)
            return
        self.stroke(((x - cut - 7, y - 4), (x + width - cut + 3, y - 4),
                     (x + width + 7, y + height + 2)), self.ui_accent, opacity * 0.8)
        self.stroke(((x + 5, y + height + 4), (x + width * 0.63, y + height + 4)),
                     self.ui_accent, opacity * 0.35)

    def minimap(self, hud, opacity, scanline_visual=None):
        r, c = self.renderer, self.config.colors
        rect = Rect(*self.layout["minimap"])
        settings = self.style["panel_scanlines"]["minimap"]
        self.framed_panel((rect.x, rect.y, rect.width, rect.height), opacity,
                          fill_opacity=settings["surface_opacity"], draw_border=False,
                          scanline_settings=settings, scanline_visual=scanline_visual)
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
        r.text("MAP", rect.x, rect.y + rect.height + 6, "v2_map_label", c["muted"], opacity)

    def target(self, state, opacity, offset_x, *, draw_marker=True):
        r, c = self.renderer, self.config.colors
        hud, body = state.hud, state.target_body
        if body is None:
            return
        x, y, rx, ry = body_diamond((body.x, body.y, body.width, body.height), self.style["lock_body_scale"])
        if draw_marker:
            self.lock_marker(LockOnVisual("", body), opacity, offset_x)
        if hud.target:
            r.text(hud.target.name, x + offset_x, y + max(ry + 7, body.height * 2), "target_name", c["text"], opacity,
                   align="center", max_width=200)

    def lock_marker(self, visual, opacity, offset_x=0):
        r, c, body = self.renderer, self.config.colors, visual.body
        x, y, rx, ry = body_diamond((body.x, body.y, body.width, body.height), self.style["lock_body_scale"])
        x += offset_x
        angle = visual.angle_degrees * pi / 180
        x += visual.offset_pixels[0] / self.style['hud_scale']
        y += visual.offset_pixels[1] / self.style['hud_scale']
        def transform(dx, dy):
            return (x + (dx * cos(angle) - dy * sin(angle)) * visual.scale,
                    y + (dx * sin(angle) + dy * cos(angle)) * visual.scale)
        half_side = max(rx, ry) / 2 ** 0.5
        points = tuple(transform(dx, dy) for dx, dy in
                       ((-half_side, -half_side), (half_side, -half_side),
                        (half_side, half_side), (-half_side, half_side)))
        alpha = opacity * visual.opacity
        if alpha <= 0 or visual.scale <= 0:
            return
        self.stroke(points + points[:1], self.ui_accent, alpha, self.style["lock_thickness_pixels"])
        for position in (visual.border_position, visual.border_position + 2):
            self.accent_stroke(outline_segment(points, position - 0.325), c["text"], alpha)
        if visual.label_progress <= 0:
            return
        angle = atan2(points[0][1] - points[3][1], points[0][0] - points[3][0])
        label = "LOCK ON"
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
                      c["text"], label_point, alpha,
                      clip_rect=Rect(0, 0, label_width * visual.label_progress, label_height))
        if visual.label_progress < 1:
            cursor = label_width * visual.label_progress
            self.stroke((label_point(cursor, 0), label_point(cursor, label_height)), c["text"], alpha, 2)

    def health_hit_offset(self, visual):
        return tuple(value / self.style["hud_scale"] for value in visual.offset_pixels)

    def health_hit_blur(self, bounds, visual):
        settings = self.style["player_health_blur"]
        maximum = settings["max_length_pixels"]
        displacement = tuple(max(-maximum, min(maximum, speed * settings["shutter_seconds"]))
                             / self.style["hud_scale"] for speed in visual.velocity_pixels_per_second)
        return (self.renderer.directional_blur(bounds, displacement, settings["opacity"], settings["samples"])
                if any(abs(value) > 0.01 for value in displacement) else nullcontext())

    def player_health(self, hud, geometry, opacity, trailing_ratio, damage_flashes, hit_visual):
        r, c = self.renderer, self.config.colors
        dx, dy = self.health_hit_offset(hit_visual)
        shape = tuple((x + dx, y + dy) for x, y in geometry.hp_shape)
        border = tuple((x + dx, y + dy) for x, y in geometry.hp_outline)
        value = f"{hud.player_health.current:,.0f}"
        value_width, value_height = r.text_size(value, "v2_hp")
        x, top = border[0]
        gap = self.style["resource_label_gap_pixels"]
        hp_width, hp_height = r.text_size("HP", "hud_small")
        left, right = min(p[0] for p in border), max(max(p[0] for p in border), x + value_width + 9 + hp_width)
        bottom = max(p[1] for p in border)
        label_top = top - max(value_height, hp_height) - gap
        bounds = Rect(left - 4, label_top - 4, right - left + 8, bottom - label_top + 8)
        with self.health_hit_blur(bounds, hit_visual):
            self.meter("hp_bar", hud.player_health.ratio, "accent", opacity, trailing_ratio,
                       shape=shape, border=border, damage_flashes=damage_flashes)
            r.text(value, x, top - value_height - gap, "v2_hp", c["text"], opacity)
            r.text("HP", x + value_width + 9, top - hp_height - gap, "hud_small", c["muted"], opacity)

    def resources(self, state, opacity, offset_x, player_trailing_ratio, *, damage_flashes=(),
                  hit_visual=HealthHitVisual(), energy_flash=0, level_visual=None,
                  overdrive_visual=None, ultimate_visual=None, energy_tint_ratio=None):
        dx, dy = self.health_hit_offset(hit_visual)
        scope = self.renderer.translated(dx, dy) if dx or dy else nullcontext()
        with scope:
            self._resource_contents(state, opacity, offset_x, player_trailing_ratio, damage_flashes=damage_flashes,
                                    hit_visual=HealthHitVisual((0, 0), hit_visual.velocity_pixels_per_second),
                                    energy_flash=energy_flash, level_visual=level_visual,
                                    overdrive_visual=overdrive_visual, ultimate_visual=ultimate_visual,
                                    energy_tint_ratio=energy_tint_ratio)
        self.dash_indicator(state, opacity)

    def _resource_contents(self, state, opacity, offset_x, player_trailing_ratio, *, damage_flashes=(),
                           hit_visual=HealthHitVisual(), energy_flash=0, level_visual=None,
                           overdrive_visual=None, ultimate_visual=None, energy_tint_ratio=None):
        r, c = self.renderer, self.config.colors
        geometry = resource_geometry(self.layout, self.style["level_bevel_pixels"])
        self.player_health(state.hud, geometry, opacity, player_trailing_ratio, damage_flashes, hit_visual)
        x, y, width, height = self.layout["energy_bar"]
        outline, channel = geometry.energy_outline, geometry.energy_channel
        charge = 1 if state.overdrive else state.overdrive_charge_ratio
        tint = charge if energy_tint_ratio is None else energy_tint_ratio
        color = energy_color(c['energy'], self.style['overdrive_red'], tint)
        fill_color = energy_color(c['energy_fill'], self.style['overdrive_red'], tint)
        boundary_color = self.style['energy_boundary']['color']
        self.panel_layer(geometry.energy_body, c["panel"], opacity, grain=True, effect_surface=channel)
        self.polygon(geometry.level_shape, c["panel"], opacity * self.style["surface_opacity"], filled=True)
        self.stroke(outline + outline[:1], c["text"], opacity * 0.75, 1.5)
        self.polygon(channel, color, opacity * 0.1, filled=True)
        energy_alpha = opacity * breathing_opacity(self._scanline_visual.elapsed_seconds, **self.style["energy_breathing"])
        if state.energy_ratio > 0:
            filled = quad_fill(channel, state.energy_ratio)
            self.polygon(filled, fill_color, energy_alpha, filled=True)
            self.stroke((filled[1], filled[2]), boundary_color, energy_alpha, 2)
        if charge > 0:
            charged = quad_fill(channel, charge)
            self.polygon(charged, color, energy_alpha * 0.45, filled=True)
            self.stroke((charged[1], charged[2]), boundary_color, energy_alpha, 2)
        if energy_flash > 0:
            self.polygon(channel, color, opacity * energy_flash * 0.55, filled=True)
        self.stroke((outline[-1], geometry.level_shape[-2]),
                     color if charge > 0 else self.ui_accent, opacity, 2)
        ratio = charge if state.energy_level == 3 and state.energy_ratio == 1 else state.energy_ratio
        self.energy_boundary(channel, ratio, energy_alpha, overdrive=state.overdrive)
        overdrive_visual = overdrive_visual or OverdriveVisual(float(state.overdrive))
        self.overdrive_label(channel, overdrive_visual, energy_alpha)
        level_right = x + width + self.layout["energy_level_width_pixels"]
        settings = self.style['level_text']
        number_scale = settings['number_scale']
        digit_width = max(r.text_size(str(d), 'v2_level')[0] for d in range(10)) * number_scale
        number_height = r.text_size('0', 'v2_level')[1] * number_scale
        number_right = level_right - settings['right_inset_pixels']
        number_top = (geometry.level_top + self.layout['energy_bar'][1] + height + 4 - number_height) / 2
        label_scale = settings['label_scale']
        self.slanted_text('LV', number_right - digit_width * 2 - settings['gap_pixels'],
                          number_top + (number_height - r.text_size('LV', 'hud_small')[1] * label_scale) / 2,
                          'hud_small', c['ui_accent'], opacity, scale=label_scale, align='right')
        level_visual = level_visual or CounterVisual(state.energy_level, state.energy_level, 1, 1)
        old, new = f'{level_visual.previous_value:02}', f'{level_visual.value:02}'
        project = lambda px, py: (number_right - digit_width * 2 + px + (number_height / 2 - py) * 0.1,
                                  number_top + py)
        viewport = Rect(0, 0, digit_width * 2, number_height)
        for i, (before, after) in enumerate(zip(old, new)):
            self.rolling_digit(level_visual, before, after, i * digit_width, number_height,
                               'v2_level', c['muted'], project, opacity, number_scale, viewport)
        cx, cy = geometry.icon_center
        radius = geometry.icon_radius
        diamond = ((cx, cy - radius), (cx + radius, cy), (cx, cy + radius), (cx - radius, cy))
        self.polygon(diamond, c["panel"], opacity * self.style["surface_opacity"], filled=True)
        self.stroke(diamond + diamond[:1], c["text"], opacity * 0.9, 1.5)
        if state.ultimate_ready:
            visual = ultimate_visual or UltimateReadyVisual()
            settings = self.style['lock_motion']
            position = accent_position(visual.age, settings['move_seconds'], settings['hold_seconds'])
            for start in (position, position + 2):
                self.accent_stroke(outline_segment(diamond, start - 0.325), color, opacity * visual.opacity)
            if visual.flash > 0:
                self.polygon(diamond, c['text'], opacity * visual.flash * 0.45, filled=True)
                self.stroke(diamond + diamond[:1], c['text'], opacity * visual.flash,
                            self.style['lock_accent_pixels'] + 1)
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
        level = "LV. 03"
        key_height = r.text_size(key, "hud_small")[1]
        gap = self.style["ultimate_label_gap_pixels"]
        label_right = cx - radius / 2 - gap
        self.ultimate_label(key, label_right, cy - radius / 2 - key_height - gap,
                            c["text"], opacity)
        self.ultimate_label(level, label_right, cy + radius / 2 + gap,
                            c["muted"], opacity, scale=0.85, slant_right=True)

    def overdrive_label(self, channel, visual, opacity):
        if visual.opacity <= 0:
            return
        r, c = self.renderer, self.config.colors
        label, role = 'OVERDRIVE', 'v2_overdrive'
        sizes = [r.text_size(letter, role) for letter in label]
        text_width = sum(size[0] for size in sizes)
        center_x, center_y = (sum(point[i] for point in channel) / 4 for i in (0, 1))
        bar_width = ((channel[1][0] - channel[0][0]) + (channel[2][0] - channel[3][0])) / 2
        spacing = max(0, (bar_width * self.style['overdrive_width_ratio'] - text_width) / (len(label) - 1))
        width = text_width + spacing * (len(label) - 1)
        cursor = -width / 2
        glow_color = energy_color(c['energy'], self.style['overdrive_red'], 1)
        self.overdrive_entry_streak((center_x, center_y), bar_width, visual, glow_color, opacity)
        for index, (letter, (letter_width, letter_height)) in enumerate(zip(label, sizes)):
            x = center_x + (cursor + letter_width / 2) * visual.spread - letter_width / 2
            flash = visual.flash * (0.5 + 0.5 * sin(index * 2.4 + visual.spread * 18) ** 2)
            bloom = dict(self.style['overdrive_bloom'])
            bloom['glow_opacity'] *= 1 + 2 * flash
            r.neon_text(letter, x, center_y - letter_height / 2, role, c['text'],
                        opacity * visual.opacity * (1 - 0.4 * visual.flash + 0.4 * flash),
                        glow_color=glow_color, **bloom)
            cursor += letter_width + spacing

    def overdrive_entry_streak(self, center, bar_width, visual, color, opacity):
        """등장 순간 중앙에서 수평으로 빠르게 뻗는 빛. 유지 중에는 반복하지 않는다."""
        settings = self.style['overdrive_entry_streak']
        age = visual.entry_seconds
        expand, hold, fade = (settings[key] for key in ('expand_seconds', 'hold_seconds', 'fade_seconds'))
        if age <= 0 or age >= expand + hold + fade or visual.opacity <= 0:
            return
        progress = min(1, age / expand)
        brightness = progress ** 0.35 if age < expand else max(0, 1 - max(0, age - expand - hold) / fade) ** 2
        length = bar_width * settings['length_ratio'] * (0.12 + 0.88 * (1 - (1 - progress) ** 3))
        alpha = opacity * visual.opacity * settings['opacity'] * brightness
        x, y = center
        for width, ink, weight in ((settings['glow_width_pixels'], self.config.colors['text'], 0.18),
                                   (settings['width_pixels'] * 2, color, 0.5),
                                   (settings['width_pixels'], self.config.colors['text'], 1)):
            shape = ((x - length / 2, y), (x, y - width / 2),
                     (x + length / 2, y), (x, y + width / 2))
            self.polygon(shape, ink, alpha * weight, filled=True)

    def energy_boundary(self, channel, ratio, opacity, *, overdrive=False):
        if not (0 < ratio < 1 or overdrive and ratio == 1):
            return
        edge = quad_fill(channel, ratio)[1:3]
        time = self._scanline_visual.elapsed_seconds
        settings = self.style['energy_boundary']
        color = settings['color']
        pulse = 0.5 + 0.5 * sin(time * 17) ** 2
        strength = settings['overdrive_intensity'] if overdrive else 1
        self.stroke(edge, color, opacity * 0.25 * pulse, settings['glow_width_pixels'] * strength)
        self.stroke(edge, color, opacity * 0.85 * pulse, 1)

    def dash_indicator(self, state, opacity):
        """현재 가로 위치에서 아이콘·키 안내를 화면 하단 기준으로 배치한다."""
        r, c, settings = self.renderer, self.config.colors, self.style["dash_icon"]
        x = self.layout["dash_x"]
        label_width, label_height = r.text_size("SPACE", "hud_small")
        key_scale = settings["key_scale"]
        y = (self.config.window["height"] - settings["bottom_margin_pixels"] / self.style["hud_scale"]
             - label_height * key_scale)
        width, height = settings["chevron_width_pixels"], settings["height_pixels"]
        step, thickness = settings["spacing_pixels"], settings["thickness_pixels"]
        left = x + (label_width * key_scale - width - step) / 2
        top = y - settings["label_gap_pixels"] - height
        alpha = opacity * (1 if state.dash_ready else 0.25)
        for index, color in enumerate((self.ui_accent, c["text"])):
            px = left + step * index
            middle, bottom = top + height / 2, top + height
            quads = (((px, top), (px + thickness, top), (px + width, middle), (px + width - thickness, middle)),
                     ((px + width - thickness, middle), (px + width, middle), (px + thickness, bottom), (px, bottom)))
            r.filtered_polygons(quads, color, alpha, self.style["panel_border"]["filter_samples"])
        self.slanted_text("SPACE", x, y, "hud_small", c["text"], alpha, scale=key_scale)

    def weapons(self, hud, opacity, offset_x, *, loadout_visual=None, weapon_swap_visual=None):
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
            self.panel_layer(shape, c["panel_surface"], alpha, fill_opacity=0.5, grain=True)
            self.stroke(shape + shape[:1], self.ui_accent, alpha)
            r.neon_text(f"{index + 1:02}", tx + 15, ty + 3, "equipment_number", c["text"], alpha * self.style["weapon_text_opacity"],
                        **self.style["weapon_text_neon"])
        ranged_weight = (float(hud.active_weapon_kind == "ranged") if weapon_swap_visual is None
                         else weapon_swap_visual.weight_before())
        sliding = loadout_visual is not None and loadout_visual.moving
        swapping = weapon_swap_visual is not None and weapon_swap_visual.moving
        index = hud.active_loadout_index if loadout_visual is None else loadout_visual.incoming_index
        shift, fade = 0, 1
        motion, strength, maximum, samples = (0, 0), 0, 0, 33
        if sliding or swapping:
            settings = self.style["loadout_blur"] if sliding else self.style["weapon_swap_blur"]
            shutter, maximum = settings["shutter_seconds"], settings["max_length_pixels"]
            strength = settings["opacity"] if settings["samples"] else 0
            samples = max(33, settings["samples"])
            shift_delta = 0
            if sliding:
                leftmost = x - (self.style["weapon_depth_offset_pixels"] + self.style["weapon_card_cut_pixels"]
                                if self.style["weapon_card_shape"] == "trapezoid" else 0)
                distance = self.config.window["width"] - leftmost + self.config.data["loadout_slide"]["exit_padding_pixels"]
                shift, fade, index = loadout_visual.pose(distance)
                shift_delta = loadout_visual.velocity(distance) * shutter
            weight_delta = weapon_swap_visual.velocity * shutter if swapping else 0
            motion = shift_delta, weight_delta
        if fade > 0:
            self.weapon_cards(hud, hud.loadouts[index], opacity * fade, offset_x + shift,
                              ranged_weight=ranged_weight, blur_motion=motion, blur_strength=strength,
                              blur_max_length=maximum, blur_samples=samples)

    def weapon_cards(self, hud, loadout, opacity, offset_x, *, ranged_weight, blur_motion=(0, 0),
                     blur_strength=0, blur_max_length=0, blur_samples=33):
        r, c = self.renderer, self.config.colors
        x, y, width, height = self.layout["weapons"]
        x += offset_x
        for index, (kind, weapon) in enumerate((("melee", loadout.melee), ("ranged", loadout.ranged))):
            top = y + index * (height + 8)
            weight = ranged_weight if kind == "ranged" else 1 - ranged_weight
            alpha = opacity * (0.5 + 0.5 * weight)
            trapezoid = self.style["weapon_card_shape"] == "trapezoid"
            if trapezoid:
                cut = self.style["weapon_card_cut_pixels"]
                right = x + width - self.style["weapon_depth_offset_pixels"] * weight
                left, amount = right - width - index * cut, 1
            else:
                left, right = x + 22 * (1 - weight), x + width
                amount = self.style["inactive_weapon_scale"] + (1 - self.style["inactive_weapon_scale"]) * weight
            depth = self.style["weapon_depth_offset_pixels"] if trapezoid else 22
            motion_x = blur_motion[0] + depth * blur_motion[1] * (-1 if kind == "ranged" else 1)
            motion_x = max(-blur_max_length, min(blur_max_length, motion_x))
            bounds = Rect(left - 4, top - 4, right - left + 8, height + 8)
            with r.directional_blur(bounds, (motion_x, 0), blur_strength, blur_samples) if blur_strength else nullcontext():
                with r.scaled(amount, (right, top + height / 2)):
                    shape = (((left + cut, top), (right, top), (right, top + height), (left, top + height))
                             if trapezoid else ((left + 18, top), (right, top),
                                                (right - 18, top + height), (left, top + height)))
                    self.panel_layer(shape, c["panel_surface"], alpha, grain=True)
                    self.stroke((shape[0], shape[3], shape[2], shape[1]),
                                 self.ui_accent, alpha * 0.85)
                    self.stroke((shape[0], shape[3]), self.ui_accent,
                                 alpha * 0.95, self.style["weapon_outer_edge_pixels"])
                    self.stroke(((left + 28, top + 4), (right - 4, top + 4)),
                                self.ui_accent, alpha * 0.3)
                    image_width = right - left - 112 if trapezoid else width - 112
                    self.weapon_image(weapon, kind, Rect(left + 18, top + 11, image_width, height - 39), alpha)
                    r.neon_text("MELEE" if kind == "melee" else "RANGED", left + 17, top + height - 23,
                                "weapon_name", c["text"], alpha * self.style["weapon_text_opacity"],
                                **self.style["weapon_text_neon"])
                    if weapon.rounds is not None:
                        text = str(weapon.rounds)
                        r.neon_text(text, right - r.text_size(text, "v2_ammo")[0] - 16,
                                    top + 10, "v2_ammo", c["text"], alpha * self.style["weapon_text_opacity"],
                                    **self.style["weapon_text_neon"])

    def absorption(self, trails, opacity, particle_system=None, charge=0):
        color = energy_color(self.config.colors['energy'], self.style['overdrive_red'], charge)
        settings = self.style["absorption_trail"]
        if particle_system is not None:
            self.renderer.draw_compute_particles(particle_system, settings, color, self.config.colors["text"], opacity)
            return
        if self.renderer.draw_instanced_particles(trails, settings, color, self.config.colors["text"], opacity):
            return
        quads = []
        for trail in trails:
            ribbon = trail.ribbon(settings["tail_fraction"], settings["samples"])
            if ribbon:
                normals = []
                for index in range(len(ribbon)):
                    a = ribbon[max(0, index - 1)][0]
                    b = ribbon[min(len(ribbon) - 1, index + 1)][0]
                    length = max(1e-9, hypot(b[0] - a[0], b[1] - a[1]))
                    normals.append((-(b[1] - a[1]) / length, (b[0] - a[0]) / length))
                for width, ink, alpha in ((settings["head_width_pixels"] * 2, color, 0.85),
                                           (settings["head_width_pixels"] * 0.5, self.config.colors["text"], 0.9)):
                    sections = []
                    for (point, pressure), normal in zip(ribbon, normals):
                        dx, dy = (value * width * pressure / 2 for value in normal)
                        sections.append(((point[0] + dx, point[1] + dy), (point[0] - dx, point[1] - dy)))
                    for index, (a, b) in enumerate(zip(sections, sections[1:])):
                        first = self.renderer.rgba(ink, opacity * alpha * ribbon[index][1])
                        second = self.renderer.rgba(ink, opacity * alpha * ribbon[index + 1][1])
                        quads.append(((a[0], b[0], b[1], a[1]), (first, second, second, first), 1))
            if trail.progress <= 1:
                x, y = trail.point(trail.progress)
                for radius, ink, alpha in ((settings["orb_radius_pixels"] * 2.4, color, 0.1),
                                           (settings["orb_radius_pixels"], color, 0.9),
                                           (settings["orb_radius_pixels"] * 0.45, self.config.colors["text"], 1)):
                    points = ((x - radius, y - radius), (x + radius, y - radius),
                              (x + radius, y + radius), (x - radius, y + radius))
                    rgba = self.renderer.rgba(ink, opacity * alpha)
                    quads.append((points, (rgba,) * 4, 0))
        self.renderer.particle_quads(quads)

    def counter_base(self, project, width, ink_bottom, opacity):
        thickness = self.style["counter_plaque_height_pixels"]
        slant = self.style["counter_plaque_slant_pixels"]
        left, right = project(-14, ink_bottom - 1), project(width + 3, ink_bottom - 1)
        color = self.config.colors["counter_plaque"]
        self.panel_layer(counter_plaque(left, right, thickness, slant), color, opacity)
        distance = hypot(right[0] - left[0], right[1] - left[1])
        ux, uy = (right[0] - left[0]) / distance, (right[1] - left[1]) / distance
        cursor = left
        for index, (length, size, alpha) in enumerate(((13, 0.85, 0.55), (10, 0.65, 0.3), (7, 0.45, 0.12))):
            end = (cursor[0] - ux * 5, cursor[1] - uy * 5 - index * 0.8)
            start = (end[0] - ux * length, end[1] - uy * length)
            self.polygon(counter_plaque(start, end, thickness * size, slant * size),
                         color, opacity * alpha * self.style["surface_opacity"], filled=True)
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
        text_alpha = opacity * self.text_flicker()
        x = 0
        for before, after, slot_width in zip(old, new, widths):
            for projection, color in ((shadow, c['counter_shadow']), (project, c['text'])):
                self.rolling_digit(visual, before, after, x, height, role, color, projection,
                                   text_alpha, scale, viewport, slot_width * scale)
            x += slot_width * scale
        label_text = self.config.labels[label]
        label_role = f"{label}_label"
        label_width = r.text_size(label_text, label_role)[0]
        r.warped_text(label_text, width - label_width - self.style['counter_label_right_inset_pixels'],
                      ink_bottom + self.style["counter_plaque_height_pixels"] + self.style['counter_label_gap_pixels'],
                      label_role, c["muted"], project, text_alpha)

    def rolling_digit(self, visual, before, after, x, height, role, color, project, opacity, scale, viewport,
                      slot_width=None):
        """v01의 탄성 이동·퇴장 감쇠·방향성 잔상을 투영면 안에서 재사용한다."""
        r, settings = self.renderer, self.config.data['damage_counter']
        moving = visual.moving and before != after and after != ','
        faces = ((before, -height * visual.vertical_progress, (1 - visual.progress) ** settings['outgoing_fade_power']),
                 (after, height * (1 - visual.vertical_progress), 1)) if moving else ((after, 0, 1),)
        samples = settings['blur_samples'] if moving else 0
        p = visual.progress
        previous = replace(visual, elapsed_seconds=max(0, visual.elapsed_seconds - settings['blur_shutter_seconds']))
        travel = height * (visual.vertical_progress - previous.vertical_progress) if moving else 0
        strength = settings['blur_opacity'] * 4 * p * (1 - p) * min(1, abs(travel) / max(1, height * 0.2)) if samples else 0
        length = min(settings['blur_length_pixels'] * scale, abs(travel))
        direction = 1 if travel >= 0 else -1
        dx, dy = settings['blur_direction']
        norm = hypot(dx, dy)
        passes = [(0, 0, 1 - strength)]
        weight_sum = samples * (samples + 1) / 2
        for sample in range(samples, 0, -1):
            distance = length * sample / samples
            # 숫자가 지나온 쪽에 잔상을 남긴다. 탄성 반전 때는 방향도 뒤집는다.
            passes.append((-dx / norm * distance * direction, -dy / norm * distance * direction,
                           strength * (samples + 1 - sample) / weight_sum))
        for char, top, alpha in faces:
            if char == ' ':
                continue
            width = r.text_size(char, role)[0] * scale
            left = x + ((slot_width - width) / 2 if slot_width is not None else 0)
            for smear_x, smear_y, weight in passes:
                if weight > 0:
                    r.warped_text(char, left + smear_x, top + smear_y, role, color, project,
                                  opacity * alpha * weight, scale_x=scale, scale_y=scale, clip_rect=viewport)

    def combat(self, state, damage_visuals=(), opacity=1, offset_x=0, *, scanline_visual=None, **kwargs):
        with self.scanline_frame(scanline_visual):
            self._combat(state, damage_visuals, opacity, offset_x, scanline_visual=scanline_visual, **kwargs)

    def _combat(self, state, damage_visuals=(), opacity=1, offset_x=0, *,
               counter_visual=None, combo_visual=None, counters_opacity=1,
               cursor_position=None, player_trailing_ratio=None, target_trailing_ratio=None,
               absorption_trails=(), scanline_visual=None, dialogue_visual=None, lock_visuals=None,
               player_damage_flashes=(), target_damage_flashes=(), counter_message_opacity=None, player_screen=None,
               loadout_visual=None, weapon_swap_visual=None,
               player_hit_visual=HealthHitVisual(), target_hit_visual=HealthHitVisual(), particle_system=None,
               defeated_targets=(), energy_flash=0, level_visual=None, overdrive_visual=None, ultimate_visual=None,
               energy_tint_ratio=None):
        r, c, hud = self.renderer, self.config.colors, state.hud
        scale = self.style["hud_scale"]
        width, height = self.config.window["width"], self.config.window["height"]
        with r.scaled(self.style["map_scale"], self.layout["minimap"][:2]):
            self.minimap(hud, opacity, scanline_visual)
        self.radar(hud.radar_contacts, opacity, center=player_screen)
        body = state.target_body
        target_anchor = ((body.x + body.width / 2, body.y + body.height / 2)
                         if body is not None else self.config.actor_anchor("target"))
        with r.scaled(scale, target_anchor):
            self.target(state, opacity, offset_x, draw_marker=lock_visuals is None)
            x, y, bar_width, bar_height = self.layout["target_hp"]
            dx, dy = self.layout["target_hp_offset_pixels"]
            x, y = target_anchor[0] + dx, target_anchor[1] + dy
            hit_x, hit_y = self.health_hit_offset(target_hit_visual)
            x, y = x + hit_x, y + hit_y
            target_rect = (x, y, bar_width, bar_height)
            if hud.target and hud.target.health.current > 0:
                self.meter("target_hp", hud.target.health.ratio, "enemy", opacity, target_trailing_ratio,
                           rect=target_rect, damage_flashes=target_damage_flashes)
                r.text("TARGET", x + bar_width, y + bar_height + 4, "target_heading", c["muted"], opacity, align="right")
        for visual in defeated_targets:
            body = visual.body
            center = (body.x + body.width / 2, body.y + body.height / 2)
            dx, dy = self.layout['target_hp_offset_pixels']
            _, _, bar_width, bar_height = self.layout['target_hp']
            rect = (center[0] + dx, center[1] + dy, bar_width, bar_height)
            with r.scaled(scale, center):
                self.meter('target_hp', visual.current_ratio, 'enemy', opacity * visual.opacity,
                           visual.trailing_ratio, rect=rect)
                r.text('TARGET', rect[0] + bar_width, rect[1] + bar_height + 4, 'target_heading',
                       c['muted'], opacity * visual.opacity, align='right')
        if lock_visuals is not None:
            for visual in lock_visuals:
                body = visual.body
                with r.scaled(scale, (body.x + body.width / 2, body.y + body.height / 2)):
                    self.lock_marker(visual, opacity, offset_x)
        with r.scaled(scale, (width / 2, height)):
            self.resources(state, opacity, offset_x, player_trailing_ratio, damage_flashes=player_damage_flashes,
                           hit_visual=player_hit_visual, energy_flash=energy_flash, level_visual=level_visual,
                           overdrive_visual=overdrive_visual, ultimate_visual=ultimate_visual,
                           energy_tint_ratio=energy_tint_ratio)
        with r.scaled(self.style["equipment_scale"], (width, height)):
            self.weapons(hud, opacity, offset_x, loadout_visual=loadout_visual,
                         weapon_swap_visual=weapon_swap_visual)
        alpha = opacity * counters_opacity
        combo_visual = combo_visual or CounterVisual(hud.combo_count, hud.combo_count, 1, 1)
        counter_visual = counter_visual or CounterVisual(hud.total_damage_dealt, hud.total_damage_dealt, 1, 1)
        for visual, role, label, y in ((combo_visual, "combo_number", "combo", self.layout["hit_y"]),
                                     (counter_visual, "damage_total", "damage", self.layout["damage_y"])):
            settings = self.style["counters"][label]
            right = width - settings["right_margin_pixels"]
            with r.scaled(scale * settings["ui_scale"], (right, y)):
                self.perspective_counter(visual, role, label, y, alpha)
        counter_alpha = float(state.counter) if counter_message_opacity is None else counter_message_opacity
        if counter_alpha > 0:
            text_scale = self.style["counter_text_scale"]
            with r.scaled(scale, self.layout["counter_message"]):
                r.text("COUNTER!", *self.layout["counter_message"], "v2_counter", c["warning"],
                       opacity * counter_alpha, scale_x=text_scale, scale_y=text_scale)
        for visual in damage_visuals:
            with r.scaled(scale, (visual.x, visual.y)):
                self.damage_number(visual, opacity, offset_x)
        self.absorption(absorption_trails, opacity, particle_system,
                        (1 if state.overdrive else state.overdrive_charge_ratio) if energy_tint_ratio is None else energy_tint_ratio)
        self.dialogue(state.dialogue, opacity, scanline_visual, panel_visual=dialogue_visual)
        if cursor_position is not None:
            x, y = cursor_position
            with r.scaled(scale, (x, y)):
                r.ring(x, y, 18, 2, c["crosshair"], opacity)
                r.line(x - 24, y, x - 9, y, c["crosshair"], opacity)
                r.line(x + 9, y, x + 24, y, c["crosshair"], opacity)
