"""검증한 원본 JSON의 런타임 패킹본을 로컬 ZIP에서 읽는다."""

from functools import lru_cache
import json
import os
from pathlib import Path
from struct import Struct, error
from zipfile import BadZipFile, ZipFile

from .part_metadata import PackedFrameRows, PackedShadowPoses, PackedTrackRows, pack_track_metadata


HEADER = Struct("<I")
CACHE_VERSION = 1
TAG = "_fdrive_packed_v1"


def source_stamp(path):
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns]


def encode(data):
    blocks = []
    offset = 0

    def packed(value):
        nonlocal offset
        if isinstance(value, PackedShadowPoses):
            kind, offsets = "shadow", ()
        elif isinstance(value, PackedFrameRows):
            kind, offsets = "frames", value._offsets
        elif isinstance(value, PackedTrackRows):
            kind, offsets = "tracks", (value._fields, value._points)
        else:
            raise TypeError(f"패킹할 수 없는 데이터다: {type(value).__name__}")
        size = len(value._data)
        chunk = {TAG: [kind, offset, size, value._format.format, len(value), offsets]}
        blocks.append(value._data)
        offset += size
        return chunk

    description = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=packed).encode("utf-8")
    return b"".join((HEADER.pack(len(description)), description, *blocks))


def decode(data):
    size, = HEADER.unpack_from(data)
    start = HEADER.size + size
    payload = memoryview(data)[start:]

    def packed(value):
        if TAG not in value:
            return value
        kind, offset, length, binary_format, count, offsets = value[TAG]
        if offset < 0 or count < 0 or length < 0 or offset + length > len(payload):
            raise ValueError("메타데이터 패킹 범위가 잘못됐다.")
        fmt = Struct(binary_format)
        if fmt.size * count != length:
            raise ValueError("메타데이터 레코드 길이가 일치하지 않는다.")
        if kind == "shadow":
            result = PackedShadowPoses.__new__(PackedShadowPoses)
            result._samples = [(-1, None), (-1, None)]
        elif kind == "frames":
            result = PackedFrameRows.__new__(PackedFrameRows)
            result._offsets = offsets
            result._rows = {}
        elif kind == "tracks":
            result = PackedTrackRows.__new__(PackedTrackRows)
            result._fields, result._points = offsets
            result._recent = [(-1, None), (-1, None)]
        else:
            raise ValueError("지원하지 않는 메타데이터 레코드 종류다.")
        result._data = payload[offset:offset + length]
        result._format = fmt
        result._length = count
        return result

    return json.loads(data[HEADER.size:start], object_hook=packed)


class PackedMetadataArchive:
    def __init__(self, path):
        self.archive = ZipFile(path)
        try:
            index = json.loads(self.archive.read("index.json"))
            if index["version"] != CACHE_VERSION:
                raise ValueError("지원하지 않는 아틀라스 메타데이터 캐시 버전이다.")
            self.members = index["members"]
        except BaseException:
            self.archive.close()
            raise

    def read(self, source, *, coat=None):
        try:
            name, stamp, coat_stamp = self.members[str(source.resolve())]
            if source_stamp(source) != stamp or (source_stamp(coat) if coat else None) != coat_stamp:
                return None
            return decode(self.archive.read(name))
        except (OSError, ValueError, KeyError, TypeError, error, BadZipFile):
            return None


@lru_cache(maxsize=2)
def open_archive(path):
    try:
        return PackedMetadataArchive(Path(path))
    except (OSError, ValueError, KeyError, TypeError, BadZipFile):
        return None


def metadata_mode():
    mode = os.getenv("FDRIVE_PACKED_PART_METADATA", "0")
    return mode == "1", open_archive(mode) if mode not in ("0", "1") else None


def read_track_metadata(path):
    path = Path(path)
    packed, archive = metadata_mode()
    data = archive.read(path) if archive is not None else None
    if data is None:
        data = json.loads(path.read_text(encoding="utf-8"))
        if packed:
            pack_track_metadata(data)
    return data
