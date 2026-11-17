"""게임과 독립된 사각형·이동 도형으로 런타임 카탈로그 입력을 만든다."""

import json
import shutil
from pathlib import Path


def write_runtime_fixture(directory):
    from PIL import Image
    from samples.texture_comparison.fixture import write_fixture
    from Tools.asset_loader.unreal_import import import_render
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError("새 시연 폴더가 필요하다.")
    directory.mkdir(parents=True)
    motion = write_fixture(directory / "input/motion", energy_mask=True)
    source = directory / "input/source"
    source.mkdir()
    catalog_data = json.loads(motion.read_text(encoding="utf-8"))
    for row in catalog_data["clips"]:
        row["pixel_scale"] = 1
    motion.write_text(json.dumps(catalog_data), encoding="utf-8")
    clip_data = json.loads((motion.parent / "clip.json").read_text(encoding="utf-8"))
    frames, masks = [], []
    for index, pair_name in enumerate(clip_data["pairs"]):
        pair = json.loads((motion.parent / pair_name).read_text(encoding="utf-8"))
        image_path = motion.parent / pair["image_a"]
        shutil.copyfile(image_path, source / f"body_{index}.png")
        shutil.copyfile(motion.parent / clip_data["energy_frames"][index], source / f"energy_{index}.png")
        with Image.open(image_path) as image:
            size = image.size
            shadow = Image.new("RGBA", size, (0, 0, 0, 0))
            shadow.putalpha(image.getchannel("A"))
            shadow.save(source / f"shadow_{index}.png")
        frames.append({"body": f"body_{index}.png", "shadow": f"shadow_{index}.png"})
        masks.append({"body": f"energy_{index}.png"})
    clips = [{"name": row["name"], "fps": 1 / pair["duration_seconds"],
              "frames": frames, "energy_frames": masks} for row in catalog_data["clips"]]
    manifest = source / "manifest.json"
    manifest.write_text(json.dumps({"version": 1, "type": "unreal_prerender", "asset_id": "public_shape",
        "size": list(size), "pivot": [size[0]/2, size[1]/2],
        "layers": {"shadow": {}, "body": {}}, "clips": clips}), encoding="utf-8")
    import_render(manifest, source / "packed")
    catalog = source / "catalog.json"
    catalog.write_text(json.dumps({"version": 1, "assets": [{"id": "shape", "kind": "mech",
        "source": "packed/mech.json"}]}), encoding="utf-8")
    request = {"output": str(directory / "runtime/assets"), "interpolation_output": str(directory / "runtime/motion"),
               "aliases": {"sample_0": "idle_loop", "sample_1": "combo_01"}, "attack_motions": ["sample_1"],
               "sources": [{"asset_catalog": str(catalog), "interpolation_catalog": str(motion)}]}
    (directory / "request.json").write_text(json.dumps(request, indent=2), encoding="utf-8")
    return request
