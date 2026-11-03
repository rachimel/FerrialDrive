"""현재 Python 환경으로 실행기 GUI를 여는 Windows 바로가기를 생성한다."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def create_launcher(destination: Path | None = None) -> Path:
    if sys.platform != "win32":
        raise OSError("Windows 바로가기 생성은 Windows에서 지원한다.")
    if importlib.util.find_spec("pico2d") is None:
        raise RuntimeError("현재 Python 환경에 Pico2D 설치가 필요하다.")
    tool_dir = Path(__file__).resolve().parent
    destination = (destination if destination is not None
                   else tool_dir / "workspace" / "Unit Test Runner.lnk").resolve()
    if destination.suffix.lower() != ".lnk":
        raise ValueError("바로가기 경로는 .lnk 파일이어야 한다.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({
        "UNIT_TEST_LINK_PATH": str(destination),
        "UNIT_TEST_LINK_PYTHON": sys.executable,
        "UNIT_TEST_LINK_ARGUMENTS": subprocess.list2cmdline([str(tool_dir / "desktop_launcher.py")]),
        "UNIT_TEST_LINK_DIRECTORY": str(tool_dir),
    })
    # 경로를 스크립트에 삽입하지 않고 환경 변수로 전달한다.
    command = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($env:UNIT_TEST_LINK_PATH)
$shortcut.TargetPath = $env:UNIT_TEST_LINK_PYTHON
$shortcut.Arguments = $env:UNIT_TEST_LINK_ARGUMENTS
$shortcut.WorkingDirectory = $env:UNIT_TEST_LINK_DIRECTORY
$shortcut.IconLocation = $env:UNIT_TEST_LINK_PYTHON + ',0'
$shortcut.WindowStyle = 1
$shortcut.Description = 'Unit Test Runner'
$shortcut.Save()
"""
    powershell = (Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell"
                  / "v1.0" / "powershell.exe")
    result = subprocess.run([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                             "-Command", command], env=environment, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError("바로가기 생성 실패:\n" + result.stderr.decode("utf-8", errors="replace"))
    if not destination.is_file():
        raise RuntimeError("바로가기 파일 생성 확인 실패")
    return destination


if __name__ == "__main__":
    print(create_launcher())
