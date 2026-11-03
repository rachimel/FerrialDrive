"""테스트 코드를 부모에 import하지 않는 실행 계획·프로세스 수명 관리."""

import ast
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tokenize
from uuid import uuid4


@dataclass(frozen=True)
class LaunchPlan:
    path: Path
    command: tuple[str, ...]


def prepare_test(path: Path, frame_limit=None) -> LaunchPlan:
    path = Path(path).resolve()
    if not path.is_file() or path.suffix.lower() != ".py":
        raise ValueError("실행할 테스트 .py 파일이 필요하다.")
    if frame_limit is not None and (not isinstance(frame_limit, int) or frame_limit <= 0):
        raise ValueError("프레임 제한은 양수 정수여야 한다.")
    with tokenize.open(path) as source:
        tree = ast.parse(source.read(), filename=str(path))
    mode = "legacy"
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "UNIT_TEST_ENTRYPOINT"
                for target in statement.targets):
            mode = ast.literal_eval(statement.value)
    if mode not in ("standalone", "legacy"):
        raise ValueError("UNIT_TEST_ENTRYPOINT는 standalone 또는 legacy여야 한다.")
    # 프로세스마다 다른 캐시 경로를 쓰고 -B로 쓰기를 막아 기존 pyc도 읽지 않는다.
    cache_prefix = Path(tempfile.gettempdir()) / f"unit-test-cache-{uuid4().hex}"
    command = [sys.executable, "-B", "-X", f"pycache_prefix={cache_prefix}"]
    if mode == "standalone":
        command.append(str(path))
    else:
        command.extend((str(Path(__file__).with_name("worker.py")), str(path)))
    if frame_limit is not None:
        command.extend(("--frames", str(frame_limit)))
    return LaunchPlan(path, tuple(command))


def child_environment():
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


class RunningTest:
    def __init__(self, process, output):
        self.process = process
        self.output = output
        self.closed = False

    @classmethod
    def start(cls, plan: LaunchPlan):
        output = tempfile.TemporaryFile(mode="w+b")
        try:
            process = subprocess.Popen(
                list(plan.command), cwd=plan.path.parent, env=child_environment(),
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), shell=False)
        except BaseException:
            output.close()
            raise
        return cls(process, output)

    def poll(self):
        return self.process.poll()

    def output_tail(self):
        self.output.seek(0, os.SEEK_END)
        length = self.output.tell()
        self.output.seek(max(0, length - 8192))
        return self.output.read().decode("utf-8", errors="replace").strip()

    def close(self):
        if self.closed:
            return
        if self.process.poll() is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.output.close()
        self.closed = True


def run_file(path: Path, frame_limit=None) -> int:
    plan = prepare_test(path, frame_limit)
    # CLI도 별도 프로세스를 사용하며 예외·중단 시 소유한 자식만 정리한다.
    with subprocess.Popen(list(plan.command), cwd=plan.path.parent,
                          env=child_environment(), shell=False) as process:
        try:
            return process.wait()
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            raise
