"""테스트 소스를 실행하거나 import하지 않고 진입 규약을 확인한다."""

import ast
from dataclasses import dataclass
from pathlib import Path
import tokenize


@dataclass(frozen=True)
class RunPreset:
    preset_id: str
    label: str
    arguments: tuple[str, ...]


def _declaration_from_tree(tree: ast.Module, name: str) -> ast.expr | None:
    value = None
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in statement.targets):
            value = statement.value
        elif (isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
              and statement.target.id == name):
            value = statement.value
    return value


def supports_mute_from_tree(tree: ast.Module) -> bool:
    value = _declaration_from_tree(tree, "UNIT_TEST_SUPPORTS_MUTE")
    if value is None:
        return False
    if not isinstance(value, ast.Constant) or type(value.value) is not bool:
        raise ValueError("UNIT_TEST_SUPPORTS_MUTE는 불리언 리터럴이어야 한다.")
    return value.value


def run_presets_from_tree(tree: ast.Module) -> tuple[RunPreset, ...]:
    """선택 실행 인자는 리터럴만 읽는다. 테스트 소스는 실행하지 않는다."""
    value = _declaration_from_tree(tree, "UNIT_TEST_PRESETS")
    if value is None:
        return ()
    try:
        rows = ast.literal_eval(value)
    except (ValueError, TypeError):
        raise ValueError("UNIT_TEST_PRESETS는 리터럴 목록이어야 한다.") from None
    if not isinstance(rows, (tuple, list)) or not 1 <= len(rows) <= 8:
        raise ValueError("실행 선택지는 1~8개여야 한다.")
    presets, identifiers = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "label", "args"}:
            raise ValueError("실행 선택지는 id·label·args 필드를 사용한다.")
        identifier, label, arguments = row["id"], row["label"], row["args"]
        if (not isinstance(identifier, str) or not identifier.strip() or identifier in identifiers
                or not isinstance(label, str) or not label.strip() or "\n" in label
                or not isinstance(arguments, (list, tuple))
                or any(not isinstance(argument, str) or "\0" in argument for argument in arguments)):
            raise ValueError("실행 선택지 ID·표시명·문자열 인자 목록이 올바르지 않다.")
        presets.append(RunPreset(identifier, label, tuple(arguments)))
        identifiers.add(identifier)
    return tuple(presets)


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
