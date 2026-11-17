"""일시정지 시안의 연결부·겹친 베젤·스캔 표면. 입력과 게임 상태는 소유하지 않는다."""

from math import cos, pi, sin

from ferrial_drive.ui.components import Rect
from .panels import PanelGeometry
from .pause_motion import PauseButtonVisual


def draw_textured_button(view, button, rect, opacity, visual, *, hovered, pressed):
    """원본 텍스처를 보존하고 선택 영역만 버튼 크기로 표시한다."""
    r, c = view.renderer, view.config.colors
    settings = view.config.data["pause"]["button_style"]
    sx, sy = rect.width / 420, rect.height / 94
    point = lambda x, y: (rect.x + x * sx, rect.y + y * sy)
    surface = tuple(point(x, y) for x, y in settings["texture_surface_points"])
    noise = view.style["panel_film_grain"]
    grain = (noise["opacity"], noise["tile_pixels"], noise["cell_pixels"], noise["seed"])
    fill = c["panel_pressed"] if pressed else c["panel_hover"] if hovered else c["panel"]
    r.filtered_polygons((surface,), fill, opacity * settings["surface_opacity"],
                        settings["filter_samples"], grain=grain)
    view.panel_scanlines(PanelGeometry(surface, ()), opacity,
                         {"line_opacity": settings["scanline_opacity"]})
    height = settings["band_height_pixels"] * sy
    travel = view._scanline_visual.elapsed_seconds * settings["band_speed_pixels_per_second"]
    top = rect.y + 11 * sy + travel % (71 * sy + height) - height
    r.scanline_layer(surface, c["energy"], opacity * settings["band_opacity"], 1, 1, 0,
                     bright_band=(top, height))
    r.image(view.pause_bezel_path, rect, opacity,
            source_rect=Rect(*settings["bezel_source_rect_pixels"]), preserve_aspect=False)
    cx, cy = point(*settings["texture_light_center_pixels"])
    light = .12 + .88 * visual.light_opacity
    # 호버 광량만 호흡한다. 원본 금속의 색·광택은 변경하지 않는다.
    for radius, thickness, strength in ((12, 2, .15), (9, 1.4, .65), (4, 3, 1)):
        r.ring(cx, cy, radius * sx, thickness * sx, c["energy"], opacity * light * strength)
    if visual.hover_ratio > 0:
        chevron = tuple(point(x, y) for x, y in ((65, 37), (71, 46), (65, 55)))
        view.stroke(chevron, c["energy"], opacity * visual.hover_ratio, 1.6)
    role = settings["font_role"]
    _, text_height = r.text_size(button.label, role)
    r.text(button.label, rect.x + settings["text_inset_pixels"] * sx,
           rect.y + 46 * sy - text_height / 2 + (1 if pressed else 0), role, c["text"], opacity,
           max_width=rect.width - (settings["text_inset_pixels"] + 30) * sx)


def draw_pause_button(view, button, input_state, opacity, offset_x=0, offset_y=0):
    r, c = view.renderer, view.config.colors
    settings = view.config.data["pause"]["button_style"]
    hovered = button.enabled and input_state.hovered_id == button.button_id
    pressed = hovered and input_state.pressed_id == button.button_id
    visual = view._pause_button_visuals.get(button.button_id)
    if visual is None:
        motion = settings.get("hover_motion", {})
        period = motion.get("breathing_seconds", 1.4)
        minimum = motion.get("minimum_light", .35)
        pulse = (1 + cos(view._scanline_visual.elapsed_seconds / period * 2 * pi)) / 2
        visual = PauseButtonVisual(float(hovered), -motion.get("offset_pixels", 8) * hovered,
                                   (minimum + (1 - minimum) * pulse) * hovered)
    # 표시만 정수 px로 이동하고 입력용 Rect와 형상 캐시는 고정한다.
    rect = button.rect.translated(offset_x + round(visual.offset_pixels), offset_y)
    x, y, width, height = rect.x, rect.y, rect.width, rect.height
    sx, sy = width / 420, height / 94
    alpha = opacity * (1 if button.enabled else settings["disabled_opacity"])
    if view.pause_bezel_path is not None:
        draw_textured_button(view, button, rect, alpha, visual, hovered=hovered, pressed=pressed)
        return
    accent = c["energy"] if hovered else view.ui_accent

    def points(vertices):
        return tuple((x + px * sx, y + py * sy) for px, py in vertices)

    def plate(vertices, color, amount=1, *, grain=False):
        noise = view.style["panel_film_grain"]
        texture_grain = ((noise["opacity"], noise["tile_pixels"], noise["cell_pixels"], noise["seed"])
                         if grain else None)
        r.filtered_polygons((points(vertices),), color, alpha * amount,
                            settings["filter_samples"], grain=texture_grain)

    def stroke(vertices, color, amount=1, thickness=1):
        view.stroke(points(vertices), color, alpha * amount, thickness)

    # 아래쪽 독립 레일과 왼쪽의 두꺼운 연결 프레임을 표면 뒤에 겹친다.
    plate(((53, 78), (391, 78), (415, 74), (420, 91), (63, 91), (49, 84)), c["background"], .95)
    plate(((55, 81), (392, 81), (413, 78), (416, 87), (64, 87)), c["panel_surface"], .95)
    stroke(((64, 88), (416, 88), (413, 80)), accent, .6, 1.3)
    outside = ((40, 1), (23, 20), (13, 47), (25, 75), (43, 93))
    inside = ((59, 4), (43, 25), (34, 47), (44, 69), (61, 91))
    for index in range(4):
        plate((outside[index], inside[index], inside[index + 1], outside[index + 1]), c["panel_surface"], .95)
    stroke(((40, 2), (25, 21), (15, 47), (26, 74), (43, 92)), accent, .85, 2)
    stroke(((49, 6), (34, 24), (26, 47), (37, 73), (51, 88)), c["text"], .38, 1.2)

    outer = ((56, 7), (397, 7), (418, 23), (414, 67), (397, 82),
             (59, 82), (40, 69), (29, 47), (40, 23))
    face = ((61, 14), (393, 14), (409, 27), (405, 64), (393, 74),
            (64, 74), (48, 63), (39, 47), (48, 28))
    plate(outer, c["background"], .95)
    plate(outer, c["panel_surface"], .9 if hovered else .72)
    plate(face, c["panel_pressed"] if pressed else c["panel_hover"] if hovered else c["panel"],
          settings["surface_opacity"], grain=True)
    surface = points(face)
    view.panel_scanlines(PanelGeometry(surface, ()), alpha,
                         {"line_opacity": settings["scanline_opacity"]})
    band_height = settings["band_height_pixels"] * sy
    travel = view._scanline_visual.elapsed_seconds * settings["band_speed_pixels_per_second"]
    band_top = y + 14 * sy + travel % (60 * sy + band_height) - band_height
    r.scanline_layer(surface, c["energy"], alpha * settings["band_opacity"], 1, 1, 0,
                     bright_band=(band_top, band_height))

    # 표면 명암과 끊어진 외곽선으로 베젤과 발광면의 두께를 구분한다.
    stroke(((42, 24), (57, 8), (397, 8), (416, 23)), accent, 1 if hovered else .72, 1.5)
    stroke(((49, 29), (62, 15), (392, 15), (406, 27)), c["text"], .3)
    stroke(((40, 63), (59, 81), (397, 81), (413, 67)), accent, .9 if hovered else .48, 1.5)
    stroke(((414, 31), (411, 57)), c["text"], .5 if hovered else .2)
    stroke(((75, 21), (123, 21)), accent, .7 if hovered else .3, 1.2)
    stroke(((347, 68), (390, 68), (398, 61)), accent, .7 if hovered else .3, 1.2)

    # 동심 연결부와 열린 바깥 프레임은 모든 버튼에서 같은 형태를 쓴다.
    center = (26, 47)
    circle = lambda radius: tuple((center[0] + cos(index * pi / 20) * radius,
                                   center[1] + sin(index * pi / 20) * radius) for index in range(40))
    plate(circle(15), c["background"], 1)
    for radius, color, strength, thickness in ((13, accent, .95, 1.8), (8, c["text"], .55, 1)):
        ring = tuple((center[0] + cos(index * pi / 24) * radius,
                      center[1] + sin(index * pi / 24) * radius) for index in range(49))
        stroke(ring, color, strength, thickness)
    plate(circle(4), accent, .2 + .8 * visual.light_opacity)
    stroke(((2, 47), (10, 47)), accent, .8, 2)
    if hovered:
        stroke(((65, 35), (71, 44), (65, 53)), c["energy"], 1, 2)

    role = settings["font_role"]
    _, text_height = r.text_size(button.label, role)
    r.text(button.label, x + settings["text_inset_pixels"] * sx,
           y + 44 * sy - text_height / 2 + (1 if pressed else 0), role, c["text"], alpha,
           max_width=width - (settings["text_inset_pixels"] + 30) * sx)


def draw_pause_menu(view, opacity, input_state):
    config, r = view.config, view.renderer
    c, settings = config.colors, config.data["pause"]
    r.rect(Rect(0, 0, config.window["width"], config.window["height"]),
           c["background"], opacity * settings["dim_opacity"])
    view.buttons("pause", input_state, opacity, 0)
    footer = settings["footer"]
    if view.pause_logo_path is not None:
        r.image(view.pause_logo_path, Rect(*footer["logo_rect_pixels"]), opacity)
    else:
        # 로컬 로고가 없는 공개 시연에서는 기존 제목 글꼴을 사용한다.
        x, y = footer["logo_position_pixels"]
        role = footer["logo_font_role"]
        first, second = config.labels["menu_title_first"], config.labels["menu_title_second"]
        width, _ = r.text_size(first, role)
        r.text(first, x, y, role, c["text"], opacity * .85)
        r.text(second, x + width + footer["logo_gap_pixels"], y, role, view.ui_accent, opacity * .85)
    right, y = footer["heading_position_pixels"]
    r.text(config.labels["pause_heading"], right, y, footer["heading_font_role"], c["text"],
           opacity, align="right")
