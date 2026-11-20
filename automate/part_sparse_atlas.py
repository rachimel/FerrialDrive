"""기존 PBR 캡처에서 시각이 가변적인 키 포즈 아틀라스를 제작한다."""

import argparse
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import zlib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ferrial_drive.rendering.atlas_json import read_atlas_json
from ferrial_drive.rendering.motion_atlas import UniqueFrames, pack_items
from ferrial_drive.rendering.part_motion_catalog import PartMotionCatalog
from ferrial_drive.rendering.part_pbr import COAT_CHANNELS
from ferrial_drive.rendering.part_vector_quantization import relative_to
from ferrial_drive.rendering.texture_codecs import texture_payload_size, unpack_payload


POSE_FPS = 60
MAX_KEY_SPAN = 4
MAX_FLOW_PATH_PIXELS = 8
FRAME_FIELDS = {"color": "color", "energy": "energy", "depth": "depth", "material": "material", "coat": "coat"}


def select_keys(proxy, motion, count, fps, pixels_per_cm, error_pixels):
    """본 위치와 회전의 화면 오차가 큰 시각은 키로 남긴다."""
    track = proxy["clips"][motion]
    samples = np.rint(np.arange(count) * track["hz"] / fps).astype(int)
    poses = np.asarray(track["poses"], dtype=np.float64)[samples]
    bounds = np.asarray(proxy["bounds"], dtype=np.float64)
    radii = np.linalg.norm(np.abs(bounds).max(axis=1), axis=1) * pixels_per_cm
    positions = poses[..., :3] * pixels_per_cm
    rotations = poses[..., 3:]
    rotations = rotations / np.linalg.norm(rotations, axis=-1, keepdims=True)
    keys = [0]
    while keys[-1] < count - 1:
        first = keys[-1]
        for last in range(min(first + MAX_KEY_SPAN, count - 1), first, -1):
            if last == first + 1:
                break
            fraction = (np.arange(1, last - first) / (last - first))[:, None, None]
            between = slice(first + 1, last)
            expected = positions[first] + fraction * (positions[last] - positions[first])
            translation_error = np.linalg.norm(expected - positions[between], axis=-1)
            a, b = rotations[first], rotations[last]
            b = b * np.where(np.sum(a * b, axis=-1, keepdims=True) < 0, -1, 1)
            expected_rotation = a + fraction * (b - a)
            expected_rotation /= np.linalg.norm(expected_rotation, axis=-1, keepdims=True)
            dot = np.sum(expected_rotation * rotations[between], axis=-1)
            rotation_error = 2 * radii * np.sqrt(np.maximum(0, 1 - dot * dot))
            if np.all(translation_error + rotation_error <= error_pixels):
                break
        keys.append(last)
    return keys


def read_page(page, directory):
    path = (directory / page["file"]).resolve()
    packed = path.read_bytes()
    if sha256(packed).hexdigest() != page["sha256"]:
        raise ValueError(f"파츠 페이지 해시 불일치: {path}")
    width, height = page["width"], page["height"]
    pixels, bc7 = unpack_payload(page["codec"], packed, width, height)
    if bc7:
        return np.frombuffer(pixels, np.uint8).reshape((height + 3) // 4, (width + 3) // 4, 16)
    return np.frombuffer(pixels, np.uint8).reshape(height, width, -1)


class TilePage:
    def __init__(self, codec):
        self.codec = codec
        self.pool = UniqueFrames()
        self.items = []
        self.references = {}

    def retain(self, source, frame, index):
        if index in self.references:
            return self.references[index]
        x, y, width, height = frame["rect"]
        if self.codec == "bc7_zlib":
            # 기존 BC7의 한 블록을 RGBA 네 픽셀로 옮겨 배치한다.
            tile = source[y//4:(y+height+3)//4, x//4:(x+width+3)//4]
            rows, cols = tile.shape[:2]
            pixels = tile.reshape(rows, cols, 2, 2, 4).transpose(0, 2, 1, 3, 4)
            slot = self.pool.add(pixels.tobytes(), cols * 2, rows * 2)
            entry = (slot, (x % 4, y % 4, width, height), {})
            self.items.append(entry)
            new = len(self.items) - 1
        else:
            metadata = {"flow_step": frame["flow_step"]} if "flow_step" in frame else {}
            new = self.add(source[y:y+height, x:x+width], metadata)
        self.references[index] = new
        return new

    def add(self, pixels, metadata):
        height, width, channels = pixels.shape
        rgba = np.zeros((height, width, 4), np.uint8)
        rgba[..., :channels] = pixels
        slot = self.pool.add(rgba.tobytes(), width, height)
        self.items.append((slot, None, metadata))
        return len(self.items) - 1

    def write(self, directory, manifest, channels):
        bc7 = self.codec == "bc7_zlib"
        pages, positions = pack_items(self.pool.items, max_side=2048 if bc7 else 4096, padding=0)
        page, = pages
        width, height = page.width, page.height
        raw = np.frombuffer(page.pixels, np.uint8).reshape(height, width, 4)
        if bc7:
            raw = raw.reshape(height//2, 2, width//2, 2, 4).transpose(0, 2, 1, 3, 4)
            width, height = width * 2, height * 2
        else:
            raw = raw[..., :channels]
        payload = zlib.compress(raw.tobytes())
        digest = sha256(payload).hexdigest()
        target = directory / f"{self.codec}-{width}x{height}-{digest}.bin"
        if not target.is_file():
            target.write_bytes(payload)
        frames = []
        for slot, block, metadata in self.items:
            rect = positions[slot]["rect"]
            if block:
                dx, dy, w, h = block
                rect = [rect[0] * 2 + dx, rect[1] * 2 + dy, w, h]
            frames.append(dict(page=0, rect=rect, **metadata))
        spec = dict(file=relative_to(target, manifest.parent), codec=self.codec, sha256=digest, width=width, height=height)
        return spec, frames


def compose_flow(vectors, tiles):
    """한 파츠의 인접 RG8 변위를 따라 키 사이의 변위를 합성한다."""
    _, _, width, height = tiles[0]["rect"]
    gy, gx = np.mgrid[:height, :width].astype(np.float32)
    total = np.zeros((height, width, 2), dtype=np.float32)
    for tile in tiles:
        x, y, w, h = tile["rect"]
        if (width, height) != (w, h):
            raise ValueError("파츠 벡터 타일의 픽셀 단위가 프레임 사이에 달라졌다.")
        steps = np.asarray(tile["flow_step"], np.float32)
        field = (vectors[y:y+h, x:x+w].astype(np.float32) - 128) * steps
        px, py = np.clip(gx + total[..., 0], 0, width - 1), np.clip(gy + total[..., 1], 0, height - 1)
        x0, y0 = px.astype(np.intp), py.astype(np.intp)
        x1, y1 = np.minimum(x0 + 1, width - 1), np.minimum(y0 + 1, height - 1)
        fx, fy = (px - x0)[..., None], (py - y0)[..., None]
        top = field[y0, x0] + fx * (field[y0, x1] - field[y0, x0])
        bottom = field[y1, x0] + fx * (field[y1, x1] - field[y1, x0])
        total += top + fy * (bottom - top)
    steps = np.abs(total).max(axis=(0, 1)) / 127
    codes = 128 + np.rint(total / np.where(steps > 0, steps, 1))
    return codes.astype(np.uint8), {"flow_step": steps.tolist()}


def preserve_large_transforms(catalog, directions, keys):
    """본 검사에서 놓치는 검·가동부의 화면 이동도 키 선택에 반영한다."""
    if all(last == first + 1 for first, last in zip(keys, keys[1:])):
        return keys
    retained = set(keys)
    for _, relative in directions:
        path = catalog.source.parent / relative
        atlas = read_atlas_json(path)
        rows = atlas["pages"]["vector"]
        if len(rows) != 1 or rows[0]["codec"] != "rg8_zlib":
            raise ValueError("단일 RG8 벡터 페이지가 필요하다.")
        vectors = read_page(rows[0], path.parent)
        frames = atlas["frames"]["vector"]
        distance_cache = {}

        def distance(index, crop):
            key = index, crop
            if key not in distance_cache:
                tile = frames[index]
                x, y, width, height = tile["rect"]
                scale = np.asarray(tile["flow_step"], np.float32) * np.asarray(crop) / (width, height)
                codes = vectors[y:y+height, x:x+width].astype(np.float32) - 128
                distance_cache[key] = np.percentile(np.linalg.norm(codes * scale, axis=-1), 90)
            return distance_cache[key]

        parts = tuple(atlas["clip"]["parts"].values())
        for first, last in zip(keys, keys[1:]):
            if last == first + 1:
                continue
            lengths = []
            for part in parts:
                crop = tuple(part["crop"][2:])
                lengths.append([max(distance(part["frames"][i]["forward"], crop),
                                    distance(part["frames"][i + 1]["backward"], crop))
                                for i in range(first, last)])
            path_lengths = np.asarray(lengths).T
            traveled = np.zeros(len(parts))
            for index, step in enumerate(path_lengths, first):
                if index in retained:
                    traveled.fill(0)
                traveled += step
                if (traveled > MAX_FLOW_PATH_PIXELS).any():
                    retained.add(index)
                    traveled = step.copy()
    return sorted(retained)


def sparsify_direction(atlas, source, target, coat_target, keys, page_root, sizes):
    clip = atlas["clip"]
    if "keyframe_seconds" in clip:
        raise ValueError("기존 캡처 표본을 가진 아틀라스가 필요하다.")
    tables = atlas["frames"]
    pages = {kind: rows[0] for kind, rows in atlas["pages"].items()}
    if pages["vector"]["codec"] != "rg8_zlib" or any(len(rows) != 1 for rows in atlas["pages"].values()):
        raise ValueError("단일 페이지의 RG8 PBR 벡터가 필요하다.")
    rasters = {kind: read_page(page, source.parent) for kind, page in pages.items()}
    packed = {kind: TilePage(page["codec"]) for kind, page in pages.items()}

    def retain(kind, index):
        return packed[kind].retain(rasters[kind], tables[kind][index], index)

    def flow(indices):
        if len(indices) == 1:
            return retain("vector", indices[0])
        return packed["vector"].add(*compose_flow(rasters["vector"], [tables["vector"][i] for i in indices]))

    for part in clip["parts"].values():
        frames = part["frames"]
        selected = []
        for index, key in enumerate(keys):
            frame = dict(frames[key])
            for field, kind in FRAME_FIELDS.items():
                if field in frame:
                    frame[field] = retain(kind, frame[field])
            next_key = keys[index + 1] if index + 1 < len(keys) else key + 1
            previous_key = keys[index - 1] if index else key - 1
            frame["forward"] = flow([frames[i]["forward"] for i in range(key, next_key)])
            frame["backward"] = flow([frames[i]["backward"] for i in range(key, previous_key, -1)])
            selected.append(frame)
        part["frames"] = selected

    clip["keyframe_seconds"] = [key / clip["fps"] for key in keys[:-1]] + [clip["duration_seconds"]]
    for kind, tile_page in packed.items():
        manifest = coat_target if kind == "coat" else target
        folder = page_root / "coat" / "pages" if kind == "coat" else page_root / "pages"
        spec, frames = tile_page.write(folder, manifest, rasters[kind].shape[-1])
        atlas["pages"][kind], tables[kind] = [spec], frames
        for accounting, row, path in ((sizes[0], pages[kind], source), (sizes[1], spec, manifest)):
            accounting[(path.parent / row["file"]).resolve(), row["sha256"]] = texture_payload_size(
                row["codec"], row["width"], row["height"])

    if coat_target:
        coat = {"page": atlas["pages"].pop("coat")[0], "frames": tables.pop("coat"),
                "parts": {name: [frame.pop("coat") for frame in part["frames"]]
                          for name, part in clip["parts"].items()}}
        write_json(coat_target, coat)
    write_json(target, atlas)


def write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def build_sparse_atlas(source, destination, *, motion_names=None, error_pixels=1.5):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    catalog = PartMotionCatalog(source)
    if catalog.paged or not catalog.pbr or not isfinite(error_pixels) or error_pixels <= 0:
        raise ValueError("방향별 PBR 아틀라스와 양수 화면 오차가 필요하다.")
    root = catalog.data
    source_motions = root["motions"]
    if motion_names and not set(motion_names) <= source_motions.keys():
        raise ValueError("원본에 없는 모션을 지정했다.")
    groups = {}
    for motion, directions in source_motions.items():
        groups.setdefault(tuple(sorted(directions.items())), []).append(motion)
    scale = root["size"][0] / root["surface_camera"]["width_cm"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    motions, coat_members, statistics = {}, {}, {}
    sizes = {}, {}
    with TemporaryDirectory(prefix="part-sparse-", dir=destination.parent) as temporary:
        stage = Path(temporary).resolve() / destination.name
        (stage / "pages").mkdir(parents=True)
        if catalog.coat_members:
            (stage / "coat/pages").mkdir(parents=True)
        for directions, aliases in groups.items():
            if motion_names and not set(aliases).intersection(motion_names):
                continue
            motion = aliases[0]
            reference = read_atlas_json(source.parent / directions[0][1])["clip"]
            count = len(reference["anchors"])
            keys = select_keys(root["shadow_proxy"], motion, count, reference["fps"], scale, error_pixels)
            keys = preserve_large_transforms(catalog, directions, keys)
            result = {}
            for direction_index, (direction, relative) in enumerate(directions):
                path = source.parent / relative
                atlas = catalog._read_direction(relative, path)
                if len(atlas["clip"]["anchors"]) != count or atlas["clip"]["fps"] != reference["fps"]:
                    raise ValueError(f"방향마다 원본 표본이 다르다: {motion}/{direction}")
                target = stage / "atlases" / f"{len(statistics):03d}-{direction_index}.json"
                coat_target = stage / "coat" / "directions" / target.name if catalog.coat_members else None
                sparsify_direction(atlas, path, target, coat_target, keys, stage, sizes)
                name = result[direction] = target.relative_to(stage).as_posix()
                if coat_target:
                    coat_members[name] = coat_target.relative_to(stage / "coat").as_posix()
            for alias in aliases:
                motions[alias] = result
            statistics[motion] = {"source_frames": count, "keys": keys, "directions": len(result)}
        root["motions"] = motions
        root["shared_pose_fps"] = POSE_FPS
        root["shadow_proxy"]["clips"] = {key: root["shadow_proxy"]["clips"][key] for key in motions}
        for field in ("part_spaces", "direction_correspondence_by_motion"):
            if field in root:
                root[field] = {key: row for key, row in root[field].items() if key in motions}
        for field in ("statistics", "source", "members", "shadow_sources"):
            root.pop(field, None)
        if coat_members:
            root["coat_index"] = "coat/index.json"
            write_json(stage / root["coat_index"], {"channels": COAT_CHANNELS, "members": coat_members})
        report = {"source_sha256": sha256(source.read_bytes()).hexdigest(), "error_pixels": error_pixels,
                  "source_texture_bytes": sum(sizes[0].values()), "sparse_texture_bytes": sum(sizes[1].values()),
                  "motions": statistics}
        write_json(stage / "catalog.json", root)
        write_json(stage / "statistics.json", report)
        stage.rename(destination)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--motion", action="append", help="대조할 모션 이름. 생략하면 전체를 변환한다.")
    parser.add_argument("--error-pixels", type=float, default=1.5)
    args = parser.parse_args()
    print(json.dumps(build_sparse_atlas(args.catalog, args.output, motion_names=args.motion,
                                        error_pixels=args.error_pixels)))


if __name__ == "__main__":
    main()
