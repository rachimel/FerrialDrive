"""고유 프레임·벡터의 공유 아틀라스 제작. CPU 작업과 GPU 수명을 분리한다."""

from dataclasses import dataclass
import hashlib
import json
from math import ceil, sqrt
from pathlib import Path
from time import perf_counter
import zlib

from .texture_codecs import OodleEncoder, bc7_size, encode_ktx, texture_payload_size


def align_four(value):
    return (value + 3) // 4 * 4


def resize_color(pixels, width, height, divisor):
    """알파 사전 곱셈 뒤 면적 필터를 적용해 투명 경계의 색 번짐을 막는다."""
    import numpy as np
    from PIL import Image
    values = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 4).astype(np.uint16)
    values[:, :, :3] = (values[:, :, :3] * values[:, :, 3:4] + 127) // 255
    size = (ceil(width / divisor), ceil(height / divisor))
    image = Image.fromarray(values.astype(np.uint8))
    if divisor != 1:
        # 모드별 알파 처리를 피한다. 입력은 이미 premultiplied RGBA다.
        image = Image.merge("RGBA", tuple(channel.resize(size, Image.Resampling.BOX) for channel in image.split()))
    return image.tobytes(), *size


def resize_vectors(pixels, width, height, divisor):
    """바이트 채널이 아닌 signed16 변위를 리샘플하고 새 픽셀 단위로 바꾼다."""
    import numpy as np
    from PIL import Image
    channels = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 4).astype(np.int32)
    fields = np.stack((channels[:, :, 0] * 256 + channels[:, :, 1],
                       channels[:, :, 2] * 256 + channels[:, :, 3]), axis=-1)
    fields = (fields - 32768).astype(np.float32) / 64
    size = (ceil(width / divisor), ceil(height / divisor))
    result = np.empty((size[1], size[0], 4), dtype=np.uint8)
    for axis in range(2):
        field = Image.fromarray(fields[:, :, axis])
        field = np.array(field.resize(size, Image.Resampling.BOX), copy=True)
        field *= size[axis] / (width if axis == 0 else height)
        encoded = np.rint(field * 64).astype(np.int32) + 32768
        if encoded.min() < 0 or encoded.max() > 65535:
            raise ValueError("축소 벡터가 signed16 범위를 벗어났다.")
        result[:, :, axis * 2] = encoded // 256
        result[:, :, axis * 2 + 1] = encoded % 256
    return result.tobytes(), *size


@dataclass(frozen=True)
class AtlasItem:
    width: int
    height: int
    pixels: bytes


class UniqueFrames:
    def __init__(self):
        self.items, self.lookup = [], {}
        self.references = 0

    def add(self, pixels, width, height):
        if len(pixels) != width * height * 4:
            raise ValueError("프레임 바이트 수가 크기와 다르다.")
        self.references += 1
        key = (width, height, hashlib.sha256(pixels).digest())
        if key not in self.lookup:
            self.lookup[key] = len(self.items)
            self.items.append(AtlasItem(width, height, pixels))
        return self.lookup[key]


def pack_items(items, *, max_side=2048, padding=4):
    """4픽셀 경계의 단순 선반 패킹. 큰 데이터는 페이지로 나눈다."""
    import numpy as np
    if not items or max_side < 8 or max_side % 4 or padding < 0 or padding % 4:
        raise ValueError("아틀라스 크기·패딩·입력 오류")
    dimensions = [(align_four(item.width + padding * 2), align_four(item.height + padding * 2))
                  for item in items]
    if any(max(size) > max_side for size in dimensions):
        raise ValueError("프레임이 아틀라스 페이지 제한보다 크다.")
    side = min(max_side, max(max(w for w, _ in dimensions), align_four(ceil(sqrt(sum(w*h for w, h in dimensions))))))
    positions, pages = [None] * len(items), []
    page, x, y, shelf_height = [], 0, 0, 0
    for index in sorted(range(len(items)), key=lambda i: (-dimensions[i][1], -dimensions[i][0], i)):
        width, height = dimensions[index]
        if x + width > side:
            x, y, shelf_height = 0, y + shelf_height, 0
        if y + height > max_side:
            pages.append(page)
            page, x, y, shelf_height = [], 0, 0, 0
        page.append((index, x, y, width, height))
        x += width
        shelf_height = max(shelf_height, height)
    if page:
        pages.append(page)
    textures = []
    for page_index, entries in enumerate(pages):
        width = max(x + w for _, x, _, w, _ in entries)
        height = max(y + h for _, _, y, _, h in entries)
        canvas = np.zeros((height, width, 4), dtype=np.uint8)
        for index, x, y, tile_w, tile_h in entries:
            item = items[index]
            image = np.frombuffer(item.pixels, dtype=np.uint8).reshape(item.height, item.width, 4)
            extended = np.pad(image, ((padding, tile_h-item.height-padding),
                                      (padding, tile_w-item.width-padding), (0, 0)), mode="edge")
            canvas[y:y+tile_h, x:x+tile_w] = extended
            positions[index] = {"page": page_index, "rect": [x+padding, y+padding, item.width, item.height]}
        textures.append(AtlasItem(width, height, canvas.tobytes()))
    return textures, positions


def select_catalogs(catalogs, patterns):
    from fnmatch import fnmatchcase
    selected = []
    names = set()
    for catalog_path in catalogs:
        catalog_path = Path(catalog_path).resolve()
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        for row in data["clips"]:
            if patterns and not any(fnmatchcase(row["name"], pattern) for pattern in patterns):
                continue
            if row["name"] in names:
                raise ValueError("카탈로그 사이 클립 이름이 중복됐다.")
            names.add(row["name"])
            selected.append((catalog_path, row))
    if not selected:
        raise ValueError("선택한 보간 클립이 없다.")
    return selected


def build_variant(selected, destination, divisor, *, max_side=2048):
    from PIL import Image
    from .motion_vectors import load_clip
    started = perf_counter()
    colors, vectors, energy = UniqueFrames(), UniqueFrames(), UniqueFrames()
    clips, sources = {}, {}
    for catalog, row in selected:
        image_cache = {}

        def read_image(path):
            path = Path(path).resolve()
            if path not in image_cache:
                with Image.open(path) as image:
                    image = image.convert("RGBA")
                    image_cache[path] = (*image.size, image.tobytes())
            return image_cache[path]

        motion_path = (catalog.parent / row["path"]).resolve()
        motion = load_clip(motion_path, read_image)
        energy_paths = json.loads(motion_path.read_text(encoding="utf-8")).get("energy_frames", [])
        if energy_paths and len(energy_paths) != len(motion.pairs) + 1:
            raise ValueError("Energy Mask에는 각 구간 양끝의 원본 프레임이 필요하다.")
        frames = []
        for pair_index, pair in enumerate(motion.pairs):
            indices = []
            for field, pool, resize in (("rgba_a", colors, resize_color), ("rgba_b", colors, resize_color),
                                        ("forward", vectors, resize_vectors), ("backward", vectors, resize_vectors)):
                pixels, width, height = resize(getattr(pair, field), pair.width, pair.height, divisor)
                indices.append(pool.add(pixels, width, height))
            if energy_paths:
                for index, color in ((pair_index, pair.rgba_a), (pair_index + 1, pair.rgba_b)):
                    width, height, raw = read_image(motion_path.parent / energy_paths[index])
                    if (width, height) != (pair.width, pair.height) or raw[3::4] != color[3::4]:
                        raise ValueError("Energy Mask의 크기·알파가 같은 구간의 색상과 다르다.")
                    pixels, width, height = resize_color(raw, width, height, divisor)
                    indices.append(energy.add(pixels, width, height))
            frames.append(indices)
        first = motion.pairs[0]
        clips[row["name"]] = {"pairs": frames, "interval_seconds": first.duration_seconds,
                              "source_size": [first.width, first.height],
                              "size": [ceil(first.width/divisor), ceil(first.height/divisor)],
                              "pivot": row["pivot_top_left"], "pixel_scale": row["pixel_scale"], "loop": row["loop"]}
        sources[str(catalog)] = hashlib.sha256(catalog.read_bytes()).hexdigest()
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {"version": 1, "divisor": divisor, "color_alpha_mode": "premultiplied",
                "vector_encoding": "signed16_rgba_x64", "clips": clips, "sources": sources,
                "pages": {}, "frames": {}, "statistics": {}}
    pools = [("color", colors), ("vector", vectors)]
    if energy.items:
        pools.append(("energy", energy))
    for kind, pool in pools:
        pages, positions = pack_items(pool.items, max_side=max_side)
        manifest["frames"][kind] = positions
        manifest["pages"][kind] = []
        for index, page in enumerate(pages):
            name = f"{kind}_{index:03}.rgba.zlib"
            packed = zlib.compress(page.pixels, 6)
            (destination / name).write_bytes(packed)
            manifest["pages"][kind].append({"file": name, "codec": "rgba_zlib", "width": page.width,
                                           "height": page.height, "sha256": hashlib.sha256(packed).hexdigest()})
        manifest["statistics"][kind] = {"references": pool.references, "unique_frames": len(pool.items),
                                         "unique_pixels": sum(item.width*item.height for item in pool.items),
                                         "atlas_pixels": sum(page.width*page.height for page in pages)}
    manifest["statistics"]["prepare_seconds"] = perf_counter() - started
    write_manifest(destination, manifest)
    return manifest


def write_manifest(destination, manifest):
    path = Path(destination) / "atlas.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def merge_variants(sources, destination, *, aliases=None, source_guards=None):
    """같은 품질의 완성 아틀라스를 파일 재인코딩 없이 한 카탈로그로 연결한다."""
    import copy
    import os
    started = perf_counter()
    destination = Path(destination).resolve()
    if destination.exists() or not sources:
        raise ValueError("새 출력 폴더와 병합할 아틀라스가 필요하다.")
    fields = ("version", "divisor", "color_alpha_mode", "vector_encoding")
    result = None
    for source in sources:
        source = Path(source).resolve()
        document = json.loads(source.read_text(encoding="utf-8"))
        if result is None:
            result = {key: document[key] for key in fields}
            result.update(pages={}, frames={}, clips={}, sources={}, statistics={})
        elif any(document[key] != result[key] for key in fields):
            raise ValueError("같은 해상도·알파·벡터 규격의 아틀라스만 연결한다.")
        page_offsets, frame_offsets = {}, {}
        for kind, pages in document["pages"].items():
            target_pages = result["pages"].setdefault(kind, [])
            target_frames = result["frames"].setdefault(kind, [])
            page_offsets[kind], frame_offsets[kind] = len(target_pages), len(target_frames)
            for page in pages:
                path = (source.parent / page["file"]).resolve()
                if not path.is_file():
                    raise FileNotFoundError(path)
                target_pages.append({**page, "file": Path(os.path.relpath(path, destination)).as_posix()})
            target_frames.extend({**frame, "page": frame["page"] + page_offsets[kind]}
                                 for frame in document["frames"][kind])
        for name, clip in document["clips"].items():
            if name in result["clips"]:
                raise ValueError("병합할 동작 이름이 중복됐다: " + name)
            clone = copy.deepcopy(clip)
            for pair in clone["pairs"]:
                if len(pair) not in (4, 6):
                    raise ValueError("색상·벡터와 선택 마스크 쌍이 필요하다.")
                for index, kind in enumerate(("color", "color", "vector", "vector", "energy", "energy")[:len(pair)]):
                    if not 0 <= pair[index] < len(document["frames"][kind]):
                        raise ValueError("원본 아틀라스 프레임 범위 오류")
                    pair[index] += frame_offsets[kind]
            result["clips"][name] = clone
        for filename, digest in {**document.get("sources", {}), str(source): hashlib.sha256(source.read_bytes()).hexdigest()}.items():
            if filename in result["sources"] and result["sources"][filename] != digest:
                raise ValueError("같은 제작 입력에 서로 다른 해시가 있다.")
            result["sources"][filename] = digest
    for name, clip in list(result["clips"].items()):
        motion, separator, direction = name.rpartition("/")
        target = (aliases or {}).get(name)
        if target is None and separator and motion in (aliases or {}):
            target = aliases[motion] + "/" + direction
        if target is not None:
            if target in result["clips"]:
                raise ValueError("별칭이 기존 동작과 충돌한다.")
            result["clips"][target] = copy.deepcopy(clip)
    for filename, digest in (source_guards or {}).items():
        if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != digest:
            raise ValueError("병합 전에 제작 입력이 바뀌었다.")
        result["sources"][str(filename)] = digest
    result["statistics"] = {kind: {"unique_frames": len(result["frames"][kind]),
        "atlas_pixels": sum(p["width"]*p["height"] for p in pages)} for kind, pages in result["pages"].items()}
    result["statistics"]["prepare_seconds"] = perf_counter()-started
    destination.mkdir(parents=True)
    write_manifest(destination, result)
    return result


def encode_variant(source, destination, *, codec, ktx_executable=None, oodle_library=None, rdo_lambda=30):
    import copy
    source, destination = Path(source).resolve(), Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((source / "atlas.json").read_text(encoding="utf-8"))
    manifest = copy.deepcopy(manifest)
    # 모든 후보가 동일한 무손실 벡터 파일을 참조하여 GPU 캐시도 공유한다.
    import os
    for page in manifest["pages"]["vector"]:
        page["file"] = os.path.relpath(source / page["file"], destination)
    # 마스크는 압축 색상의 오차와 분리해 무손실 원본을 공유한다.
    for page in manifest["pages"].get("energy", []):
        page["file"] = os.path.relpath(source / page["file"], destination)
    started = perf_counter()
    encoder = OodleEncoder(oodle_library) if codec == "oodle" else None
    for index, page in enumerate(manifest["pages"]["color"]):
        pixels = zlib.decompress((source / page["file"]).read_bytes())
        width, height = page["width"], page["height"]
        if codec == "oodle":
            payload = encoder.bc7(pixels, width, height, rdo_lambda=rdo_lambda)
            name = f"color_{index:03}.bc7.zlib"
            packed = zlib.compress(payload, 6)
            (destination / name).write_bytes(packed)
            page["codec"] = "bc7_zlib"
        elif codec == "ktx":
            raw_path = destination / f"color_{index:03}.raw"
            raw_path.write_bytes(pixels)
            name = f"color_{index:03}.ktx2"
            encode_ktx(ktx_executable, raw_path, destination / name, width, height)
            packed = (destination / name).read_bytes()
            # raw는 재생성 가능한 출력이며 성공한 인코딩 후에만 정리한다.
            raw_path.unlink()
            page["codec"] = "ktx2_uastc"
        else:
            raise ValueError("인코더 선택 오류")
        page.update(file=name, sha256=hashlib.sha256(packed).hexdigest())
    manifest["statistics"]["encoder"] = codec
    manifest["statistics"]["rdo_lambda"] = rdo_lambda if codec == "oodle" else 1
    manifest["statistics"]["encode_seconds"] = perf_counter() - started
    return write_manifest(destination, manifest)


def payload_summary(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    disk, gpu, paths = 0, 0, set()
    for pages in data["pages"].values():
        for page in pages:
            path = (manifest_path.parent / page["file"]).resolve()
            if path not in paths:
                paths.add(path)
                disk += path.stat().st_size
                gpu += texture_payload_size(page["codec"], page["width"], page["height"])
    return {"disk_bytes": disk + manifest_path.stat().st_size, "gpu_payload_bytes": gpu,
            "pages": len(paths), "clips": len(data["clips"]), "statistics": data["statistics"]}
