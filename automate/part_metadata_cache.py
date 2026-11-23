"""지정한 카탈로그들의 CPU 메타데이터 패킹본을 만든다."""

from argparse import ArgumentParser
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ferrial_drive.rendering.part_metadata_archive import CACHE_VERSION, encode, source_stamp
from ferrial_drive.rendering.part_metadata import pack_track_metadata
from ferrial_drive.rendering.part_motion_catalog import PartMotionCatalog


def build(catalogs, output, tracks=()):
    members = {}
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as folder:
        staged = Path(folder) / "metadata.zip"
        with ZipFile(staged, "w") as archive:
            def add(path, data, coat=None):
                key = str(path.resolve())
                stamp = source_stamp(path), source_stamp(coat) if coat else None
                if key in members:
                    if members[key][1:] != list(stamp):
                        raise ValueError(f"같은 방향 파일이 다른 코팅 자료를 참조한다: {path}")
                    return
                entry = f"records/{len(members)}"
                archive.writestr(entry, encode(data))
                members[key] = [entry, *stamp]

            for source in tracks:
                data = json.loads(source.read_text(encoding="utf-8"))
                pack_track_metadata(data)
                add(source, data)
            for source in catalogs:
                catalog = PartMotionCatalog(source, packed=True)
                add(catalog.source, catalog.data)
                for motion, directions in catalog.data["motions"].items():
                    for direction, relative in directions.items():
                        path = (catalog.source.parent / relative).resolve()
                        coat = (catalog.coat_folder / catalog.coat_members[relative]).resolve() if catalog.coat_members else None
                        previous = members.get(str(path))
                        if previous is not None and previous[2] == (source_stamp(coat) if coat else None):
                            continue
                        add(path, catalog.read_direction(motion, direction), coat)
            archive.writestr("index.json", json.dumps(
                {"version": CACHE_VERSION, "members": members}, ensure_ascii=False))
        if os.name == "nt":
            staged.rename(output)
        else:
            os.link(staged, output)
    return len(members)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", action="append", type=Path, default=[])
    parser.add_argument("--track", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not (args.catalog or args.track):
        parser.error("--catalog 또는 --track 입력이 필요하다.")
    count = build(args.catalog, args.output, args.track)
    print(f"{count}개 CPU 메타데이터 레코드 저장: {args.output}")


if __name__ == "__main__":
    main()
