"""테스트 소스를 실행하거나 import하지 않고 진입 규약을 확인한다."""

import ast
from pathlib import Path
import tokenize


def read_test_source(path: Path) -> ast.Module:
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != ".py":
        raise ValueError("실행할 테스트 .py 파일이 필요하다.")
    with tokenize.open(path) as source:
        tree = ast.parse(source.read(), filename=str(path))
    # return의 최상위 사용 등 AST 파싱만으로 잡히지 않는 문법도 확인한다.
    compile(tree, str(path), "exec")
    return tree


def read_test_header(tree: ast.Module) -> tuple[str, str]:
    """파일 맨 위 설명의 첫 줄은 제목, 나머지는 짧은 소개로 읽는다."""
    header = ast.get_docstring(tree) or ""
    lines = header.strip().splitlines()
    return (lines[0].strip(), "\n".join(lines[1:]).strip()) if lines else ("", "")


def inspect_entrypoint(path: Path) -> str:
    return entrypoint_from_tree(read_test_source(path))


def entrypoint_from_tree(tree: ast.Module) -> str:
    mode = "legacy"
    factory = None
    for statement in tree.body:
        value = None
        if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "UNIT_TEST_ENTRYPOINT"
                for target in statement.targets):
            value = statement.value
        elif (isinstance(statement, ast.AnnAssign)
              and isinstance(statement.target, ast.Name)
              and statement.target.id == "UNIT_TEST_ENTRYPOINT"):
            value = statement.value
        if value is not None:
            try:
                mode = ast.literal_eval(value)
            except (ValueError, TypeError):
                raise ValueError("UNIT_TEST_ENTRYPOINT는 문자열 리터럴이어야 한다.") from None
        if isinstance(statement, ast.FunctionDef) and statement.name == "create_test":
            factory = statement
    if mode not in ("standalone", "legacy"):
        raise ValueError("UNIT_TEST_ENTRYPOINT는 standalone 또는 legacy여야 한다.")
    if mode == "legacy":
        if factory is None:
            raise ValueError("진입점 없음: standalone 선언 또는 create_test()가 필요하다.")
        arguments = factory.args
        if (len(arguments.posonlyargs) + len(arguments.args) > len(arguments.defaults)
                or any(default is None for default in arguments.kw_defaults)):
            raise ValueError("create_test()는 필수 인자 없이 호출할 수 있어야 한다.")
    return mode
