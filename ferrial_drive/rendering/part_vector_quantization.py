"""기존 파츠 아틀라스의 모션 벡터를 RG8로 변환한다."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import zlib

from .texture_codecs import unpack_payload


def quantize_page(pixels, width, height, rectangles):
    import numpy as np

    source = np.frombuffer(pixels, np.uint8).reshape(height, width, 4)
    target = np.full((height, width, 2), 128, np.uint8)
    steps = []
    maximum_error = 0.0
    for x, y, w, h in rectangles:
        if min(x, y) < 0 or min(w, h) < 1 or x + w > width or y + h > height:
            raise ValueError("벡터 프레임이 아틀라스 페이지 범위를 벗어났다.")
        tile = source[y:y+h, x:x+w].astype(np.int32)
        values = tile[..., ::2] * 256 + tile[..., 1::2] - 32768
        radius = np.abs(values).max(axis=(0, 1))
        # 텍스처 선형 필터링 뒤 같은 계수로 복원하며 코드 128은 정확한 영벡터다.
        step = radius / (127 * 64)
        codes = np.rint(values * 127 / np.maximum(1, radius)).astype(np.int16)
        target[y:y+h, x:x+w] = codes + 128
        steps.append(step.tolist())
        maximum_error = max(maximum_error, float(np.abs(values / 64 - codes * step).max()))
    return target.tobytes(), steps, maximum_error


def relative_to(path, directory):
    return Path(os.path.relpath(path, directory)).as_posix()


def quantize_catalogs(sources, destination):
    """여러 품질이 참조하는 벡터 페이지는 한 번만 변환한다."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    vectors = {}
    qualities = set()
    stats = dict(vector_pages=0, before_bytes=0, after_bytes=0, maximum_error_vector_pixels=0.0)
    with TemporaryDirectory(prefix="part-vector-", dir=destination.parent) as temporary:
        stage = Path(temporary) / destination.name
        (stage / "vectors").mkdir(parents=True)
        for source in sources:
            source = Path(source).resolve()
            catalog = json.loads(source.read_text(encoding="utf-8"))
            quality = catalog.get("quality")
            if (catalog.get("type") != "part_motion_gpu" or catalog.get("version") != 1 or
                    quality not in {"low", "medium", "high"} or quality in qualities):
                raise ValueError("품질이 서로 다른 파츠 GPU 카탈로그 v1이 필요하다.")
            qualities.add(quality)
            output = stage / quality
            (output / "atlases").mkdir(parents=True)
            final = destination / quality
            manifests = {}
            for directions in catalog["motions"].values():
                for direction, relative in directions.items():
                    old = (source.parent / relative).resolve()
                    if old not in manifests:
                        name = f"atlases/{len(manifests):04d}.json"
                        manifests[old] = name
                        atlas = json.loads(old.read_text(encoding="utf-8"))
                        new_dir = (final / name).parent
                        page, = atlas["pages"]["vector"]
                        frames = atlas["frames"]["vector"]
                        rects = tuple(tuple(frame["rect"]) for frame in frames)
                        raw_path = (old.parent / page["file"]).resolve()
                        key = raw_path, page["sha256"], page["width"], page["height"], rects
                        if page["codec"] != "rgba_zlib" or any(frame["page"] != 0 for frame in frames):
                            raise ValueError("RGBA16 벡터 단일 페이지가 필요하다.")
                        if key not in vectors:
                            packed = raw_path.read_bytes()
                            if hashlib.sha256(packed).hexdigest() != page["sha256"]:
                                raise ValueError(f"벡터 페이지 해시 불일치: {raw_path}")
                            raw, _ = unpack_payload(page["codec"], packed, page["width"], page["height"])
                            pixels, steps, error = quantize_page(raw, page["width"], page["height"], rects)
                            packed = zlib.compress(pixels)
                            file = Path("vectors") / f"{len(vectors):04d}.bin"
                            (stage / file).write_bytes(packed)
                            vectors[key] = file, hashlib.sha256(packed).hexdigest(), steps
                            stats["vector_pages"] += 1
                            stats["before_bytes"] += len(raw)
                            stats["after_bytes"] += len(pixels)
                            stats["maximum_error_vector_pixels"] = max(stats["maximum_error_vector_pixels"], error)
                            del raw, pixels, packed
                        file, digest, steps = vectors[key]
                        page.update(file=relative_to(destination / file, new_dir), codec="rg8_zlib", sha256=digest)
                        for frame, step in zip(frames, steps, strict=True):
                            frame["flow_step"] = step
                        for kind, pages in atlas["pages"].items():
                            if kind != "vector":
                                for entry in pages:
                                    entry["file"] = relative_to(old.parent / entry["file"], new_dir)
                        (output / name).write_text(json.dumps(atlas, ensure_ascii=False, separators=(",", ":")),
                                                   encoding="utf-8")
                    directions[direction] = manifests[old]
            for key in ("shadow_sources", "members"):
                if key in catalog:
                    catalog[key] = {motion: relative_to(source.parent / rel, final)
                                    for motion, rel in catalog[key].items()}
            if "source" in catalog:
                catalog["source"] = str((source.parent / catalog["source"]).resolve())
            else:
                catalog["source"] = relative_to(source, final)
                catalog["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            catalog.pop("statistics", None)
            (output / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        if not qualities:
            raise ValueError("변환할 파츠 카탈로그가 필요하다.")
        stage.rename(destination)
    return stats
