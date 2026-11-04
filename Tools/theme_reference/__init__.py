"""게임 모듈에 의존하지 않는 도구 공통 테마 기준."""

import json
from pathlib import Path


def load_theme():
    return json.loads(Path(__file__).with_name("theme.json").read_text(encoding="utf-8"))


def rgb(value):
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))
