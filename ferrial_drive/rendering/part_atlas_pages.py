"""파츠별 8방향 텍스처 페이지를 만들고 기존 BC7 블록을 보존한다."""

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import zlib

from .motion_atlas import align_four
from .part_vector_quantization import relative_to
from .texture_codecs import unpack_payload


PAGE_SIDES = {"color": 512, "depth": 512, "vector": 256, "energy": 256}
PAGE_CODECS = {"color": "bc7_zlib", "depth": "rgba_zlib", "vector": "rg8_zlib", "energy": "a8_zlib"}
CHANNELS = {"color": 16, "depth": 4, "vector": 2, "energy": 1}
FRAME_FIELDS = {kind: ("forward", "backward") if kind == "vector" else (kind,) for kind in PAGE_SIDES}


@dataclass
class Shelf:
    top: int
    height: int
    right: int = 0


@dataclass
class PackedPage:
    shelves: list = field(default_factory=list)
    placements: dict = field(default_factory=dict)
    bottom: int = 0


def pack_tiles(tiles, side, block_aligned, *, access_order=False):
    pages = []
    keys = tiles if access_order else sorted(tiles, key=lambda tile: (-tile[1], -tile[0], tile[2]))
    for key in keys:
        width, height, _ = key
        padded_w, padded_h = width + 2, height + 2
        if block_aligned:
            padded_w, padded_h = align_four(padded_w), align_four(padded_h)
        if max(padded_w, padded_h) > side:
            raise ValueError(f"페이지보다 큰 타일: {width}×{height}, 페이지 {side}")
        open_pages = pages[-3:] if access_order else pages
        choices = ((shelf.height - padded_h, side - shelf.right - padded_w, index, shelf_index)
                   for index, page in enumerate(open_pages) for shelf_index, shelf in enumerate(page.shelves)
                   if shelf.height >= padded_h and shelf.right + padded_w <= side)
        match = min(choices, default=None)
        if match is None:
            page = next((page for page in open_pages if page.bottom + padded_h <= side), None)
            if page is None:
                page = PackedPage()
                pages.append(page)
            shelf = Shelf(page.bottom, padded_h)
            page.shelves.append(shelf)
            page.bottom += padded_h
        else:
            page = open_pages[match[2]]
            shelf = page.shelves[match[3]]
        page.placements[key] = (shelf.right + 1, shelf.top + 1, width, height)
        shelf.right += padded_w
    return pages


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def source_pixels(path, atlases, kind):
    import numpy as np

    sources, by_path = {}, {}
    block = 4 if kind == "color" else 1
    for manifest, atlas in zip(path, atlases, strict=True):
        entries = atlas["pages"][kind]
        page, = entries
        if page["codec"] != PAGE_CODECS[kind]:
            raise ValueError(f"기존 Oodle BC7·RG8·A8 플레이어 카탈로그가 필요하다: {manifest} / {kind}")
        filename = (manifest.parent / page["file"]).resolve()
        if filename not in by_path:
            packed = filename.read_bytes()
            if sha256(packed).hexdigest() != page["sha256"]:
                raise ValueError(f"페이지 해시 불일치: {filename}")
            w, h = page["width"], page["height"]
            data, _ = unpack_payload(page["codec"], packed, w, h)
            by_path[filename] = np.frombuffer(data, np.uint8).reshape(h // block, w // block, CHANNELS[kind])
        sources[manifest] = by_path[filename]
    return sources


def visible_depth_bounds(pixels, frames):
    import numpy as np

    bounds = []
    for frame in frames:
        x, y, w, h = frame["rect"]
        valid = pixels[y:y+h, x:x+w, 3]
        rows = np.flatnonzero(valid.any(axis=1))
        columns = np.flatnonzero(valid.any(axis=0))
        bounds.append((int(columns[0]), int(rows[0]), int(columns[-1]) + 1, int(rows[-1]) + 1, w, h)
                      if len(rows) else (0, 0, 0, 0, w, h))
    return bounds


def frame_crop(bounds, width, height, block):
    left, top, right, bottom, source_width, source_height = bounds
    if left == right or top == bottom:
        return None
    # 가시 깊이 경계 바깥에 선형 필터용 여백을 남기고 BC7 시작 블록을 보존한다.
    x = max(0, left * width // source_width - 2) // block * block
    y = max(0, top * height // source_height - 2) // block * block
    right = min(width, (right * width + source_width - 1) // source_width + 2)
    bottom = min(height, (bottom * height + source_height - 1) // source_height + 2)
    return x, y, right - x, bottom - y


def extract_tile(kind, pixels, descriptor, bounds=None):
    import numpy as np

    x, y, w, h = descriptor["rect"]
    extras = {key: value for key, value in descriptor.items() if key not in ("rect", "page")}
    if bounds is not None:
        crop = frame_crop(bounds, w, h, 4 if kind == "color" else 1)
        if crop is None:
            return None, None, extras
        left, top, width, height = crop
        extras["frame_crop"] = [left, top, w, h]
        x, y, w, h = x + left, y + top, width, height
    if kind == "color":
        if (x - 1) % 4 or (y - 1) % 4:
            raise ValueError("기존 BC7 타일은 4×4 블록에 정렬되어 있어야 한다.")
        ox, oy = (x - 1) // 4, (y - 1) // 4
        tile = pixels[oy:oy + align_four(h + 2)//4, ox:ox + align_four(w + 2)//4]
    else:
        tile = pixels[y:y+h, x:x+w]
    if kind == "energy":
        yy, xx = np.nonzero(tile[:, :, 0])
        if not len(xx):
            return None, None, extras
        # 보간에서 발광 경계에 인접한 0 마스크도 읽는다.
        left, top = max(0, int(xx.min()) - 1), max(0, int(yy.min()) - 1)
        right, bottom = min(w, int(xx.max()) + 2), min(h, int(yy.max()) + 2)
        extras["mask_crop"] = [left, top, w, h]
        tile = tile[top:bottom, left:right]
        w, h = right - left, bottom - top
    if kind == "vector" and extras.get("flow_step") == [0, 0]:
        return None, None, extras
    return (w, h, sha256(tile.tobytes()).digest()), tile, extras


class PageWriter:
    def __init__(self, directory):
        self.directory = directory
        self.pages = {}
        self.offsets = defaultdict(int)
        self.stats = defaultdict(lambda: {"pages": 0, "storage_bytes": 0, "disk_bytes": 0})
        (directory / "pages").mkdir()

    def write(self, kind, page, tiles, *, part=None):
        import numpy as np

        block = 4 if kind == "color" else 1
        width = align_four(max(shelf.right for shelf in page.shelves))
        height = align_four(page.bottom)
        canvas = np.zeros((height // block, width // block, CHANNELS[kind]), np.uint8)
        for key, (x, y, _, _) in page.placements.items():
            tile = tiles[key]
            if block == 1:
                tile = np.pad(tile, ((1, 1), (1, 1), (0, 0)), mode="edge")
            row, column = (y - 1) // block, (x - 1) // block
            h, w = tile.shape[:2]
            canvas[row:row+h, column:column+w] = tile
        raw = canvas.tobytes()
        identity = part, kind, width, height, sha256(raw).digest()
        if identity in self.pages:
            return self.pages[identity]
        data = zlib.compress(raw, level=3)
        folder = f"pages/{part}" if part is not None else "pages"
        file = f"{folder}/{kind}.bin"
        offset = self.offsets[file]
        path = self.directory / file
        if offset == 0:
            path.parent.mkdir(exist_ok=True)
        with path.open("ab") as stream:
            stream.write(data)
        self.offsets[file] += len(data)
        spec = {"file": "../" + file, "width": width, "height": height,
                "codec": PAGE_CODECS[kind], "sha256": sha256(data).hexdigest(),
                "offset": offset, "length": len(data)}
        if part is not None:
            spec["part"] = part
        self.pages[identity] = spec
        stats = self.stats[kind]
        stats["pages"] += 1
        stats["storage_bytes"] += len(raw)
        stats["disk_bytes"] += len(data)
        return spec


def repack_track(kind, name, inputs, outputs, pixels, writer, page_ids, depth_bounds):
    tiles = {}
    refs = []
    for i, (src, dst) in enumerate(zip(inputs, outputs, strict=True)):
        part = src["clip"]["parts"].get(name)
        if part is None:
            continue
        used = {}
        frames = dst["frames"][kind]
        pairs = zip(part["frames"], dst["clip"]["parts"][name]["frames"], strict=True)
        for before, after in pairs:
            for field in FRAME_FIELDS[kind]:
                old = before[field]
                bounds = depth_bounds[i][before["depth"]] if kind in ("color", "depth") else None
                source_id = old, bounds
                if source_id not in used:
                    key, tile, info = extract_tile(kind, pixels[i], src["frames"][kind][old], bounds)
                    used[source_id] = len(frames)
                    frames.append(info)
                    refs.append((i, info, key))
                    if key is not None:
                        tiles.setdefault(key, tile)
                after[field] = used[source_id]
    locations = {}
    for page in pack_tiles(tiles, PAGE_SIDES[kind], kind == "color"):
        spec = writer.write(kind, page, tiles)
        locations.update({key: (spec, rect) for key, rect in page.placements.items()})
    for direction, frame, key in refs:
        if key is None:
            frame.update(page=-1, rect=[0, 0, 0, 0])
            continue
        spec, rect = locations[key]
        pages = outputs[direction]["pages"][kind]
        mapping = page_ids[direction]
        identity = spec["file"], spec["offset"]
        if identity not in mapping:
            mapping[identity] = len(pages)
            pages.append(spec)
        frame.update(page=mapping[identity], rect=rect)


def packing_groups(motions, order):
    groups, seen = defaultdict(list), set()
    for motion, directions in motions.items():
        for direction, relative in directions.items():
            if relative in seen:
                continue
            seen.add(relative)
            groups[motion if order == "motion" else direction].append(relative)
    return groups


def repack_catalog(source, destination, *, order="motion", progress=None):
    """한 품질의 모션별 8방향을 파츠 단위로 패킹하고 참조를 다시 연결한다."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    if order not in ("motion", "direction"):
        raise ValueError("페이지 배치 순서는 motion 또는 direction이어야 한다.")
    catalog = read_json(source)
    if catalog.get("type") != "part_motion_gpu" or catalog.get("version") != 1 or catalog.get("part_pages"):
        raise ValueError("기존 플레이어 파츠 카탈로그가 필요하다.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="part-pages-", dir=destination.parent) as tmp:
        stage = Path(tmp) / destination.name
        manifests_dir = stage / "atlases"
        manifests_dir.mkdir(parents=True)
        writer = PageWriter(stage)
        manifest_names = {}
        for group, relatives in packing_groups(catalog["motions"], order).items():
            old_paths = [(source.parent / relative).resolve() for relative in relatives]
            inputs = [read_json(path) for path in old_paths]
            outputs = [dict(atlas, clip=deepcopy(atlas["clip"]), pages={kind: [] for kind in PAGE_SIDES},
                            frames={kind: [] for kind in PAGE_SIDES}) for atlas in inputs]
            depth_sources = source_pixels(old_paths, inputs, "depth")
            depth_bounds = [visible_depth_bounds(depth_sources[path], atlas["frames"]["depth"])
                            for path, atlas in zip(old_paths, inputs, strict=True)]
            for kind in PAGE_SIDES:
                sources = depth_sources if kind == "depth" else source_pixels(old_paths, inputs, kind)
                pixels = [sources[path] for path in old_paths]
                ids = [{} for _ in inputs]
                for part in catalog["parts"]:
                    repack_track(kind, part, inputs, outputs, pixels, writer, ids, depth_bounds)
            for relative, atlas in zip(relatives, outputs, strict=True):
                name = f"atlases/{len(manifest_names):04d}.json"
                manifest_names[relative] = name
                (stage / name).write_text(json.dumps(atlas, separators=(",", ":")), encoding="utf-8")
            if progress:
                progress(group, len(manifest_names))
        catalog["motions"] = {motion: {direction: manifest_names[rel] for direction, rel in dirs.items()}
                              for motion, dirs in catalog["motions"].items()}
        for key in ("shadow_sources", "members"):
            if key in catalog:
                catalog[key] = {name: relative_to(source.parent / rel, destination) for name, rel in catalog[key].items()}
        if "source" in catalog:
            catalog["source"] = relative_to(source.parent / catalog["source"], destination)
        layout = "part_motion_direction" if order == "motion" else "part_direction_motion"
        catalog["part_pages"] = {"version": 1, "sides": PAGE_SIDES, "layout": layout, "geometry_crop": "frame"}
        catalog["statistics"] = dict(writer.stats)
        (stage / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        stage.rename(destination)
    return dict(writer.stats)
