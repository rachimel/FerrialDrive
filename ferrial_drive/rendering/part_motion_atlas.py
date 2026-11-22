"""독립 파츠의 공통 아틀라스 제작과 시간·허리 기준점 선택. GPU에 의존하지 않는다."""

from bisect import bisect_right
import hashlib
import json
import os
from math import ceil, floor, isfinite
from pathlib import Path
import zlib

from .motion_atlas import UniqueFrames, pack_items, resize_color, resize_vectors

DEPTH_MAX = 16777215
COMPACT_DEPTH_ENCODING = "rg16_normalized_valid_blue"
ENERGY_CHANNEL_TOLERANCE = 2
MAX_PARTS = 13


def encode_depth(depth, minimum, span):
    """양수 깊이를 RGB24, 유효 영역을 A에 저장한다. 원본 float32 파일은 보존한다."""
    import numpy as np
    valid = np.isfinite(depth) & (depth > 0)
    values = np.where(valid, depth, minimum).astype(np.float64)
    if span <= 0 or not np.isfinite(values).all() or (values[valid] < minimum).any() or (values[valid] > minimum + span).any():
        raise ValueError("깊이 범위가 맞지 않는다.")
    encoded = np.rint((values - minimum) / span * DEPTH_MAX).astype(np.uint32)
    pixels = np.stack(((encoded >> 16) & 255, (encoded >> 8) & 255, encoded & 255, valid * 255), axis=-1).astype(np.uint8)
    return pixels.tobytes()


def decode_depth(pixels, width, height, minimum, span):
    import numpy as np
    raw = np.frombuffer(pixels, np.uint8).reshape(height, width, 4).astype(np.float64)
    encoded = raw[..., 0] * 65536 + raw[..., 1] * 256 + raw[..., 2]
    return np.where(raw[..., 3] > 0, minimum + encoded / DEPTH_MAX * span, np.inf)


def frame_phase(clip, elapsed_seconds, *, dense_anchors=False):
    if not isfinite(elapsed_seconds) or elapsed_seconds < 0:
        raise ValueError("동작 시간은 0 이상의 초다.")
    duration = clip["duration_seconds"]
    time = elapsed_seconds % duration if clip["loop"] else min(duration, elapsed_seconds)
    keys = clip.get("keyframe_seconds")
    if keys is not None and not dense_anchors:
        first = min(len(keys) - 2, bisect_right(keys, time) - 1)
        return first, (time - keys[first]) / (keys[first + 1] - keys[first])
    position = time * clip["fps"]
    first = min(len(clip["anchors"]) - 2, int(position))
    return first, min(1, max(0, position - first))


def frame_state(upper, lower, elapsed_seconds):
    """같은 위상의 두 방향을 허리에 맞춘다. 깊이는 카메라 축 차이만 보정한다."""
    if upper["fps"] != lower["fps"] or upper["duration_seconds"] != lower["duration_seconds"]:
        raise ValueError("같은 동작·표본 속도의 두 방향이 필요하다.")
    if upper.get("keyframe_seconds") != lower.get("keyframe_seconds"):
        raise ValueError("같은 시각의 키 포즈를 갖는 두 방향이 필요하다.")
    first, alpha = frame_phase(upper, elapsed_seconds)
    anchor_first, anchor_alpha = ((first, alpha) if "keyframe_seconds" not in upper
                                  else frame_phase(upper, elapsed_seconds, dense_anchors=True))

    def waist(clip):
        a, b = (row["waist"] for row in clip["anchors"][anchor_first:anchor_first + 2])
        return [x + (y - x) * anchor_alpha for x, y in zip(a, b)]

    shift = [0, 0, 0] if upper is lower else [b - a for a, b in zip(waist(upper), waist(lower))]
    parts = []
    for name, initial in upper["parts"].items():
        bank = 0 if initial["space"] == "upper" else 1
        spec = (upper, lower)[bank]["parts"][name]
        offset = shift if bank == 0 else [0, 0, 0]
        parts.append({"name": name, "bank": bank, "crop": spec["crop"], "shift": offset,
                      "a": spec["frames"][first], "b": spec["frames"][first + 1]})
    left = floor(min(p["crop"][0] + p["shift"][0] for p in parts))
    top = floor(min(p["crop"][1] + p["shift"][1] for p in parts))
    right = ceil(max(p["crop"][0] + p["crop"][2] + p["shift"][0] for p in parts))
    bottom = ceil(max(p["crop"][1] + p["crop"][3] + p["shift"][1] for p in parts))
    return {"first": first, "alpha": alpha, "anchor_phase": (anchor_first, anchor_alpha),
            "parts": parts, "bounds": [left, top, right - left, bottom - top]}


def shadow_view(source, destination):
    """기존 그림자 페이지만 참조하는 뷰를 만든다. 본체 텍스처는 적재하지 않는다."""
    import copy
    source, destination = Path(source).resolve(), Path(destination).resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    clips = {name: copy.deepcopy(clip) for name, clip in data["clips"].items() if name.startswith("shadow/")}
    if not clips or destination.exists():
        raise ValueError("기존 그림자 클립과 새 뷰 경로가 필요하다.")
    result = {key: data[key] for key in ("version", "divisor", "color_alpha_mode", "vector_encoding")}
    result.update(pages={}, frames={}, clips=clips, sources={str(source): hashlib.sha256(source.read_bytes()).hexdigest()})
    for kind, fields in (("color", (0, 1)), ("vector", (2, 3))):
        ids = sorted({pair[field] for clip in clips.values() for pair in clip["pairs"] for field in fields})
        pages = sorted({data["frames"][kind][index]["page"] for index in ids})
        result["pages"][kind] = [{**data["pages"][kind][index],
            "file": Path(os.path.relpath(source.parent / data["pages"][kind][index]["file"], destination.parent)).as_posix()} for index in pages]
        result["frames"][kind] = [{**data["frames"][kind][index], "page": pages.index(data["frames"][kind][index]["page"])} for index in ids]
        remap = {old: new for new, old in enumerate(ids)}
        for clip in clips.values():
            for pair in clip["pairs"]:
                for field in fields:
                    pair[field] = remap[pair[field]]
    for clip in clips.values():
        clip["pairs"] = [pair[:4] for pair in clip["pairs"]]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def build_motion(source, motion, destination, *, max_side=4096, legacy_catalog=None, direction_capture=None,
                 vector_divisor=1, compact_energy=False):
    """기존 UniqueFrames·선반 패킹과 GPU 페이지 캐시 규격을 재사용한다."""
    import numpy as np
    from PIL import Image
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    if vector_divisor not in (1, 2):
        raise ValueError("벡터 해상도 축소 배수는 1 또는 2여야 한다.")
    catalog = json.loads(source.read_text(encoding="utf-8"))
    if catalog.get("type") != "independent_part_motion" or not 1 <= len(catalog["parts"]) <= MAX_PARTS:
        raise ValueError(f"최대 {MAX_PARTS}개 파츠의 독립 모션 입력이 필요하다.")
    clips = {name: clip for name, clip in catalog["clips"].items() if name.rsplit("/", 1)[0] == motion}
    if not clips:
        raise ValueError("선택한 독립 모션이 없다.")
    root = {"version": 1, "type": "part_motion_gpu", "quality": "high", "parts": catalog["parts"],
            "size": catalog["size"], "pivot_top_left": [catalog["pivot"][0], catalog["size"][1] - catalog["pivot"][1]],
            "pixel_scale": catalog["pixel_scale"], "motions": {motion: {}},
            "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "depth_encoding": "rgb24_normalized_valid_alpha", "color_alpha_mode": "premultiplied",
            "vector_divisor": vector_divisor, "sample_fps": catalog["fps"]}
    if "upscale_filter" in catalog:
        root["upscale_filter"] = catalog["upscale_filter"]
    surface = "surface_camera" in catalog
    pbr = catalog.get("material_channels") == ["Metallic", "Roughness", "Specular"]
    kinds = ("color", "vector", "energy", "depth") + (("material",) if pbr else ())
    if surface:
        root["surface_camera"] = catalog["surface_camera"]
        root["shadow_proxy"] = catalog["shadow_proxy"]
        root["shadow_proxy"]["clips"] = {motion: catalog["shadow_proxy"]["clips"][motion]}
        root["surface_encoding"] = "world_normal_rgb_energy_a"
    if pbr:
        root["material_channels"] = catalog["material_channels"]
    if direction_capture is not None:
        from .direction_reprojection import bake_correspondence
        capture = json.loads(Path(direction_capture).read_text(encoding="utf-8"))
        if (capture["size"] != catalog["size"] or capture["pivot"] != catalog["pivot"]
                or capture["source_sha256"] != catalog["source_sha256"]):
            raise ValueError("Unreal 캡처와 파츠 카탈로그의 제작 입력이 다르다.")
        offset = catalog["surface_camera"]["depth_offset_cm"] if surface else None
        root["direction_correspondence"] = bake_correspondence(source, clips, capture["camera"], catalog["size"],
                                                               depth_offset_cm=offset)
        if capture["fps"] in (24, 30) and all(clip["fps"] == capture["fps"] for clip in clips.values()):
            root["direction_sample_fps"] = capture["fps"]
    destination.mkdir(parents=True)
    totals = {"logical_bytes": 0, "disk_bytes": 0, "pages": 0, "maximum_depth_error_cm": 0,
              "maximum_compact_energy_channel_spread": 0,
              "fields": {kind: {"logical_bytes": 0, "disk_bytes": 0} for kind in kinds}}
    for name, original in clips.items():
        direction = str(original["direction"])
        folder = destination / motion / ("d" + direction)
        folder.mkdir(parents=True)
        raw = {}
        minimum, maximum = float("inf"), 0
        for part, spec in original["parts"].items():
            path = (source.parent / spec["clip"]).parent
            width, height = spec["crop"][2:]
            rows = []
            for local, frame in enumerate(spec["frames"]):
                with Image.open(path / frame["color"]) as image:
                    color = image.convert("RGBA").tobytes()
                with Image.open(path / frame["energy"]) as image:
                    energy = image.convert("RGBA").tobytes()
                if color[3::4] != energy[3::4]:
                    raise ValueError("파츠 색상과 마스크의 알파가 다르다.")
                if surface:
                    with Image.open(path / frame["normal"]) as image:
                        world = np.array(image.convert("RGBA"))
                    mask = np.frombuffer(energy, np.uint8).reshape(height, width, 4)
                    if not np.array_equal(world[..., 3], mask[..., 3]):
                        raise ValueError("노멀과 마스크의 알파가 다르다.")
                    strength = np.rint(mask[..., :3].max(axis=2).astype(np.float32) * mask[..., 3] / 255).astype(np.uint8)
                    world[..., :3] = np.rint(world[..., :3].astype(np.float32) * world[..., 3:] / 255).astype(np.uint8)
                    world[..., 3] = strength
                    energy = world.tobytes()
                material = None
                if pbr:
                    with Image.open(path / frame["material"]) as image:
                        material = image.convert("RGBA").tobytes()
                    if material[3::4] != color[3::4]:
                        raise ValueError("재질과 색상의 알파가 다르다.")
                depth = np.frombuffer(zlib.decompress((path / frame["depth"]).read_bytes()), "<f4").reshape(height, width)
                valid = np.isfinite(depth) & (depth > 0)
                if not valid.any() or np.any((np.frombuffer(color, np.uint8).reshape(height, width, 4)[..., 3] > 0) != valid):
                    raise ValueError("파츠 깊이의 유효 영역이 색상과 다르다.")
                minimum = min(minimum, float(depth[valid].min()))
                maximum = max(maximum, float(depth[valid].max()))
                rows.append((color, energy, material, depth, (path / f"forward_{local:03d}.rgba").read_bytes(),
                             (path / f"backward_{local:03d}.rgba").read_bytes()))
            raw[part] = rows
        span = max(1, maximum - minimum)
        pools = {kind: UniqueFrames() for kind in kinds}
        record = {k: v for k, v in original.items() if k != "parts"}
        record.update(parts={}, depth_range=[minimum, span])
        for part, spec in original["parts"].items():
            width, height = spec["crop"][2:]
            frames = []
            for color, energy, material, depth, forward, backward in raw[part]:
                if vector_divisor == 1:
                    flow_a, flow_b = (forward, width, height), (backward, width, height)
                else:
                    flow_a = resize_vectors(forward, width, height, vector_divisor)
                    flow_b = resize_vectors(backward, width, height, vector_divisor)
                depth_pixels = encode_depth(depth, minimum, span)
                reconstructed = decode_depth(depth_pixels, width, height, minimum, span)
                valid = np.isfinite(depth)
                totals["maximum_depth_error_cm"] = max(totals["maximum_depth_error_cm"], float(np.abs(depth[valid] - reconstructed[valid]).max()))
                frames.append({"color": pools["color"].add(resize_color(color, width, height, 1)[0], width, height),
                               "energy": pools["energy"].add(energy if surface else resize_color(energy, width, height, 1)[0], width, height),
                               "depth": pools["depth"].add(depth_pixels, width, height),
                               "forward": pools["vector"].add(*flow_a),
                               "backward": pools["vector"].add(*flow_b)})
                if pbr:
                    premultiplied = resize_color(material, width, height, 1)[0]
                    frames[-1]["material"] = pools["material"].add(premultiplied, width, height)
                if direction_capture is not None:
                    frames[-1]["center_depth"] = float(np.median(depth[valid]))
                    frames[-1]["depth_extent"] = [float(depth[valid].min()), float(depth[valid].max())]
            record["parts"][part] = {"crop": spec["crop"], "space": spec["space"], "frames": frames}
        data = {"version": 1, "pages": {}, "frames": {}, "clip": record}
        for kind, pool in pools.items():
            pages, positions = pack_items(pool.items, max_side=max_side)
            if len(pages) != 1:
                raise ValueError("한 방향의 필드가 여러 페이지다. max_side를 늘려 다시 준비한다.")
            page = pages[0]
            payload = page.pixels
            codec = "rgba_zlib"
            if kind == "material" or (kind == "energy" and not surface):
                rgb = np.frombuffer(payload, np.uint8).reshape(-1, 4)[:, :3]
                payload = rgb.tobytes()
                codec = "rgb8_zlib"
                if kind == "energy" and compact_energy:
                    strength = rgb.max(axis=1)
                    spread = int((strength - rgb.min(axis=1)).max())
                    if spread <= ENERGY_CHANNEL_TOLERANCE:
                        # 셰이더는 필터링한 RGB 중 최댓값을 쓴다. 강도의 필터링 오차는 채널 편차 이하다.
                        payload, codec = strength.tobytes(), "a8_zlib"
                        totals["maximum_compact_energy_channel_spread"] = max(
                            totals["maximum_compact_energy_channel_spread"], spread)
            packed = zlib.compress(payload)
            filename = kind + ".bin"
            (folder / filename).write_bytes(packed)
            data["pages"][kind] = [{"file": filename, "codec": codec, "width": page.width, "height": page.height,
                                     "sha256": hashlib.sha256(packed).hexdigest()}]
            data["frames"][kind] = positions
            totals["logical_bytes"] += len(payload)
            totals["disk_bytes"] += len(packed)
            totals["fields"][kind]["logical_bytes"] += len(payload)
            totals["fields"][kind]["disk_bytes"] += len(packed)
            totals["pages"] += 1
        path = folder / "atlas.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        root["motions"][motion][direction] = path.relative_to(destination).as_posix()
        print(json.dumps({"packed": name, "pages": len(kinds)}), flush=True)
    root["statistics"] = totals
    if legacy_catalog is not None:
        legacy_catalog = Path(legacy_catalog).resolve()
        legacy = json.loads(legacy_catalog.read_text(encoding="utf-8"))
        path = destination / "legacy_shadow" / (motion + ".json")
        shadow_view(legacy_catalog.parent / legacy["motions"][motion]["variants"]["high"], path)
        root["shadow_sources"] = {motion: path.relative_to(destination).as_posix()}
    (destination / "catalog.json").write_text(json.dumps(root, ensure_ascii=False, indent=2), encoding="utf-8")
    return root


def merge_motion_catalogs(sources, destination, *, aliases=None, part_spaces=None):
    """동작별 페이지를 복제하지 않고 하나의 재생 카탈로그로 연결한다."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    common_fields = ("version", "type", "quality", "parts", "size", "pivot_top_left", "pixel_scale",
                     "depth_encoding", "color_alpha_mode", "vector_divisor", "texture_divisor", "texture_scale", "direction_sample_fps",
                     "sample_fps", "upscale_filter", "surface_camera", "surface_encoding", "material_channels")
    motions, shadows, correspondences, members = {}, {}, {}, {}
    shadow_proxy = None
    common = None
    for source in sources:
        source = Path(source).resolve()
        data = json.loads(source.read_text(encoding="utf-8"))
        fields = {key: data.get(key) for key in common_fields}
        if fields["type"] != "part_motion_gpu" or (common is not None and fields != common):
            raise ValueError("같은 형식·파츠·기준점의 GPU 후보가 필요하다.")
        common = fields
        if data.get("shadow_proxy"):
            proxy = data["shadow_proxy"]
            if shadow_proxy is None:
                shadow_proxy = {**proxy, "clips": {}}
            if proxy["bones"] != shadow_proxy["bones"] or proxy["bounds"] != shadow_proxy["bounds"]:
                raise ValueError("같은 리그의 그림자 캐스터가 필요하다.")
            shadow_proxy["clips"].update(proxy["clips"])
        relative = Path(os.path.relpath(source.parent, destination.parent))
        for name, directions in data["motions"].items():
            if name in motions:
                raise ValueError("재생 동작이 중복된다: " + name)
            motions[name] = {key: (relative / path).as_posix() for key, path in directions.items()}
            if name in data.get("shadow_sources", {}):
                shadows[name] = (relative / data["shadow_sources"][name]).as_posix()
            correspondence = data.get("direction_correspondence_by_motion", {}).get(name, data.get("direction_correspondence"))
            if correspondence:
                correspondences[name] = correspondence
            members[name] = (relative / data.get("members", {}).get(name, source.name)).as_posix()
    if not motions:
        raise ValueError("연결할 모션이 없다.")
    spaces = {}
    for motion, mapping in (part_spaces or {}).items():
        if motion not in motions or not set(mapping) <= set(common["parts"]) or not set(mapping.values()) <= {"upper", "lower"}:
            raise ValueError("등록된 동작·파츠의 상하체 귀속이 필요하다: " + motion)
        spaces[motion] = mapping
    for alias, name in (aliases or {}).items():
        if alias in motions or name not in motions:
            raise ValueError("원본이 없거나 이름이 중복된 동작 별칭: " + alias)
        motions[alias] = motions[name]
        members[alias] = members[name]
        if name in correspondences:
            correspondences[alias] = correspondences[name]
        if name in shadows:
            shadows[alias] = shadows[name]
        if name in spaces:
            spaces[alias] = spaces[name]
        if shadow_proxy and name in shadow_proxy["clips"]:
            shadow_proxy["clips"][alias] = shadow_proxy["clips"][name]
    result = {**common, "motions": motions, "shadow_sources": shadows,
              "direction_correspondence_by_motion": correspondences, "members": members,
              "part_spaces": spaces}
    if shadow_proxy:
        result["shadow_proxy"] = shadow_proxy
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def rescale_motion(source, destination, quality):
    """원래 파츠 픽셀 좌표와 시간축을 유지하며 컬러·에너지 텍스처를 줄인다."""
    from PIL import Image
    from ferrial_drive.settings import TEXTURE_QUALITY_SCALES

    source, destination = Path(source).resolve(), Path(destination).resolve()
    root = json.loads(source.read_text(encoding="utf-8"))
    scale = TEXTURE_QUALITY_SCALES[quality]
    if destination.exists() or root["quality"] != "high" or len(root["motions"]) != 1:
        raise ValueError("단일 동작의 높음 아틀라스와 새 출력 경로가 필요하다.")
    root["quality"] = quality
    root.pop("texture_divisor", None)
    root["texture_scale"] = scale
    root.pop("statistics", None)
    root.pop("shadow_sources", None)
    root["source"] = Path(os.path.relpath(source, destination)).as_posix()
    root["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    directions = next(iter(root["motions"].values()))
    for relative in directions.values():
        old_path, new_path = source.parent / relative, destination / relative
        data = json.loads(old_path.read_text(encoding="utf-8"))
        new_path.parent.mkdir(parents=True, exist_ok=True)
        for kind, frames in data["frames"].items():
            page, = data["pages"][kind]
            original_page = old_path.parent / page["file"]
            if kind in ("depth", "vector"):
                page["file"] = Path(os.path.relpath(original_page, new_path.parent)).as_posix()
                continue
            mode = {"a8_zlib": "L", "rgb8_zlib": "RGB", "rgba_zlib": "RGBA"}[page["codec"]]
            packed = original_page.read_bytes()
            if hashlib.sha256(packed).hexdigest() != page["sha256"]:
                raise ValueError("높음 품질 페이지 해시가 다르다.")
            image = Image.frombytes(mode, (page["width"], page["height"]), zlib.decompress(packed))
            pool = UniqueFrames()
            indices = []
            for frame in frames:
                x, y, width, height = frame["rect"]
                tile = image.crop((x, y, x + width, y + height))
                size = (ceil(width * scale), ceil(height * scale))
                if mode == "RGBA":
                    resized = Image.merge(mode, tuple(channel.resize(size, Image.Resampling.BOX) for channel in tile.split()))
                else:
                    resized = tile.resize(size, Image.Resampling.BOX).convert("RGBA")
                indices.append(pool.add(resized.tobytes(), *size))
            pages, placements = pack_items(pool.items, max_side=4096)
            output, = pages
            pixels = output.pixels
            if mode != "RGBA":
                image = Image.frombytes("RGBA", (output.width, output.height), pixels)
                pixels = image.getchannel("R").tobytes() if mode == "L" else image.convert("RGB").tobytes()
            packed = zlib.compress(pixels)
            (new_path.parent / page["file"]).write_bytes(packed)
            page.update(width=output.width, height=output.height, sha256=hashlib.sha256(packed).hexdigest())
            data["frames"][kind] = [placements[index] for index in indices]
        new_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "catalog.json").write_text(json.dumps(root, ensure_ascii=False, indent=2), encoding="utf-8")
    return root
