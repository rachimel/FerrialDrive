"""PBR 프레임별 재질·코팅 값을 절반 해상도로 다시 패킹한다."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ferrial_drive.rendering.motion_atlas import UniqueFrames, pack_items
from ferrial_drive.rendering.part_motion_catalog import PartMotionCatalog
from ferrial_drive.rendering.part_pbr import COAT_CHANNELS
from ferrial_drive.rendering.part_vector_quantization import relative_to
from ferrial_drive.rendering.texture_codecs import texture_payload_size, unpack_payload


def _read(path):
    return json.loads(path.read_bytes())


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _half_page(page, frames, source_dir, output_dir, page_dir, channels, max_side):
    import numpy as np
    from PIL import Image

    source = (source_dir / page["file"]).resolve()
    packed = source.read_bytes()
    if sha256(packed).hexdigest() != page["sha256"]:
        raise ValueError(f"파츠 페이지 해시 불일치: {source}")
    width, height = page["width"], page["height"]
    pixels, compressed = unpack_payload(page["codec"], packed, width, height)
    if compressed or len(pixels) != width * height * channels:
        raise ValueError(f"재질 페이지 채널 수 불일치: {source}")

    layers = Image.frombytes("RGB" if channels == 3 else "LA", (width, height), pixels).split()
    pool = UniqueFrames()
    indices = []
    for frame in frames:
        x, y, w, h = frame["rect"]
        if frame["page"] != 0 or min(x, y) < 0 or min(w, h) < 1 or x + w > width or y + h > height:
            raise ValueError(f"재질 타일 범위 오류: {source}")
        size = (w + 1) // 2, (h + 1) // 2
        tile = [layer.crop((x, y, x + w, y + h)).resize(size, Image.Resampling.BOX) for layer in layers]
        # 독립 수치 채널이라 LA의 알파 가중 필터를 적용하지 않는다.
        blank = Image.new("L", size)
        rgba = Image.merge("RGBA", (*tile, *([blank] * (4 - channels))))
        indices.append(pool.add(rgba.tobytes(), *size))

    # 셰이더는 타일 내부 텍셀 중심에 샘플 좌표를 제한한다.
    pages, placements = pack_items(pool.items, max_side=max_side, padding=0)
    output, = pages
    raw = np.frombuffer(output.pixels, np.uint8).reshape(output.height, output.width, 4)
    payload = zlib.compress(raw[:, :, :channels].tobytes())
    digest = sha256(payload).hexdigest()
    target = page_dir / f"{output.width}x{output.height}-{digest}.bin"
    if not target.is_file():
        target.write_bytes(payload)
    spec = dict(page, file=relative_to(target, output_dir), width=output.width, height=output.height, sha256=digest)
    return spec, [placements[index] for index in indices], source, target


def _downsample_quality(source, output, final, max_side):
    catalog = PartMotionCatalog(source / "catalog.json")
    root = catalog.data
    if not catalog.pbr or not catalog.coat_members or catalog.paged:
        raise ValueError(f"재질과 코팅이 있는 방향별 PBR 아틀라스가 필요하다: {source}")

    coat_index = {}
    before, after = {}, {}
    (output / "material").mkdir(parents=True)
    (output / "coat" / "pages").mkdir(parents=True)

    def resize_entry(page, frames, source_dir, output_dir, page_dir, channels):
        spec, placements, old, new = _half_page(page, frames, source_dir, output_dir, page_dir, channels, max_side)
        for totals, path, row in ((before, old, page), (after, new, spec)):
            totals[path, row["sha256"]] = texture_payload_size(row["codec"], row["width"], row["height"])
        return spec, placements

    for relative, coat_relative in catalog.coat_members.items():
        target = (output / relative).resolve()
        original_coat = (catalog.coat_folder / coat_relative).resolve()
        if not target.is_relative_to(output) or not original_coat.is_relative_to(catalog.coat_folder):
            raise ValueError(f"품질 폴더 밖의 방향·코팅 경로: {relative}")
        original = source / relative
        direction = _read(original)
        for kind, entries in direction["pages"].items():
            if kind == "material":
                page, = entries
                spec, frames = resize_entry(page, direction["frames"][kind], original.parent,
                                            target.parent, output / "material", 3)
                direction["pages"][kind] = [spec]
                direction["frames"][kind] = frames
            else:
                for page in entries:
                    page["file"] = relative_to(original.parent / page["file"], (final / relative).parent)
        _write(target, direction)

        coat = _read(original_coat)
        target_coat = output / "coat" / "directions" / f"{len(coat_index):04d}.json"
        coat["page"], coat["frames"] = resize_entry(coat["page"], coat["frames"], original_coat.parent,
                                                     target_coat.parent, output / "coat" / "pages", 2)
        _write(target_coat, coat)
        coat_index[relative] = target_coat.relative_to(output / "coat").as_posix()

    for field in ("shadow_sources", "members"):
        if field in root:
            root[field] = {key: relative_to(source / path, final) for key, path in root[field].items()}
    if "source" in root:
        root["source"] = relative_to(source / root["source"], final)
    root.pop("statistics", None)
    root["coat_index"] = "coat/index.json"
    _write(output / root["coat_index"], {"channels": COAT_CHANNELS, "members": coat_index})
    _write(output / "catalog.json", root)
    return {"directions": len(coat_index), "before_bytes": sum(before.values()), "after_bytes": sum(after.values()),
            "before_disk_bytes": sum(path.stat().st_size for path in {p for p, _ in before}),
            "after_disk_bytes": sum(path.stat().st_size for path in {p for p, _ in after})}


def downsample_profiles(source, destination, *, max_side=4096):
    """기존 색상·노멀·깊이·벡터 페이지를 참조하는 새 프로필을 만든다."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="part-surface-", dir=destination.parent) as temporary:
        stage = Path(temporary).resolve() / destination.name
        stats = {quality: _downsample_quality(source / quality, stage / quality, destination / quality, max_side)
                 for quality in ("high", "medium", "low")}
        _write(stage / "statistics.json", stats)
        stage.rename(destination)
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, required=True, help="높음·보통·낮음 원본 품질 폴더")
    parser.add_argument("--output", type=Path, required=True, help="축소한 품질을 저장할 새 폴더")
    args = parser.parse_args()
    print(json.dumps(downsample_profiles(args.profiles, args.output)))


if __name__ == "__main__":
    main()
