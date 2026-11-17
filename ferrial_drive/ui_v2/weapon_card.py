"""무기 카드 시안의 내용 표시. 입력·전환 시간·게임 속성 판정을 소유하지 않는다."""

from math import cos, hypot, pi, sin

from ferrial_drive.ui.components import Rect


def draw_attribute_icon(view, attribute, x, y, size, opacity):
    """불은 도형으로, 아직 도안이 없는 추가 속성은 머리글자로 표시한다."""
    color = view.config.colors["text"]
    if attribute.upper() == "FIRE":
        flame = ((0.48, 0), (0.68, 0.33), (0.82, 0.23), (0.95, 0.62),
                 (0.78, 0.93), (0.38, 1), (0.08, 0.75), (0.12, 0.43),
                 (0.34, 0.58), (0.31, 0.27))
        view.polygon(tuple((x + u * size, y + v * size) for u, v in flame),
                     color, opacity, filled=True)
    else:
        view.renderer.text(attribute[:1].upper(), x + size / 2, y, "hud_small", color,
                           opacity, align="center", scale_x=0.8, scale_y=0.8)


def draw_auxiliary_slot(view, weapon, left, top, diameter, opacity):
    """이미지 캐시를 재사용하며 투명 문양은 공통 원형 패널 위에 합성한다."""
    settings = view.style["shared_swap_slot"]
    kind = "empty" if weapon.auxiliary_image_path else weapon.auxiliary_kind or "empty"
    path = view.config.path.parent / settings["images"][kind]
    if kind in settings.get("glyph_kinds", []):
        radius = diameter / 2
        circle = tuple((left + radius + cos(i * pi / 32) * radius,
                        top + radius + sin(i * pi / 32) * radius) for i in range(64))
        view.renderer.filtered_polygons((circle,), view.config.colors["panel_surface"],
                                        opacity * view.style["surface_opacity"], 2)
        if kind != "counter":
            border = view.style["weapon_card"]["auxiliary_border_pixels"]
            quads = []
            for a, b in zip(circle, circle[1:] + circle[:1]):
                length = hypot(b[0] - a[0], b[1] - a[1])
                nx, ny = -(b[1] - a[1]) / length * border / 2, (b[0] - a[0]) / length * border / 2
                quads.append(((a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny),
                              (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)))
            view.renderer.filtered_polygons(tuple(quads), view.ui_accent,
                opacity * view.style["weapon_card"]["auxiliary_border_opacity"], 2)
        inset = settings["glyph_inset_pixels"]
        view.renderer.image(path, Rect(left + inset, top + inset, diameter - inset * 2, diameter - inset * 2), opacity,
                            tint=view.config.colors["text"] if view.hud_theme is not None else "#FFFFFF")
        return
    view.renderer.image(path, Rect(left, top, diameter, diameter), opacity)
    if weapon.auxiliary_image_path:
        size = diameter * settings["icon_scale"] * 0.75
        view.renderer.image(weapon.auxiliary_image_path,
                            Rect(left + (diameter - size) / 2, top + (diameter - size) / 2, size, size), opacity)


def draw_weapon_card(view, weapon, kind, left, top, right, height, opacity):
    """카드 전체가 호출자의 이동·배율·투명도·블러 안에서 함께 그려진다."""
    r, c, settings = view.renderer, view.config.colors, view.style["weapon_card"]
    gap = settings["content_left_pixels"]
    content_left = left + gap
    band_height = settings["band_height_pixels"]
    band_top = top + height - band_height
    spine_width = settings["spine_width_pixels"]
    spine_top = top + 1
    spine_bottom = top + height
    slope = settings["spine_slant_pixels"] / (height - 1)
    horizontal_width = spine_width * hypot(1, slope)
    upper_width = settings["spine_upper_width_pixels"]
    upper_horizontal_width = upper_width * hypot(1, slope)

    def spine_x(y):
        return content_left + slope * (spine_bottom - y)

    spine_band_x = spine_x(band_top)
    label_width = settings["kind_width_pixels"]
    label_left = right - label_width
    right_cut = settings["right_cut_pixels"]
    band = ((spine_band_x, band_top), (label_left - 5, band_top),
            (label_left, band_top + 5), (right, band_top + 5),
            (right - right_cut, top + height), (content_left, top + height))
    # 단차가 있는 띠는 볼록한 두 면으로 나눠 삼각형이 오목한 모서리를 침범하지 않게 한다.
    main_band = band[:3] + ((label_left, top + height), band[-1])
    kind_band = (band[2], band[3], band[4], (label_left, top + height))
    for surface in (main_band, kind_band):
        view.panel_layer(surface, c["panel_surface"], opacity, grain=True)
    if weapon.base_attribute:
        text_left = spine_band_x + horizontal_width + 5
        clip = Rect(text_left, band_top, max(0, label_left - text_left - 9), band_height)
        spacing = settings.get("attribute_letter_spacing_pixels", 0)
        tw, th = r.text_size(weapon.base_attribute, "v2_weapon_attribute", letter_spacing_pixels=spacing)
        scale = min(1, clip.width / max(1, tw))
        r.text(weapon.base_attribute, clip.x, band_top + (band_height - th) / 2,
               "v2_weapon_attribute", c["text"], opacity * settings["attribute_opacity"],
               scale_x=scale, clip_rect=clip, letter_spacing_pixels=spacing,
               stroke_inset_pixels=settings.get("attribute_stroke_inset_pixels", 0))
    # 가는 선의 아래 시작점을 굵은 선의 오른쪽 위 끝에 붙인다.
    upper_bottom = spine_band_x + horizontal_width
    upper_top = upper_bottom + slope * (band_top - spine_top)
    line_mid_x = (upper_bottom + upper_top + upper_horizontal_width) / 2
    content_start = max(line_mid_x, upper_top + upper_horizontal_width) + settings["content_gap_pixels"]
    lower = ((content_left, spine_bottom), (spine_band_x, band_top),
             (spine_band_x + horizontal_width, band_top), (content_left + horizontal_width, spine_bottom))
    view.polygon(lower, view.ui_accent, opacity * 0.9, filled=True)
    upper = ((upper_bottom, band_top), (upper_top, spine_top),
             (upper_top + upper_horizontal_width, spine_top), (upper_bottom + upper_horizontal_width, band_top))
    view.polygon(upper, view.ui_accent, opacity * 0.9, filled=True)

    text_alpha = opacity * view.style["weapon_text_opacity"]
    name_x = content_start
    ammo_width = 0 if weapon.rounds is None else r.text_size(str(weapon.rounds), "v2_ammo")[0]
    ammo_reserve = max(settings["ammo_min_width_pixels"], ammo_width + 12)
    name_width = max(1, right - name_x - ammo_reserve)
    name_size = r.text_size(weapon.name, "v2_weapon_name")
    name_scale = min(1, name_width / max(1, name_size[0]))
    r.text(weapon.name, name_x, top + 2, "v2_weapon_name", c["text"], text_alpha,
           scale_x=name_scale, scale_y=name_scale)
    image_top = top + settings["image_top_pixels"]
    image_left = content_start
    image_width = max(1, right - image_left - ammo_reserve)
    view.weapon_image(weapon, kind, Rect(image_left, image_top, image_width,
                                       max(1, band_top - image_top - 5)), opacity)
    if weapon.rounds is not None:
        r.neon_text(str(weapon.rounds), right - ammo_width - 6, top + 9, "v2_ammo", c["text"],
                    text_alpha, gradient_bottom_ratio=settings.get("ammo_gradient_bottom_ratio", 1),
                    **view.style["weapon_text_neon"])
    label = "MELEE" if kind == "melee" else "RANGED"
    label_w, label_h = r.text_size(label, "v2_weapon_kind")
    label_scale = min(1, (label_width - right_cut - 9) / max(1, label_w), (band_height - 7) / max(1, label_h))
    r.text(label, right - right_cut - 6, band_top + 6 + (band_height - 6 - label_h * label_scale) / 2,
           "v2_weapon_kind", c["text"], text_alpha, align="right", scale_x=label_scale, scale_y=label_scale)

    icon_size = settings["additional_icon_pixels"]
    step = icon_size + settings["additional_icon_gap_pixels"]
    # 영역이 좁으면 추가 속성 아이콘 전체를 같은 비율로 줄인다.
    icon_width = max(0, len(weapon.additional_attributes) * step - settings["additional_icon_gap_pixels"])
    icon_scale = min(1, ammo_reserve / max(1, icon_width))
    for index, attribute in enumerate(weapon.additional_attributes):
        draw_attribute_icon(view, attribute, right - icon_width * icon_scale + index * step * icon_scale,
                            band_top - icon_size * icon_scale - 4, icon_size * icon_scale, text_alpha)
    # 보조 기능은 HUD의 공통 스왑 슬롯에서 한 번 표시한다.
