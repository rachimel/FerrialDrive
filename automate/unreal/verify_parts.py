"""분리 전후 형상·가동·그림자·재합성과 원본 보존을 확인한다."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automate/runtime/image/python"))
from PIL import Image, ImageChops


def maximum_difference(a, b):
    return [pair[1] for pair in ImageChops.difference(a, b).getextrema()]


def verify(directory, units, copies):
    data = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    report = json.loads(units.read_text(encoding="utf-8"))
    ids = [key for part in report["parts"].values() for key in part["parts"]]
    rows, failures = [], []
    if len(ids) != len(set(ids)) or len(ids) != report["count"]:
        failures.append("부품 중복·누락")
    for item in json.loads(copies.read_text(encoding="utf-8")):
        if hashlib.sha256(Path(item["source"]).read_bytes()).hexdigest() != item["sha256"]:
            failures.append("원본 변경: " + item["source"])
    for index, frame in enumerate(data["clips"][0]["frames"]):
        whole = Image.open(directory / f"color/FinalImage/{index:04d}.png").convert("RGBA")
        reference = Image.open(directory / data["reference_frames"][index]).convert("RGBA")
        reference_mask = Image.open(directory / data["reference_mask_frames"]["unsplit_reference"][index]).convert("RGBA")
        clear = Image.open(directory / f"shadow_reference/FinalImageshadow_receiver/{index:04d}.png").convert("RGBA")
        combined = Image.new("RGBA", whole.size)
        colors = Image.new("RGBA", whole.size)
        for part in data["clips"][0]["order"]:
            image = Image.open(directory / frame[part]).convert("RGBA")
            combined = Image.alpha_composite(combined, image)
            if part != "shadow":
                colors = Image.alpha_composite(colors, image)
        reconstructed = Image.alpha_composite(clear, combined)
        shadow = Image.open(directory / frame["shadow"]).convert("RGBA")
        bbox = shadow.getbbox()
        color_diff = maximum_difference(whole, reference)
        difference_pixels = sum(max(pixel) > 1 for pixel in ImageChops.difference(whole, reference).get_flattened_data())
        alpha_diff = ImageChops.difference(colors.getchannel("A"), reference_mask.getchannel("A")).getextrema()[1]
        composition_diff = maximum_difference(whole, reconstructed)
        rgb_zero = shadow.convert("RGB").getbbox() is None
        uncut = bool(bbox) and bbox[0] > 0 and bbox[1] > 0 and bbox[2] < whole.width and bbox[3] < whole.height
        row = {"frame": index, "unsplit_rgba_max_difference": color_diff,
               "unsplit_pixels_over_one": difference_pixels,
               "silhouette_max_difference": alpha_diff, "recomposition_max_difference": composition_diff,
               "shadow_rgb_zero": rgb_zero, "shadow_not_clipped": uncut, "shadow_bbox": bbox}
        rows.append(row)
        if max(color_diff) > 1 or alpha_diff != 0 or max(composition_diff) > 1 or not rgb_zero or not uncut:
            failures.append("이미지 정합 불일치: " + str(index))
        if index == 0:
            preview = Image.alpha_composite(Image.new("RGBA", combined.size, (225, 225, 225, 255)), combined)
            preview.save(directory / "assembly_preview.png")
            matte = Image.alpha_composite(Image.new("RGBA", combined.size, (255, 255, 255, 255)), shadow)
            matte.save(directory / "shadow_preview.png")
    hand_images = [Image.open(directory / f["left_hand"]).getchannel("A") for f in data["clips"][0]["frames"]]
    moving = len(hand_images) > 1 and ImageChops.difference(hand_images[0], hand_images[1]).getbbox() is not None
    if not moving:
        failures.append("손목 검증 동작이 분리 손에 전달되지 않음")
    return {"passed": not failures, "parts": len(ids), "units": list(report["parts"]), "bones": len(report["bones"]),
            "source_unchanged": not any(f.startswith("원본 변경") for f in failures),
            "hand_pose_transferred": moving, "frames": rows, "failures": failures, "gui_test": "user_owned"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", type=Path, required=True)
    parser.add_argument("--units", type=Path, required=True)
    parser.add_argument("--copies", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = verify(args.render, args.units, args.copies)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(not report["passed"])


if __name__ == "__main__":
    main()
