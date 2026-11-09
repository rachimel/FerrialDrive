"""8방향·4프레임의 분리 도형 메카. 실제 게임 모델을 요구하지 않는다."""

import json
from pathlib import Path

from samples.asset_loader.make_sample import write_png


def write_sample(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    directions = ("s", "sw", "w", "nw", "n", "ne", "e", "se")
    shapes = {
        "body": ((30, 18, 66, 75), (122, 145, 160, 255)),
        "left_hand": ((18, 35, 52, 53), (75, 190, 225, 255)),
        "right_hand": ((43, 49, 84, 63), (235, 133, 105, 255)),
        "sheath": ((33, 25, 42, 85), (160, 114, 190, 255)),
    }
    animations = [{"name": "equipped_idle/" + direction, "fps": 8,
                   "frames": [{"rect": [frame * 96, 768 - (row + 1) * 96, 96, 96], "pivot": [48, 10]}
                              for frame in range(4)]} for row, direction in enumerate(directions)]
    paths = {}
    for owner, (box, color) in shapes.items():
        def pixel(x, y, bounds=box, value=color):
            px, py = x % 96, y % 96 - x // 96 % 2
            left, top, right, bottom = bounds
            return value if left <= px < right and top <= py < bottom else (0, 0, 0, 0)
        write_png(directory / (owner + ".png"), 384, 768, pixel)
        data = {"version": 1, "coordinates": "bottom-left", "image": {"path": owner + ".png", "size": [384, 768]},
                "animations": animations}
        path = directory / (owner + ".json")
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        paths[owner] = {"sheet": str(path), "energy_sheet": ""}
    for owner in ("body", "sheath"):
        mask_name = owner + "_energy"
        def mask(x, y, target=owner):
            px, py = x % 96, y % 96 - x // 96 % 2
            hit = 42 <= px < 54 and 25 <= py < 29 if target == "body" else 35 <= px < 39 and 30 <= py < 80
            return (255, 255, 255, 255) if hit else (0, 0, 0, 0)
        write_png(directory / (mask_name + ".png"), 384, 768, mask)
        data = {"version": 1, "coordinates": "bottom-left", "image": {"path": mask_name + ".png", "size": [384, 768]},
                "animations": animations}
        path = directory / (mask_name + ".json")
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        paths[owner]["energy_sheet"] = str(path)
    return paths
