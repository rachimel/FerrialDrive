"""명시한 테스트 .py 하나를 읽는다. 자동 탐색이나 등록 목록은 사용하지 않는다."""

import importlib.util
from pathlib import Path
import sys

from .interface import TestProgram, WindowSpec


def load_test(path: Path) -> tuple[TestProgram, WindowSpec]:
    path = path.resolve()
    if not path.is_file() or path.suffix != ".py":
        raise ValueError("실행할 테스트 .py 파일을 지정해.")
    name = "_unit_test_program"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"테스트를 불러올 수 없다: {path}")
    module = importlib.util.module_from_spec(spec)
    previous_module = sys.modules.get(name)
    previous_path = sys.path[:]
    sys.modules[name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
        factory = getattr(module, "create_test", None)
        if not callable(factory):
            raise TypeError("테스트 .py에 create_test() 함수가 필요하다.")
        program = factory()
        if not isinstance(program, TestProgram):
            raise TypeError("create_test()는 TestProgram을 반환해야 한다.")
        window = getattr(module, "WINDOW", WindowSpec())
        if not isinstance(window, WindowSpec):
            raise TypeError("WINDOW는 WindowSpec이어야 한다.")
        return program, window
    except BaseException:
        if previous_module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous_module
        raise
    finally:
        sys.path[:] = previous_path
