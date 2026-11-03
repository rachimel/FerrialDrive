"""아이콘 실행 경로의 인자 전달·오류 유지·Windows 바로가기를 확인한다."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

FIXTURE_SOURCE = '''from pathlib import Path
from unit_test_runner import Stop, TestProgram

class ImmediateExit(TestProgram):
    def update(self, delta_seconds):
        return Stop()

    def draw(self):
        pass

def create_test():
    Path(__file__).with_suffix(".loaded").write_text(Path(__file__).name, encoding="utf-8")
    return ImmediateExit()
'''


@unittest.skipUnless(sys.platform == "win32", "Windows 바로가기 검사")
class LauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output_root = (ROOT / "output/runner_launcher_verification").resolve()
        cls.output_root.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=cls.output_root, prefix="launch_")
        cls.directory = Path(cls.temporary.name).resolve()
        if not cls.directory.is_relative_to(cls.output_root):
            raise AssertionError("임시 검사 경로가 출력 폴더 밖이다.")
        cls.tool_dir = cls.directory / "툴 공백 & ! ' 100%" / "unit_test_runner"
        shutil.copytree(ROOT / "Tools/unit_test_runner", cls.tool_dir,
                        ignore=shutil.ignore_patterns("workspace", "__pycache__"))
        cls.launcher = cls.tool_dir / "desktop_launcher.py"
        cls.environment = os.environ.copy()
        cls.environment.update({"PYTHONUTF8": "1", "SDL_VIDEODRIVER": "dummy",
                                "SDL_AUDIODRIVER": "dummy"})
        cls.powershell = (Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell"
                          / "v1.0" / "powershell.exe")

    @classmethod
    def tearDownClass(cls):
        if not cls.directory.is_relative_to(cls.output_root):
            raise AssertionError("정리 대상이 검사 출력 폴더 밖이다.")
        cls.temporary.cleanup()

    def fixture(self, name):
        path = self.directory / name
        path.write_text(FIXTURE_SOURCE, encoding="utf-8")
        return path

    def invoke(self, *args):
        return subprocess.run([sys.executable, str(self.launcher), *(str(arg) for arg in args)],
                              cwd=self.directory, env=self.environment, input="\n",
                              capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_unicode_spaces_and_shell_characters_reach_same_loader(self):
        path = self.fixture("한글 공백 & 느낌! ' 100%.py")
        result = self.invoke(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.with_suffix(".loaded").read_text(encoding="utf-8"), path.name)
        self.assertNotIn("종료: Enter", result.stdout)

    def test_missing_file_retains_error_and_failure_code(self):
        result = self.invoke(self.directory / "missing.py")
        self.assertEqual(result.returncode, 1)
        self.assertIn("테스트 .py 파일이 필요하다", result.stderr)
        self.assertIn("종료: Enter", result.stdout)

    def test_no_file_shows_usage_and_waits(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage:", result.stderr)
        self.assertIn("종료: Enter", result.stdout)

    def test_multiple_files_are_rejected_before_loading(self):
        first = self.fixture("multiple first.py")
        second = self.fixture("multiple second.py")
        result = self.invoke(first, second)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(first.with_suffix(".loaded").exists())
        self.assertFalse(second.with_suffix(".loaded").exists())

    def test_invalid_factory_reports_contract_error(self):
        path = self.directory / "invalid_factory.py"
        path.write_text("def create_test():\n    return object()\n", encoding="utf-8")
        result = self.invoke(path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("create_test()는 TestProgram", result.stderr)
        self.assertIn("종료: Enter", result.stdout)

    def test_existing_cli_options_are_forwarded(self):
        path = self.fixture("options.py")
        result = self.invoke(path, "--frames", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(path.with_suffix(".loaded").exists())

    def test_help_exits_without_waiting(self):
        result = self.invoke("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("test_file", result.stdout)
        self.assertNotIn("종료: Enter", result.stdout)

    def test_shortcut_target_and_native_shell_argument_delivery(self):
        creation = subprocess.run([sys.executable, str(self.tool_dir / "create_launcher.py")],
                                  cwd=self.directory, env=self.environment, capture_output=True,
                                  text=True, encoding="utf-8", timeout=30)
        self.assertEqual(creation.returncode, 0, creation.stderr)
        shortcut = self.tool_dir / "workspace/Unit Test Runner.lnk"
        self.assertTrue(shortcut.is_file())
        path = self.fixture("바로가기 공백 & 느낌! ' 100%.py")
        environment = self.environment.copy()
        environment.update({"UNIT_TEST_LINK_PATH": str(shortcut), "UNIT_TEST_INPUT_PATH": str(path)})
        script = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($env:UNIT_TEST_LINK_PATH)
@{target=$link.TargetPath; arguments=$link.Arguments; directory=$link.WorkingDirectory} | ConvertTo-Json -Compress
$process = Start-Process -FilePath $env:UNIT_TEST_LINK_PATH -ArgumentList ('"' + $env:UNIT_TEST_INPUT_PATH + '"') -WindowStyle Hidden -Wait -PassThru
exit $process.ExitCode
"""
        result = subprocess.run([str(self.powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                                 "-Command", script], cwd=self.directory, env=environment,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        metadata = json.loads(result.stdout.splitlines()[0])
        self.assertEqual(Path(metadata["target"]), Path(sys.executable))
        self.assertEqual(metadata["arguments"], subprocess.list2cmdline([str(self.launcher)]))
        self.assertEqual(Path(metadata["directory"]), self.tool_dir)
        self.assertEqual(path.with_suffix(".loaded").read_text(encoding="utf-8"), path.name)


if __name__ == "__main__":
    unittest.main()
