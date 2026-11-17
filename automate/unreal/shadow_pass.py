"""중성 바닥의 그림자 유무 렌더를 검은 RGBA 그림자로 변환한다."""
import json
from pathlib import Path
import sys


def image_library():
    try:
        from PIL import Image
    except ModuleNotFoundError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "automate/runtime/image/python"))
        from PIL import Image
    return Image


def extract_shadow(shadowed, clear):
    Image = image_library()
    from PIL import ImageChops
    if shadowed.mode != "RGBA" or clear.mode != "RGBA" or shadowed.size != clear.size:
        raise ValueError("그림자 기준 이미지의 RGBA·크기가 다르다.")
    if ImageChops.difference(shadowed.getchannel("A"), clear.getchannel("A")).getextrema()[1] > 1:
        raise ValueError("두 바닥 렌더의 가림·알파가 다르다.")
    coverage_mask = ImageChops.darker(shadowed.getchannel("A"), clear.getchannel("A")).point(
        [0] + [255] * 255)
    for image in (shadowed, clear):
        red, green, blue = image.split()[:3]
        low = ImageChops.darker(ImageChops.darker(red, green), blue)
        high = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        invalid = ImageChops.subtract(high, low).point([0] * 3 + [255] * 253)
        if ImageChops.multiply(invalid, coverage_mask).getbbox():
            raise ValueError("중성 바닥과 중성 조명이 필요하다.")
    # 평균이 8 미만일 가능성이 있는 영역만 확인한다. 동일한 두 입력도 검증한다.
    low_light = ImageChops.multiply(low.point([255] * 8 + [0] * 248), coverage_mask).getbbox()
    if low_light:
        for light, coverage in zip(clear.crop(low_light).get_flattened_data(),
                                   coverage_mask.crop(low_light).get_flattened_data()):
            if coverage and sum(light[:3]) < 24:
                raise ValueError("그림자 없는 기준 바닥이 너무 어둡다.")
    bounds = ImageChops.difference(shadowed.convert("RGB"), clear.convert("RGB")).getbbox()
    image = Image.new("RGBA", clear.size)
    if bounds is None:
        return image
    result = []
    for dark, light in zip(shadowed.crop(bounds).get_flattened_data(), clear.crop(bounds).get_flattened_data()):
        if abs(dark[3] - light[3]) > 1:
            raise ValueError("두 바닥 렌더의 가림·알파가 다르다.")
        coverage = min(dark[3], light[3])
        alpha = 0
        if coverage:
            if max(light[:3]) - min(light[:3]) > 2 or max(dark[:3]) - min(dark[:3]) > 2:
                raise ValueError("중성 바닥과 중성 조명이 필요하다.")
            base = sum(light[:3]) / 3
            if base < 8:
                raise ValueError("그림자 없는 기준 바닥이 너무 어둡다.")
            alpha = round(max(0, min(1, 1 - sum(dark[:3]) / (3 * base))) * coverage)
        result.append((0, 0, 0, alpha))
    cropped = Image.new("RGBA", (bounds[2] - bounds[0], bounds[3] - bounds[1]))
    cropped.putdata(result)
    image.paste(cropped, bounds[:2])
    return image


def finalize_shadow(output):
    Image = image_library()
    output = Path(output).resolve()
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(manifest_path)
    data = json.loads((output / "native_manifest.json").read_text(encoding="utf-8"))
    pending = data.pop("shadow_pending")
    part = pending["part_id"]
    if part in data["layers"]:
        raise ValueError("그림자 ID가 색상 파츠와 중복된다.")
    if len(data["clips"]) != 1 or len(pending["frames"]) != len(data["clips"][0]["frames"]):
        raise ValueError("그림자와 색상 프레임 수가 다르다.")
    images, rows = [], []
    for pair in pending["frames"]:
        paths = [(output / pair[key]).resolve() for key in ("shadowed", "clear")]
        if any(not p.is_relative_to(output) for p in paths):
            raise ValueError("렌더 묶음 밖의 그림자 입력")
        with Image.open(paths[0]) as dark, Image.open(paths[1]) as light:
            image = extract_shadow(dark, light)
            if list(image.size) != data["size"]:
                raise ValueError("그림자와 파츠의 크기가 다르다.")
            coverage = sum(1 for value in image.getchannel("A").get_flattened_data() if value)
            rows.append({"nonzero_pixels": coverage, "alpha_extrema": list(image.getchannel("A").getextrema())})
            images.append(image)
    if not any(row["nonzero_pixels"] for row in rows):
        raise ValueError("검출된 지면 그림자가 없다.")
    directory = output / "shadow"
    if directory.exists():
        raise FileExistsError(directory)
    directory.mkdir()
    clip = data["clips"][0]
    for i, image in enumerate(images):
        name = f"shadow/{i:04d}.png"
        image.save(output / name)
        clip["frames"][i][part] = name
    data["layers"][part] = {"name": "그림자", "anchor": "root", "kind": "shadow"}
    clip["order"] = [part, *clip["order"]]
    clip["order_overrides"] = {key: [part, *order] for key, order in clip.get("order_overrides", {}).items()}
    data["shadow_method"] = "neutral_receiver_display_space_ratio_v1"
    (output / "shadow_validation.json").write_text(json.dumps({"frames": rows, "rgb": [0, 0, 0], "source": pending}, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path
