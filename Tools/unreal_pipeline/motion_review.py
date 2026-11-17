"""Unreal 파츠 출력을 고정 피봇·배율의 동작 검토 이미지로 묶는다."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    from PIL import Image, ImageChops, ImageDraw, ImageFont
except ModuleNotFoundError as error:
    if error.name != "PIL":
        raise
    sys.path.insert(0, str(ROOT / "automate/runtime/image/python"))
    from PIL import Image, ImageChops, ImageDraw, ImageFont


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8-sig"))


def compose(directory, comparison_exclude=()):
    """전체 프레임을 재합성하고 원본 실루엣·에너지 소유 영역을 비교한다."""
    manifest = read(directory / "manifest.json")
    clip = manifest["clips"][0]
    output = directory / "composite"
    output.mkdir(exist_ok=True)
    frames, checks = [], []
    for index, frame in enumerate(clip["frames"]):
        image = Image.new("RGBA", manifest["size"])
        comparison = Image.new("RGBA", manifest["size"])
        mask_error = 0
        for part in clip["order"]:
            layer = Image.open(directory / frame[part]).convert("RGBA")
            image = Image.alpha_composite(image, layer)
            if part not in comparison_exclude:
                comparison = Image.alpha_composite(comparison, layer)
            energy_rows = clip.get("energy_frames", [])
            relative = energy_rows[index].get(part) if energy_rows else None
            energy = directory / relative if relative else None
            if energy is None and not energy_rows and (directory / "energy").exists() and part not in comparison_exclude:
                energy = directory / "energy" / frame[part]
            if energy is not None and not energy.is_file():
                raise FileNotFoundError(energy)
            if energy is not None:
                mask_error = max(mask_error, ImageChops.difference(layer.getchannel("A"),
                    Image.open(energy).getchannel("A")).getextrema()[1])
        reference = Image.open(directory / manifest["reference_mask_frames"]["unsplit_reference"][index]).convert("RGBA")
        difference = ImageChops.difference(comparison, reference)
        alpha_error = difference.getchannel("A").getextrema()[1]
        rgb = difference.convert("RGB")
        histogram = ImageChops.lighter(ImageChops.lighter(rgb.getchannel("R"), rgb.getchannel("G")), rgb.getchannel("B")).histogram()
        bbox = image.getbbox()
        uncut = bool(bbox) and bbox[0] > 0 and bbox[1] > 0 and bbox[2] < image.width and bbox[3] < image.height
        checks.append({"frame": index, "alpha_max_difference": alpha_error,
                       "rgb_pixels_over_two": sum(histogram[3:]), "energy_alpha_max_difference": mask_error,
                       "rgb_max_difference": max(value[1] for value in rgb.getextrema()),
                       "bbox": bbox, "comparison_bbox": comparison.getbbox(), "not_clipped": uncut})
        image.save(output / f"{index:04d}.png")
        frames.append(image)
    return frames, checks


def create_follow(request):
    """시선 추종 후보의 모든 출력 프레임·방향을 같은 배율로 검토한다."""
    output = ROOT / request["output"]
    output.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(ROOT / request["font"]), 14)
    background = tuple(request.get("background", [28, 31, 38]))
    cell_size = tuple(request.get("cell_size", [350, 310]))
    crop_box = tuple(request.get("crop_box", [80, 130, 430, 410]))
    scale = request["game_scale"]
    primary, verification, frames_per_state = {}, {}, None
    for state, spec in request["states"].items():
        samples = read(spec["samples"])
        trajectory = read(spec["trajectory"]) if spec.get("trajectory") else None
        views, trail_views = {}, {}
        for direction, paths in spec["views"].items():
            frames, checks = [], []
            for path in paths:
                images, rows = compose(ROOT / path, comparison_exclude=("shadow",))
                frames.extend(images)
                checks.extend({"clip": path, **row} for row in rows)
            if len(frames) * 10 >= len(samples):
                raise ValueError("전체 출력 프레임에 대응하는 추종 표본이 필요하다.")
            if frames_per_state is not None and len(frames) != frames_per_state:
                raise ValueError("한 검토 묶음의 상태별 프레임 수가 다르다.")
            frames_per_state = len(frames)
            boxes = [row["comparison_bbox"] for row in checks if row["comparison_bbox"]]
            contact_box = (max(0, min(box[0] for box in boxes)-8),
                           max(0, min(box[1] for box in boxes)-8),
                           min(frames[0].width, max(box[2] for box in boxes)+8),
                           min(frames[0].height, max(box[3] for box in boxes)+8))
            tiles, trail_tiles = [], []
            sheet = Image.new("RGB", (180 * 12, 230 * ((len(frames) + 11) // 12)), background)
            for index, image in enumerate(frames):
                tile = Image.new("RGBA", cell_size, background + (255,))
                picture = image.crop(crop_box)
                picture.thumbnail((cell_size[0], cell_size[1] - 30))
                tile.alpha_composite(picture, ((cell_size[0] - picture.width)//2, 30))
                sample = samples[index * 10]
                label = f"{spec['label']} {direction} {index/12:.2f}s F{int(sample['lower_following'])}"
                ImageDraw.Draw(tile).text((5, 5), label, font=font, fill="white")
                tiles.append(tile.convert("RGB"))
                if trajectory:
                    overlay = Image.new("RGBA", image.size)
                    trace_draw = ImageDraw.Draw(overlay)
                    seconds = index / 12
                    begin, end = spec["trajectory_active_seconds"]
                    if begin <= seconds <= end:
                        start = max(round(begin * trajectory["sample_hz"]),
                                    round((seconds - .1) * trajectory["sample_hz"]))
                        stop = round(seconds * trajectory["sample_hz"])
                        trace = trajectory["samples"][start:stop+1]
                        segments = [[tuple(row["screen_top_left_px"][direction][key])
                                     for key in ("cutting_edge_root", "cutting_edge_tip")] for row in trace]
                        for a, b in zip(segments, segments[1:]):
                            trace_draw.polygon([a[0], a[1], b[1], b[0]], fill=(255, 157, 53, 55))
                        if segments:
                            trace_draw.line(segments[-1], fill=(255, 180, 75, 255), width=2)
                    marked = Image.alpha_composite(image, overlay).crop(crop_box)
                    marked.thumbnail((cell_size[0], cell_size[1] - 30))
                    trail_tile = Image.new("RGBA", cell_size, background + (255,))
                    trail_tile.alpha_composite(marked, ((cell_size[0]-marked.width)//2, 30))
                    ImageDraw.Draw(trail_tile).text((5, 5), f"검날 궤적 진단 {direction} {seconds:.2f}s",
                        font=font, fill=(255, 180, 75))
                    trail_tiles.append(trail_tile.convert("RGB"))
                small = Image.new("RGBA", (180, 230), background + (255,))
                image_crop = image.crop(contact_box)
                image_crop.thumbnail((176, 200))
                small.alpha_composite(image_crop, ((180 - image_crop.width) // 2, 27))
                ImageDraw.Draw(small).text((4, 4), f"{direction} {index/12:.2f}s", font=font, fill="white")
                sheet.paste(small.convert("RGB"), (index % 12 * 180, index // 12 * 230))
            sheet.save(output / f"frames_{state}_{direction}.png")
            views[direction] = tiles
            if trajectory:
                trail_views[direction] = trail_tiles
            verification[f"{state}/{direction}"] = checks
            if direction == request.get("primary_view", "se"):
                primary[state] = tiles
                game = []
                for index, image in enumerate(frames):
                    canvas = Image.new("RGBA", (360, 360), background + (255,))
                    resized = image.resize((round(image.width*scale), round(image.height*scale)), Image.Resampling.BICUBIC)
                    canvas.alpha_composite(resized, ((360-resized.width)//2, (360-resized.height)//2))
                    ImageDraw.Draw(canvas).text((6, 6), f"{spec['label']} {index/12:.2f}s", font=font, fill="white")
                    game.append(canvas.convert("RGB"))
                save_gif(output / f"game_{state}.gif", game, 12)
        combined = []
        for tiles in zip(*views.values()):
            canvas = Image.new("RGB", (cell_size[0] * len(tiles), cell_size[1]), background)
            for index, tile in enumerate(tiles):
                canvas.paste(tile, (index * cell_size[0], 0))
            combined.append(canvas)
        save_gif(output / f"{state}.gif", combined, 12)
        if trajectory:
            traced = []
            for tiles in zip(*trail_views.values()):
                canvas = Image.new("RGB", (cell_size[0]*len(tiles), cell_size[1]), background)
                for index, tile in enumerate(tiles):
                    canvas.paste(tile, (index*cell_size[0], 0))
                traced.append(canvas)
            save_gif(output / f"{state}_trajectory.gif", traced, 12)
    overview = []
    columns = min(4, len(primary))
    for tiles in zip(*primary.values()):
        canvas = Image.new("RGB", (cell_size[0]*columns,
            cell_size[1]*((len(tiles)+columns-1)//columns)), background)
        for index, tile in enumerate(tiles):
            canvas.paste(tile, (index % columns * cell_size[0], index // columns * cell_size[1]))
        overview.append(canvas)
    save_gif(output / "overview.gif", overview, 12)
    result = {"mode": "aim_follow", "frames_per_state": frames_per_state,
              "total_output_frames": sum(len(rows) for rows in verification.values()),
              "renders": verification,
              "all_silhouettes_equal": all(row["alpha_max_difference"] == 0 for rows in verification.values() for row in rows),
              "all_energy_alpha_equal": all(row["energy_alpha_max_difference"] == 0 for rows in verification.values() for row in rows),
              "all_frames_uncut": all(row["not_clipped"] for rows in verification.values() for row in rows),
              "game_scale": scale, "actual_game_window_checked": False}
    (output / "verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "renders"}, ensure_ascii=False))


def fixed_frame(image, size, anchor, pivot, scale):
    return image.transform(tuple(size), Image.Transform.AFFINE,
        (1 / scale, 0, pivot[0] - anchor[0] / scale, 0, 1 / scale, pivot[1] - anchor[1] / scale),
        resample=Image.Resampling.BICUBIC)


def save_gif(path, frames, fps, slow=False):
    # 모든 프레임이 같은 팔레트를 사용해 색 떨림을 줄인다.
    contact = Image.new("RGB", (frames[0].width * 8, frames[0].height * ((len(frames) + 7) // 8)))
    for index, frame in enumerate(frames):
        contact.paste(frame, (index % 8 * frame.width, index // 8 * frame.height))
    palette = contact.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    converted = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    durations = [250 if slow else round((index + 1) * 100 / fps) * 10 - round(index * 100 / fps) * 10
                 for index in range(len(frames))]
    converted[0].save(path, save_all=True, append_images=converted[1:], duration=durations,
                      loop=0, disposal=2, optimize=False)


def create(request):
    output = ROOT / request["output"]
    output.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(ROOT / request["font"]), 16)
    background = tuple(request.get("background", [28, 31, 38]))
    all_frames, traces, report = {}, {}, {}
    for direction, view in request["views"].items():
        frames, labels, sample_refs = [], [], []
        idle = [Image.open(ROOT / view["idle"] / f"{n:04d}.png").convert("RGBA")
                for n in range(request["idle_frames"])]
        frames.extend(idle)
        labels.extend(["Idle"] * len(idle))
        sample_refs.extend([None] * len(idle))
        ground_offsets = [0.0] * len(idle)
        travelled = 0.0
        for number, clip in enumerate(view["clips"], 1):
            images, checks = compose(ROOT / clip["directory"])
            report[f"{number:02d}_{direction}"] = checks
            caption = clip.get("label", f"{number}타")
            repeat = clip.get("repeat", 1)
            if type(repeat) is not int or not 1 <= repeat <= 8:
                raise ValueError("검토 반복 수는 1~8 정수다.")
            for _ in range(repeat):
                frames.extend(images)
                labels.extend([f"{caption} · {n + 1}/{len(images)}" for n in range(len(images))])
                sample_refs.extend([(number, n) for n in range(len(images))])
                distance = clip.get("ground_travel_cm", 0)
                ground_offsets.extend([travelled + distance * n / len(images) for n in range(len(images))])
                travelled += distance
            trace = read(clip["tracking"])
            traces[number] = trace
            # 확대 검토는 모든 타수의 모든 출력 프레임을 보존한다.
            size = request.get("contact_size", [300, 360])
            sheet = Image.new("RGB", (size[0] * 5, size[1] * ((len(images) + 4) // 5)), background)
            draw = ImageDraw.Draw(sheet)
            for n, image in enumerate(images):
                crop = image.crop(tuple(request["contact_crop"]))
                crop.thumbnail((size[0], size[1] - 24), Image.Resampling.LANCZOS)
                x, y = n % 5 * size[0], n // 5 * size[1]
                sheet.paste(crop, (x + (size[0] - crop.width) // 2, y), crop)
                draw.text((x + 6, y + size[1] - 23), f"{caption} {direction} F{n}", font=font, fill="white")
            sheet.save(output / f"{number:02d}_{direction}_contact.png")
        frames.extend(idle)
        labels.extend(["Idle 복귀"] * len(idle))
        sample_refs.extend([None] * len(idle))
        ground_offsets.extend([travelled] * len(idle))
        view_frames, trail_frames = [], []
        for image, label, sample_ref, distance in zip(frames, labels, sample_refs, ground_offsets):
            tile = Image.new("RGBA", request["canvas"], background + (255,))
            if request.get("ground_demo"):
                from automate.unreal.blade_tracking import project_to_screen
                camera = next(iter(traces.values()))["cameras"][direction]
                ground = ImageDraw.Draw(tile)
                def screen(point):
                    pixel = project_to_screen(point, camera)
                    return tuple(request["anchor"][i] + (pixel[i] - view["pivot_top_left_px"][i]) * request["scale"] for i in (0, 1))
                shift = distance % 100
                for x in range(-700, 701, 100):
                    ground.line([screen([x - shift, -550, -1]), screen([x - shift, 550, -1])], fill=(52, 59, 68, 255))
                for y in range(-500, 501, 100):
                    ground.line([screen([-750, y, -1]), screen([750, y, -1])], fill=(45, 52, 61, 255))
            tile.alpha_composite(fixed_frame(image, request["canvas"], request["anchor"],
                                            view["pivot_top_left_px"], request["scale"]))
            draw = ImageDraw.Draw(tile)
            draw.text((10, 8), view["label"] + " · " + label, font=font, fill="white")
            view_frames.append(tile.convert("RGB"))
            trail = tile.copy()
            if sample_ref:
                number, frame = sample_ref
                trace = traces[number]
                stride = round(trace["sample_hz"] / request["fps"])
                start = max(0, frame - 3) * stride
                samples = trace["samples"][start:frame * stride + 1:stride]
                segments = []
                for sample in samples:
                    points = sample["screen_top_left_px"][direction]
                    segments.append([tuple(request["anchor"][i] +
                        (points[key][i] - view["pivot_top_left_px"][i]) * request["scale"] for i in (0, 1))
                        for key in ("cutting_edge_root", "cutting_edge_tip")])
                overlay = Image.new("RGBA", trail.size)
                od = ImageDraw.Draw(overlay)
                for a, b in zip(segments, segments[1:]):
                    od.polygon([a[0], a[1], b[1], b[0]], fill=(255, 157, 53, 65))
                if segments:
                    od.line(segments[-1], fill=(255, 180, 75, 255), width=2)
                trail.alpha_composite(overlay)
            trail_frames.append(trail.convert("RGB"))
        all_frames[direction] = view_frames
        if direction == request["primary_view"]:
            save_gif(output / "combo.gif", view_frames, request["fps"])
            save_gif(output / "combo_slow.gif", view_frames, request["fps"], slow=True)
            save_gif(output / "combo_trail.gif", trail_frames, request["fps"])
    combined = []
    for tiles in zip(*all_frames.values()):
        image = Image.new("RGB", (tiles[0].width * len(tiles), tiles[0].height), background)
        for n, tile in enumerate(tiles):
            image.paste(tile, (n * tile.width, 0))
        combined.append(image)
    save_gif(output / "combo_review.gif", combined, request["fps"])
    result = {"frames_per_view": len(combined), "scale": request["scale"], "renders": report,
              "all_silhouettes_equal": all(row["alpha_max_difference"] == 0 for rows in report.values() for row in rows),
              "all_frames_uncut": all(row["not_clipped"] for rows in report.values() for row in rows),
              "all_energy_alpha_equal": all(row["energy_alpha_max_difference"] == 0 for rows in report.values() for row in rows)}
    (output / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "renders"}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    request = read(args.request)
    (create_follow if request.get("mode") == "aim_follow" else create)(request)
