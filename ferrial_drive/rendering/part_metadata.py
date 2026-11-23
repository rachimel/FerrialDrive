"""런타임의 그림자 포즈와 파츠 프레임을 정밀도 손실 없이 보관한다."""

from collections.abc import Sequence
from struct import Struct, error


SHADOW_BONE_VALUES = 7
FRAME_ROW_CACHE_MASK = 31
DOUBLE = Struct("<d")
TILE_FIELDS = {
    "page": (1, "h"), "rect": (4, "h"), "frame_crop": (4, "h"), "mask_crop": (4, "h"),
    "flow_step": (2, "d"), "flow_curve": (2, "d"),
}
PART_FRAME_FIELDS = {
    "color": (1, "h"), "energy": (1, "h"), "depth": (1, "h"), "material": (1, "h"),
    "coat": (1, "h"), "forward": (1, "h"), "backward": (1, "h"),
    "center_depth": (1, "d"), "depth_extent": (2, "d"),
}


class PackedShadowPoses(Sequence):
    """동작은 연속 바이트로 보관하고 최근 두 표본만 펼쳐 둔다."""

    __slots__ = ("_data", "_format", "_samples", "_length")

    def __init__(self, poses, bone_count):
        self._format = Struct(f"<{bone_count * SHADOW_BONE_VALUES}d")
        self._length = len(poses)
        storage = bytearray(self._format.size * self._length)
        for index, pose in enumerate(poses):
            if len(pose) != bone_count or any(len(bone) != SHADOW_BONE_VALUES for bone in pose):
                raise ValueError("그림자 포즈의 본 수 또는 좌표 수가 다르다.")
            values = tuple(value for bone in pose for value in bone)
            if not all(exact_double(value) for value in values):
                raise ValueError("그림자 포즈를 배정밀도로 정확히 저장할 수 없다.")
            self._format.pack_into(storage, index * self._format.size, *values)
        self._data = bytes(storage)
        self._samples = [(-1, None), (-1, None)]

    def __len__(self):
        return self._length

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        index = checked_index(index, len(self))
        slot = index & 1
        cached_index, pose = self._samples[slot]
        if index != cached_index:
            values = self._format.unpack_from(self._data, index * self._format.size)
            pose = tuple(values[start:start + SHADOW_BONE_VALUES]
                         for start in range(0, len(values), SHADOW_BONE_VALUES))
            self._samples[slot] = index, pose
        return pose

    def __sizeof__(self):
        return super().__sizeof__() + len(self._data)


class PackedFrameRows(Sequence):
    """필드 플래그와 고정 폭 레코드로 프레임 원본을 보관한다."""

    __slots__ = ("_data", "_format", "_offsets", "_length", "_rows")

    def __init__(self, rows, schema):
        present = {key for row in rows for key in row}
        if present - schema.keys() or not present:
            raise ValueError("고정 폭으로 저장할 수 없는 프레임 필드다.")
        fields = [(key, length, code) for key, (length, code) in schema.items() if key in present]
        self._format = Struct("<H" + "".join(f"{length}{code}" for _, length, code in fields))
        self._length = len(rows)
        storage = bytearray(self._length * self._format.size)
        offsets = []
        start = 1
        for i, (key, length, _) in enumerate(fields):
            offsets.append((key, 1 << i, start, start + length))
            start += length
        self._offsets = tuple(offsets)
        for index, row in enumerate(rows):
            mask = 0
            values = []
            for i, (key, length, code) in enumerate(fields):
                if key not in row:
                    values.extend((0,) * length)
                    continue
                mask |= 1 << i
                cell = (row[key],) if length == 1 else row[key]
                if len(cell) != length or not valid_cell(cell, code):
                    raise ValueError("고정 폭으로 저장할 수 없는 프레임 값이다.")
                values.extend(cell)
            self._format.pack_into(storage, index * self._format.size, mask, *values)
        self._data = bytes(storage)
        self._rows = {}

    def __len__(self):
        return self._length

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        index = checked_index(index, len(self))
        slot = index & FRAME_ROW_CACHE_MASK
        cached_index, row = self._rows.get(slot, (-1, None))
        if cached_index == index:
            return row
        values = self._format.unpack_from(self._data, index * self._format.size)
        mask = values[0]
        row = {key: values[start] if end - start == 1 else list(values[start:end])
               for key, flag, start, end in self._offsets if mask & flag}
        self._rows[slot] = index, row
        return row

    def __sizeof__(self):
        return super().__sizeof__() + len(self._data)


def exact_double(value):
    return type(value) is float or type(value) is int and abs(value) <= 2**53


def valid_cell(cell, code):
    if code == "h":
        return all(type(value) is int for value in cell)
    return all(exact_double(value) for value in cell)


def checked_index(index, length):
    if index < 0:
        index += length
    if not 0 <= index < length:
        raise IndexError(index)
    return index


def pack_shadow_metadata(data):
    proxy = data.get("shadow_proxy")
    if not proxy:
        return
    bone_count = len(proxy["bones"])
    for clip in proxy["clips"].values():
        try:
            clip["poses"] = PackedShadowPoses(clip["poses"], bone_count)
        except (ValueError, TypeError, error, OverflowError):
            # 다른 규격의 포즈는 기존 자료 구조로 읽는다.
            continue


def packed_rows(rows, schema):
    try:
        return PackedFrameRows(rows, schema)
    except (ValueError, TypeError, error):
        return rows


def pack_direction_metadata(data):
    frames = data.get("frames", {})
    for field, rows in frames.items():
        frames[field] = packed_rows(rows, TILE_FIELDS)
    for spec in data.get("clip", {}).get("parts", {}).values():
        spec["frames"] = packed_rows(spec["frames"], PART_FRAME_FIELDS)


class PackedTrackRows(Sequence):
    """같은 좌표 구성을 갖는 추적 표본의 시간과 위치를 보관한다."""

    __slots__ = ("_data", "_format", "_length", "_fields", "_points", "_recent")

    def __init__(self, rows, fields=(), points=()):
        self._fields, self._points = tuple(fields), tuple(points)
        width = sum(length for _, length in fields) + len(points) * 3 if fields else len(rows[0])
        self._format = Struct(f"<{width}d")
        self._length = len(rows)
        storage = bytearray(self._format.size * self._length)
        for index, row in enumerate(rows):
            values = self._flatten(row) if fields else row
            if len(values) != width or not all(exact_double(value) for value in values):
                raise ValueError("추적 좌표의 폭 또는 수치가 다르다.")
            self._format.pack_into(storage, index * self._format.size, *values)
        self._data = bytes(storage)
        self._recent = [(-1, None), (-1, None)]

    def _flatten(self, row):
        expected = [name for name, _ in self._fields]
        if self._points:
            expected.append("points")
        if list(row) != expected or (self._points and list(row["points"]) != list(self._points)):
            raise ValueError("추적 표본마다 좌표 이름이나 순서가 다르다.")
        values = []
        for name, length in self._fields:
            cell = (row[name],) if length == 1 else row[name]
            if len(cell) != length:
                raise ValueError("추적 필드의 수치 개수가 다르다.")
            values.extend(cell)
        for point in self._points:
            xyz = row["points"][point]
            if len(xyz) != 3:
                raise ValueError("부착점 좌표는 세 축이 필요하다.")
            values.extend(xyz)
        return values

    def time_at(self, index):
        return DOUBLE.unpack_from(self._data, index * self._format.size)[0]

    def __len__(self):
        return self._length

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        index = checked_index(index, len(self))
        slot = index & 1
        cached_index, row = self._recent[slot]
        if cached_index == index:
            return row
        values = self._format.unpack_from(self._data, index * self._format.size)
        row = self._mapping(values) if self._fields else values
        self._recent[slot] = index, row
        return row

    def _mapping(self, values):
        result = {}
        start = 0
        for name, length in self._fields:
            result[name] = values[start] if length == 1 else values[start:start + length]
            start += length
        if self._points:
            result["points"] = {name: values[start + 3 * i:start + 3 * i + 3]
                                for i, name in enumerate(self._points)}
        return result

    def __sizeof__(self):
        return super().__sizeof__() + len(self._data)


def packed_track(rows, fields=(), points=()):
    if not rows:
        return rows
    try:
        return PackedTrackRows(rows, fields, points)
    except (ValueError, TypeError, KeyError, error):
        return rows


def pack_track_metadata(data):
    if data.get("type") == "upper_lower_pose_table":
        for track in data.get("attachments", {}).values():
            rows = track["samples"]
            if rows and rows[0]["points"]:
                fields = (("seconds", 1), ("root", 3), ("waist", 3))
                track["samples"] = packed_track(rows, fields, rows[0]["points"])
    elif data.get("space") == "render_pixel_offset_from_root_top_left":
        for track in data["clips"].values():
            rows = track["samples"]
            if rows:
                track["samples"] = packed_track(rows, tuple((name, 2) for name in rows[0]))
    elif data.get("space") == "root_relative_top_left_px":
        for name, rows in data["tracks"].items():
            data["tracks"][name] = packed_track(rows)
    elif data.get("type") in ("sword_trail_sample", "sword_blade_projection"):
        fields = (("time_seconds", 1), ("root", 2), ("tip", 2))
        for name, rows in data["clips"].items():
            data["clips"][name] = packed_track(rows, fields)
