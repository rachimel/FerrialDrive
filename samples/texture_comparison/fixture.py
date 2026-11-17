"""기본 도형의 이동·정확한 상수 벡터. 게임 에셋 없이 실제 제작 경로를 사용한다."""

import json
from pathlib import Path


def write_fixture(destination, *, energy_mask=False):
    import numpy as np
    from PIL import Image
    from ferrial_drive.rendering.motion_vectors import encode_vector
    scene = json.loads(Path(__file__).with_name("scene.json").read_text(encoding="utf-8"))
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    size, count = scene["size"], scene["frames"]
    yy, xx = np.mgrid[:size, :size] + 0.5
    for frame in range(count):
        phase = frame / (count - 1)
        cx, cy = [a+(b-a)*phase for a, b in zip(scene["start"], scene["end"])]
        coverage = np.clip(0.5-np.maximum(abs(xx-cx)-scene["half_size"][0], abs(yy-cy)-scene["half_size"][1]), 0, 1)
        rgba = np.zeros((size, size, 4), dtype=np.uint8)
        rgba[:, :, :3] = (100, 180, 215)
        rgba[abs(yy-cy) < 2, :3] = (235, 140, 60)
        rgba[:, :, 3] = np.rint(coverage*255).astype(np.uint8)
        Image.fromarray(rgba).save(destination / f"color_{frame:03}.png")
        if energy_mask:
            mask = np.zeros_like(rgba)
            mask[:, :, :3] = np.where((abs(xx-cx) < 3)[..., None], 255, 0)
            mask[:, :, 3] = rgba[:, :, 3]
            Image.fromarray(mask).save(destination / f"energy_{frame:03}.png")
    dx, dy = [(b-a)/(count-1) for a, b in zip(scene["start"], scene["end"])]
    pairs = []
    for frame in range(count-1):
        for name, x, y in (("forward", dx, dy), ("backward", -dx, -dy)):
            (destination / f"{name}_{frame:03}.rgba").write_bytes(encode_vector(x, y)*size*size)
        name = f"pair_{frame:03}.json"
        data = {"schema_version": 1, "size_pixels": [size, size], "duration_seconds": scene["duration_seconds"]/(count-1),
                "vector_encoding": "signed16_rgba_x64", "vector_units": "pixels_per_pair", "origin": "top_left",
                "image_a": f"color_{frame:03}.png", "image_b": f"color_{frame+1:03}.png",
                "forward_a_to_b": f"forward_{frame:03}.rgba", "backward_b_to_a": f"backward_{frame:03}.rgba"}
        (destination / name).write_text(json.dumps(data), encoding="utf-8")
        pairs.append(name)
    clip = {"schema_version": 1, "pairs": pairs}
    if energy_mask:
        clip["energy_frames"] = [f"energy_{frame:03}.png" for frame in range(count)]
    (destination / "clip.json").write_text(json.dumps(clip), encoding="utf-8")
    # 같은 클립 입력을 사용하는 별도 재생 상태의 GPU 캐시 공유를 확인한다.
    catalog = {"schema_version": 1, "clips": [{"name": f"sample_{index}/s", "path": "clip.json",
                "pivot_top_left": [size/2, size/2], "pixel_scale": 2, "loop": True} for index in range(2)]}
    path = destination / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return path
