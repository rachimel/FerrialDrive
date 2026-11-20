"""모션 아틀라스의 UTF-8 JSON을 한 번에 읽는다."""

try:
    from orjson import loads
except ModuleNotFoundError as error:
    if error.name != "orjson":
        raise
    from json import loads


def read_atlas_json(path):
    return loads(path.read_bytes())
