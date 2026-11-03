"""창 없이 실행 경계·부모 import 방지·보조 모듈 캐시 분리를 확인한다."""

import os
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools"))

from unit_test_runner.processes import RunningTest, prepare_test, run_file


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="runner-boundary-")
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def source(self, name, text):
        path = self.directory / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_preparation_does_not_execute_selected_file(self):
        path = self.source("읽기 전용.py", 'UNIT_TEST_ENTRYPOINT = "standalone"\n'
                           'raise RuntimeError("부모에서 실행하면 안 된다")\n')
        plan = prepare_test(path)
        self.assertIn(str(path), plan.command)
        self.assertNotIn("worker.py", " ".join(plan.command))

    def test_syntax_error_is_rejected_before_replacing_active_process(self):
        path = self.source("syntax.py", "def broken(:\n")
        with self.assertRaises(SyntaxError):
            prepare_test(path)

    def test_existing_factory_uses_compatibility_worker(self):
        path = self.source("factory.py", "def create_test():\n    pass\n")
        self.assertTrue(any(Path(part).name == "worker.py" for part in prepare_test(path).command))

    def test_each_launch_ignores_stale_helper_bytecode(self):
        helper = self.source("helper.py", 'VALUE = "OLD"\n')
        py_compile.compile(str(helper), doraise=True)
        previous_time = helper.stat()
        path = self.source("한글 공백 & !.py", 'UNIT_TEST_ENTRYPOINT = "standalone"\n'
                           'from pathlib import Path\nimport helper\n'
                           'Path(__file__).with_suffix(".result").write_text(helper.VALUE)\n')
        for value in ("NEW", "END"):
            helper.write_text(f'VALUE = "{value}"\n', encoding="utf-8")
            os.utime(helper, ns=(previous_time.st_atime_ns, previous_time.st_mtime_ns))
            self.assertEqual(run_file(path), 0)
            self.assertEqual(path.with_suffix(".result").read_text(), value)

    def test_child_failure_output_is_captured_without_blocking_on_pipe(self):
        path = self.source("failure.py", 'UNIT_TEST_ENTRYPOINT = "standalone"\n'
                           'raise RuntimeError("자식 프로세스 오류")\n')
        child = RunningTest.start(prepare_test(path))
        try:
            self.assertNotEqual(child.process.wait(timeout=10), 0)
            self.assertIn("자식 프로세스 오류", child.output_tail())
        finally:
            child.close()

    def test_ui_file_import_needs_neither_runner_nor_open_canvas(self):
        script = ('import runpy, sys\n'
                  f'runpy.run_path({str(ROOT / "tests/ui_test.py")!r}, run_name="ui_import_check")\n'
                  'assert "unit_test_runner" not in sys.modules\n'
                  'assert "pico2d" not in sys.modules\n')
        result = subprocess.run([sys.executable, "-B", "-c", script], cwd=self.directory,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_owned_child_is_reaped_and_cleanup_is_idempotent(self):
        path = self.source("long_running.py", 'UNIT_TEST_ENTRYPOINT = "standalone"\n'
                           'import time\ntime.sleep(60)\n')
        child = RunningTest.start(prepare_test(path))
        try:
            child.close()
            child.close()
            self.assertIsNotNone(child.poll())
            self.assertTrue(child.output.closed)
        finally:
            child.close()


if __name__ == "__main__":
    unittest.main()
