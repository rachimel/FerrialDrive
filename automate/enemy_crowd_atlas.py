"""기존 PBR 적 파츠에서 군집 표시용 포즈를 고정 시트로 내보낸다."""

import argparse
import ctypes as ct
import json
from pathlib import Path
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ferrial_drive.combat.enemy_sprites import PART_DIRECTIONS, load_enemy_part_sprites
from ferrial_drive.rendering.canvas import PicoCanvas
from ferrial_drive.rendering.enemy_crowd_atlas import CROWD_ATLAS_SIZE, CROWD_CELL_SIZE, CROWD_SHADOW_RECT
from ferrial_drive.rendering.part_motion_atlas import frame_state
from ferrial_drive.rendering.part_upscale import render_target
from ferrial_drive.settings import GameSettings


def pose_intervals(sprite, name):
    attacks = {"attack": sprite.attack_frames}
    attacks.update((spec["motion"], spec["attack_frames"]) for spec in sprite.attack_motions.values())
    duration = sprite.duration(name)
    if name in attacks:
        edges = [0, *(frame / 12 for frame in attacks[name]), duration]
    else:
        count = {"move": 6, "hit": 2, "break": 4}[name]
        edges = [duration * index / count for index in range(count + 1)]
    return list(zip(edges, edges[1:]))


def capture(pico, sprites):
    size, cell = CROWD_ATLAS_SIZE, CROWD_CELL_SIZE
    columns = size // cell
    atlas = pico.SDL_CreateTexture(pico.renderer, pico.SDL_PIXELFORMAT_RGBA32, pico.SDL_TEXTUREACCESS_TARGET,
                                   size, size)
    if not atlas:
        raise RuntimeError("군집 아틀라스 렌더 타깃 생성 실패")
    profiles, index = {}, 0
    pixels = (ct.c_ubyte * (size * size * 4))()
    try:
        with render_target(pico, atlas):
            pico.SDL_SetRenderDrawColor(pico.renderer, 0, 0, 0, 0)
            pico.SDL_RenderClear(pico.renderer)
            for kind, sprite in sprites.items():
                resource = sprite.resource
                pixel_scale = resource.data["pixel_scale"]
                pivot_x, pivot_y = resource.data["pivot_top_left"]
                motions = profiles[kind] = {}
                names = dict.fromkeys(("move", "attack", "hit", sprite.break_motion,
                                       *(spec["motion"] for spec in sprite.attack_motions.values())))
                for name in names:
                    intervals = pose_intervals(sprite, name)
                    directions = {}
                    motions[name] = {"starts": [start for start, _ in intervals], "directions": directions}
                    for bank, direction in enumerate(PART_DIRECTIONS):
                        clip = resource.get(name, str(bank))["data"]["clip"]
                        rows = directions[direction] = []
                        for start, end in intervals:
                            if index >= columns ** 2 - 1:
                                raise ValueError("선택한 적 포즈가 고정 시트 용량을 넘는다.")
                            seconds = (start + end) / 2
                            left, top, width, height = frame_state(clip, clip, seconds)["bounds"]
                            ratio = min(1, (cell - 2) / max(width, height))
                            x, y = (index % columns) * cell + 1, (index // columns) * cell + 1
                            destination = resource.draw(sprite.part_clip(name, direction), seconds,
                                                        x + (pivot_x - left) * ratio, y + (pivot_y - top) * ratio,
                                                        scale=ratio / pixel_scale, sample_shadow=False)
                            rows.append([destination.x, destination.y, destination.w, destination.h,
                                         (left - pivot_x) * pixel_scale, (top - pivot_y) * pixel_scale,
                                         width * pixel_scale, height * pixel_scale])
                            index += 1
                resource.release_pages()
            if pico.SDL_RenderReadPixels(pico.renderer, None, pico.SDL_PIXELFORMAT_RGBA32, pixels, size * 4):
                raise RuntimeError("군집 아틀라스 픽셀 읽기 실패")
    finally:
        pico.SDL_DestroyTexture(atlas)
    left, top, width, height = CROWD_SHADOW_RECT
    for y in range(height):
        for x in range(width):
            distance_sq = ((x + .5) * 2 / width - 1) ** 2 + ((y + .5) * 2 / height - 1) ** 2
            pixels[4 * ((top + y) * size + left + x) + 3] = round(255 * max(0, 1 - distance_sq) ** 1.5)
    return {"version": 1, "size": size, "profiles": profiles}, pixels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("enemy_parts", type=Path)
    parser.add_argument("lighting", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with PicoCanvas(128, 128, "군집 포즈 아틀라스 출력") as canvas:
        if canvas.info.name != "opengl":
            raise RuntimeError("군집 포즈 출력에 OpenGL이 필요하다.")
        sprites = load_enemy_part_sprites(args.enemy_parts, canvas.pico, args.lighting,
                                         GameSettings(texture_quality="high", upscale_aa="off"), None,
                                         preload=False)
        try:
            if not sprites:
                raise ValueError("캡처할 적 파츠가 없다.")
            document, pixels = capture(canvas.pico, sprites)
        finally:
            for sprite in sprites.values():
                sprite.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".rgba.zlib").write_bytes(zlib.compress(pixels))
    args.output.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
