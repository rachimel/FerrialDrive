"""모션 아틀라스의 UTF-8 JSON을 한 번에 읽는다."""

from ferrial_drive.json_io import loads


def read_atlas_json(path):
    return loads(path.read_bytes())
