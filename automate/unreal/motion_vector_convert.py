"""Blender의 EXR 디코더로 Unreal 벡터를 읽어 Pico2D 보간 입력으로 변환한다."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

import bpy
import numpy as np


def read_pixels(path):
    image = bpy.data.images.load(str(path.resolve()), check_existing=False)
    try:
        image.colorspace_settings.name = "Non-Color"
        width, height = image.size
        values = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(values)
        return values.reshape(height, width, 4)[::-1].copy()
    finally:
        bpy.data.images.remove(image)


def write_png(path, pixels):
    pixels = np.clip(np.rint(pixels * 255), 0, 255).astype(np.uint8)
    height, width, _ = pixels.shape
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xffffffff)
    scanlines = b"".join(b"\0" + row.tobytes() for row in pixels)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))


def sample(pixels, flow):
    height, width, _ = pixels.shape
    yy, xx = np.mgrid[:height, :width]
    x, y = xx + flow[:, :, 0], yy + flow[:, :, 1]
    valid = (x >= 0) & (x <= width - 1) & (y >= 0) & (y <= height - 1)
    x, y = np.clip(x, 0, width - 1), np.clip(y, 0, height - 1)
    left, top = x.astype(int), y.astype(int)
    right, bottom = np.minimum(left + 1, width - 1), np.minimum(top + 1, height - 1)
    fx, fy = (x - left)[..., None], (y - top)[..., None]
    result = (pixels[top, left] * (1 - fx) * (1 - fy) + pixels[top, right] * fx * (1 - fy)
              + pixels[bottom, left] * (1 - fx) * fy + pixels[bottom, right] * fx * fy)
    result[~valid] = 0
    return result


def premultiply(pixels):
    result = pixels.copy()
    result[:, :, :3] *= result[:, :, 3:4]
    return result


def decode(raw, convention, width, height):
    fields = raw[:, :, convention["channels"]] - 0.5
    return fields * np.array([width, height]) * np.array(convention["signs"]) * convention["scale"]


def calibrate(raw, colors, only=None):
    """유한한 채널·축·배율 후보를 측정한다. 광학 흐름을 추정하거나 대체하지 않는다."""
    height, width, _ = colors[0].shape
    rows = []
    indices = list(range(1, len(colors), 2))
    for channels in ([0, 1], [1, 0]):
        for sx in (-1, 1):
            for sy in (-1, 1):
                for scale in (0.25, 0.5, 1, 2, 4):
                    convention = {"channels": channels, "signs": [sx, sy], "scale": scale}
                    if only is not None and any(convention[key] != only.get(key) for key in convention):
                        continue
                    errors = []
                    for index in indices:
                        flow = decode(raw[index], convention, width, height)
                        mask = (colors[index][:, :, 3] > 0.9) & (np.linalg.norm(flow, axis=2) > 0.25)
                        if np.count_nonzero(mask) < 10:
                            continue
                        previous = sample(premultiply(colors[index - 1]), flow)
                        difference = np.abs(previous - premultiply(colors[index])).mean(axis=2)
                        errors.append(float(difference[mask].mean()))
                    if errors:
                        rows.append({**convention, "error": float(np.mean(errors))})
    if not rows:
        if only is not None:
            distances = [np.linalg.norm(decode(raw[i], only, width, height), axis=2)[colors[i][:, :, 3] > 0.9]
                         for i in range(1, len(colors))]
            maximum = max((float(values.max()) for values in distances if values.size), default=float('inf'))
            delta = max(float(np.abs(premultiply(a) - premultiply(b)).mean())
                        for a, b in zip(colors, colors[1:]))
            if maximum <= 0.25 and delta <= 0.005:
                row = {**only, "error": None, "calibration": "verified_decoder_subpixel_motion",
                       "max_opaque_displacement_px": maximum, "max_frame_mean_difference": delta}
                return row, [row]
        raise RuntimeError("움직이는 표면의 유효한 Unreal 벡터가 없다.")
    rows.sort(key=lambda row: row["error"])
    return rows[0], rows


def pad_vectors(flow, mask, radius):
    result, known = flow.copy(), mask.copy()
    result[~known] = 0
    for _ in range(radius):
        previous = known.copy()
        if previous.all():
            break
        for axis, shift in ((0, -1), (0, 1), (1, -1), (1, 1)):
            neighbor = np.roll(previous, shift, axis=axis)
            if axis == 0:
                neighbor[0 if shift == 1 else -1, :] = False
            else:
                neighbor[:, 0 if shift == 1 else -1] = False
            take = ~known & neighbor
            result[take] = np.roll(flow, shift, axis=axis)[take]
            known[take] = True
        flow = result.copy()
    return result


def encode(flow):
    values = np.rint(flow * 64).astype(np.int64) + 32768
    if np.any(values < 0) or np.any(values > 65535):
        raise ValueError("픽셀 변위가 보간 입력의 16비트 범위를 초과했다.")
    packed = np.stack((values[:, :, 0] // 256, values[:, :, 0] % 256,
                       values[:, :, 1] // 256, values[:, :, 1] % 256), axis=2)
    return packed.astype(np.uint8).tobytes()


def find_images(directory, token, suffix):
    folders = [path for path in directory.iterdir() if path.is_dir() and token == path.name]
    if len(folders) != 1:
        raise ValueError(f"출력 패스 경로가 모호하다: {token}; {[p.name for p in directory.iterdir()]}")
    return sorted(folders[0].glob("*" + suffix))


def convert(args):
    source, output = args.source.resolve(), args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    provenance = json.loads((source / "provenance.json").read_text(encoding="utf-8"))
    files = {name: find_images(source / name, "FinalImageunsplit_reference", ".png")
             for name in ("forward", "reverse", "reference")}
    vector_files = {name: find_images(source / name, "FinalImageMotionVectors", ".exr")
                    for name in ("forward", "reverse")}
    colors = {key: [read_pixels(path) for path in value] for key, value in files.items()}
    raw = {key: [read_pixels(path) for path in value] for key, value in vector_files.items()}
    count = len(colors["forward"])
    if count < 2 or len(colors["reverse"]) != count or any(len(value) != count for value in raw.values()):
        raise ValueError("정방향·역방향 이미지와 벡터 수가 다르다.")
    reverse_errors = [float(np.abs(premultiply(a) - premultiply(b)).mean())
                      for a, b in zip(colors["forward"], reversed(colors["reverse"]))]
    if max(reverse_errors) > 0.01:
        raise ValueError("정/역방향 렌더의 시각이 일치하지 않는다: " + str(reverse_errors))
    selected = json.loads(args.decoder.read_text(encoding="utf-8")) if args.decoder else None
    convention, candidates = calibrate(raw["forward"], colors["forward"], only=selected)
    if args.decoder:
        selected = json.loads(args.decoder.read_text(encoding="utf-8"))
        convention = next((row for row in candidates if all(row[key] == selected.get(key)
                              for key in ("channels", "signs", "scale"))), None)
        if convention is None:
            raise ValueError("지정한 벡터 규약을 현재 움직이는 표면에서 측정할 수 없다.")
    height, width, _ = colors["forward"][0].shape
    mask = np.logical_or.reduce([image[:, :, 3] > 0.01 for image in colors["reference"]])
    yy, xx = np.nonzero(mask)
    if not len(xx):
        raise ValueError("색상 패스에 보이는 표면이 없다.")
    size = min(width, height, max(xx.max() - xx.min() + 1, yy.max() - yy.min() + 1) + 32)
    left = int(np.clip((xx.min() + xx.max() + 1 - size) // 2, 0, width - size))
    top = int(np.clip((yy.min() + yy.max() + 1 - size) // 2, 0, height - size))
    if args.crop:
        left, top, size = args.crop
        if left < 0 or top < 0 or size <= 0 or left + size > width or top + size > height:
            raise ValueError("공통 크롭이 원본 캔버스 범위를 벗어났다.")
        if xx.min() < left or xx.max() >= left + size or yy.min() < top or yy.max() >= top + size:
            raise ValueError("공통 크롭이 동작 실루엣을 자른다.")
    crop = np.s_[top:top + size, left:left + size]
    energy = []
    energy_alpha_maximum = 0
    if provenance["request"].get("energy_map"):
        energy_source = Path(getattr(args, "energy_source", None) or source).resolve()
        energy_provenance = json.loads((energy_source / "provenance.json").read_text(encoding="utf-8"))
        for field in ("animation", "size", "source_fps", "duration_seconds", "energy_map"):
            if energy_provenance["request"].get(field) != provenance["request"].get(field):
                raise ValueError("대체 Energy Mask의 네이티브 동작·카메라 입력이 다르다: " + field)
        energy_files = find_images(energy_source / "energy", "FinalImageunsplit_reference", ".png")
        if len(energy_files) != count:
            raise ValueError("Energy Mask와 원본 색상의 끝점 포함 프레임 수가 다르다.")
        for path, color in zip(energy_files, colors["forward"]):
            image = read_pixels(path)
            if image.shape != color.shape or np.max(np.abs(image[:, :, 3] - color[:, :, 3])) > 1/255 + 1e-6:
                raise ValueError("Energy Mask의 크기·알파·시각이 색상과 일치하지 않는다.")
            energy_alpha_maximum = max(energy_alpha_maximum, float(np.max(np.abs(image[:, :, 3] - color[:, :, 3]))))
            image[:, :, 3] = color[:, :, 3]
            energy.append(image)
    output.mkdir(parents=True)
    for index, image in enumerate(colors["forward"]):
        write_png(output / f"color_{index:03d}.png", image[crop])
    for index, image in enumerate(energy):
        write_png(output / f"energy_{index:03d}.png", image[crop])
    reference = []
    for index, image in enumerate(colors["reference"]):
        name = f"reference_{index:03d}.png"
        write_png(output / name, image[crop])
        reference.append({"phase": index / (len(colors["reference"]) - 1), "image": name})
    pair_files = []
    magnitudes = []
    for index in range(count - 1):
        # 현재 표면에서 직전 표시 프레임으로 향하는 변위를 사용한다.
        backward = decode(raw["forward"][index + 1], convention, width, height)[crop]
        forward = decode(raw["reverse"][count - 1 - index], convention, width, height)[crop]
        for field, image_index, name in ((forward, index, "forward"), (backward, index + 1, "backward")):
            valid = colors["forward"][image_index][crop][:, :, 3] > 0.01
            magnitude = float(np.linalg.norm(field[valid], axis=1).max())
            magnitudes.append(magnitude)
            field = pad_vectors(field, valid, min(size, int(np.ceil(magnitude)) + 8))
            (output / f"{name}_{index:03d}.rgba").write_bytes(encode(field))
        name = f"pair_{index:03d}.json"
        data = {"schema_version": 1, "label": "Unreal " + provenance["request"]["animation"].rsplit("/", 1)[-1], "size_pixels": [int(size), int(size)],
                "duration_seconds": 1 / provenance["request"]["source_fps"], "origin": "top_left",
                "vector_units": "pixels_per_pair", "vector_encoding": "signed16_rgba_x64",
                "image_a": f"color_{index:03d}.png", "image_b": f"color_{index + 1:03d}.png",
                "forward_a_to_b": f"forward_{index:03d}.rgba", "backward_b_to_a": f"backward_{index:03d}.rgba"}
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        pair_files.append(name)
    report = {"schema_version": 1, "pairs": pair_files, "reference_frames": reference,
              "provenance": {"type": "unreal_native_motion_vectors", "source": str(source),
                             "native_capture_verified": True,
                             "animation": provenance["request"]["animation"], "engine": provenance["engine"],
                             "decoder": convention, "decoder_candidates": candidates,
                             "decoder_selection": "explicit_verified_convention" if args.decoder else "minimum_reprojection_error",
                             "reverse_color_mae": reverse_errors, "max_displacement_pixels": max(magnitudes),
                             "crop_top_left": [left, top], "size_pixels": int(size),
                             "source_animation_modified": False, "occlusion_reconstruction": False,
                             "native_provenance_sha256": hashlib.sha256((source / "provenance.json").read_bytes()).hexdigest()}}
    if energy:
        report["energy_frames"] = [f"energy_{i:03d}.png" for i in range(count)]
        report["provenance"].update(energy_source=str(energy_source), energy_alpha_max_difference=energy_alpha_maximum,
            energy_alpha_normalization="same-source color alpha after at most one 8-bit quantization step",
            energy_native_provenance_sha256=hashlib.sha256((energy_source / "provenance.json").read_bytes()).hexdigest())
    (output / "clip.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT " + json.dumps({"output": str(output / "clip.json"), "decoder": convention,
                                  "max_displacement_pixels": max(magnitudes), "size": int(size)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--crop", nargs=3, type=int, metavar=("LEFT", "TOP", "SIZE"))
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--energy-source", type=Path, help="같은 네이티브 동작의 별도 Energy Mask 출력")
    parser.add_argument("--batch", type=Path, help="같은 디코더를 사용하는 변환 요청 목록")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.batch:
        for row in json.loads(args.batch.read_text(encoding="utf-8")):
            output = Path(row["output"])
            if (output / "clip.json").is_file():
                print("완료 변환 재사용: " + str(output), flush=True)
                continue
            convert(argparse.Namespace(source=Path(row["source"]), output=output,
                                       crop=row.get("crop"), decoder=Path(row["decoder"]) if row.get("decoder") else None,
                                       energy_source=Path(row["energy_source"]) if row.get("energy_source") else None))
    else:
        if not args.source or not args.output:
            parser.error("--source와 --output 또는 --batch가 필요하다.")
        convert(args)


if __name__ == "__main__":
    main()
