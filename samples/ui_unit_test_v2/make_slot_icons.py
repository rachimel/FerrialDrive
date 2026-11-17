"""기본 도형 슬롯 PNG 준비
미사일·카운터·빈 슬롯을 설정 색상과 크기로 출력한다. 게임 에셋을 사용하지 않는다.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw


def build_slot_icon(config, kind, *, include_panel=True):
    style = config["v2"]["style"]
    settings, colors = style["shared_swap_slot"], config["colors"]
    diameter = settings["diameter_pixels"]
    samples = 4
    size = diameter * samples
    image = Image.new("RGBA", (size, size))

    def rgba(color, opacity):
        return (*tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)), round(255 * opacity))

    def layer():
        surface = Image.new("RGBA", image.size)
        return surface, ImageDraw.Draw(surface)

    surface, draw = layer()
    border = style["weapon_card"]["auxiliary_border_pixels"] * samples
    bounds = (border / 2, border / 2, size - border / 2 - 1, size - border / 2 - 1)
    draw.ellipse(bounds, fill=rgba(colors["panel_surface"], style["surface_opacity"]),
                 outline=(None if kind == "panel" else rgba(colors["ui_accent"], style["weapon_card"]["auxiliary_border_opacity"])),
                 width=round(border))
    if include_panel:
        image.alpha_composite(surface)

    def points(shape):
        return tuple((size * (0.5 + (u - 0.5) * settings["icon_scale"]),
                      size * (0.5 + (v - 0.5) * settings["icon_scale"])) for u, v in shape)

    def stroke(shape, opacity):
        surface, draw = layer()
        draw.line(points(shape), fill=rgba(colors["text"], opacity),
                  width=round(settings["icon_stroke_pixels"] * samples), joint="curve")
        image.alpha_composite(surface)

    def fill(shape, opacity):
        surface, draw = layer()
        draw.polygon(points(shape), fill=rgba(colors["text"], opacity))
        image.alpha_composite(surface)

    if kind == "back_weapon":
        for mirror in (False, True):
            shape = tuple((1 - u if mirror else u, v) for u, v in
                          ((.20, .26), (.27, .19), (.39, .24), (.41, .63), (.32, .72), (.23, .65)))
            fill(shape, .14)
            stroke(shape + shape[:1], .9)
            for y in (.32, .44):
                stroke(tuple((1 - u if mirror else u, v) for u, v in ((.24, y), (.37, y + .025))), .7)
        fill(((.46, .36), (.54, .36), (.54, .77), (.46, .77)), .7)
        for shape in (((.35, .61), (.46, .69)), ((.65, .61), (.54, .69))):
            stroke(shape, .8)
    elif kind == "counter":
        shield = ((.27, .24), (.73, .24), (.68, .61), (.5, .8), (.32, .61))
        stroke(shield + shield[:1], .85)
        stroke(((.38, .56), (.61, .38)), 1)
    return image.resize((diameter * 2, diameter * 2), Image.Resampling.LANCZOS)


def main():
    directory = Path(__file__).resolve().parent
    config = json.loads((directory / "ui_config.json").read_text(encoding="utf-8"))
    settings = config["v2"]["style"]["shared_swap_slot"]
    images = {**settings["images"], "panel": settings["panel_image"]}
    for kind, path in images.items():
        destination = directory / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        build_slot_icon(config, kind, include_panel=not Path(path).stem.endswith("_glyph")).save(destination)


if __name__ == "__main__":
    main()
