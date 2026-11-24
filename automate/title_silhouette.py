"""현재 본편 몸체 glTF의 외곽과 주요 면 경계를 투명 타이틀 이미지로 출력한다."""

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ferrial_drive.rendering.runtime_mesh import GltfAsset


def main():
    root = Path(__file__).resolve().parents[1]
    config = root / "samples/sword_movement/movement_config.json"
    mesh_path = json.loads(config.read_text(encoding="utf-8"))["upper_lower"]["runtime_mesh"]
    catalog = (config.parent / mesh_path).resolve()
    body, = json.loads(catalog.read_text(encoding="utf-8"))["meshes"]["player"]
    asset = GltfAsset(catalog.parent / body)
    triangles = []
    for mesh in asset.data["meshes"]:
        for part in mesh["primitives"]:
            vertices = asset.array(part["attributes"]["POSITION"])
            triangles.append(vertices[asset.array(part["indices"]).reshape(-1, 3)])
    faces = np.concatenate(triangles)
    depth = faces @ [0.92, 0.12, 0.38]
    xy = np.stack((faces @ [-0.38, 0, 0.92], faces @ [0.11, -1, 0.045]), axis=-1)
    xy -= xy.min(axis=(0, 1))
    xy *= 1800 / xy.max()
    size = tuple((xy.max(axis=(0, 1)) + 9).astype(int))
    normals = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-9)
    tones = np.clip(130 + 64 * (normals @ [0.7, 0.65, 0.3]), 0, 255)
    plane = Image.new("L", size)
    draw = ImageDraw.Draw(plane)
    points = (xy + 4).astype(int)
    for i in depth.mean(axis=1).argsort():
        draw.polygon(points[i].ravel().tolist(), fill=int(tones[i]))
    mask = plane.point(lambda x: 255 if x else 0)
    outline = ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(5)), mask)
    edges = ImageChops.subtract(plane.filter(ImageFilter.MaxFilter(3)), plane.filter(ImageFilter.MinFilter(3)))
    alpha = ImageChops.lighter(outline, edges.point(lambda x: min(120, max(0, x - 30) * 2)))
    result = Image.new("RGBA", size, "white")
    result.putalpha(alpha)
    result.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    result.save(root / "data/runtime/images/ui/title_mech_outline.png")


if __name__ == "__main__":
    main()
