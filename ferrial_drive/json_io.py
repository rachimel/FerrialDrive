"""아틀라스와 실행 설정에 사용하는 UTF-8 JSON 로더."""

from codecs import BOM_UTF8

try:
    from orjson import loads
except ModuleNotFoundError as error:
    if error.name != "orjson":
        raise
    from json import loads


def read_json(path):
    return loads(path.read_bytes().removeprefix(BOM_UTF8))
