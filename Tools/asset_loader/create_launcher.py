"""현재 Pico2D 환경으로 에셋 로더를 여는 Windows 바로가기를 만든다."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def create_launcher():
    if sys.platform != "win32" or importlib.util.find_spec("pico2d") is None:
        raise RuntimeError("Windows의 Pico2D 설치 환경에서 실행한다.")
    root = Path(__file__).resolve().parents[2]
    destination = root / "FDrive Asset Loader.lnk"
    python = Path(sys.executable).with_name("pythonw.exe")
    if not python.is_file():
        python = Path(sys.executable)
    environment = dict(os.environ)
    environment.update(FDRIVE_LINK=str(destination), FDRIVE_PYTHON=str(python),
                       FDRIVE_ARGUMENTS=subprocess.list2cmdline([str(root / "Tools/asset_loader/run.py"), "--debug"]),
                       FDRIVE_DIRECTORY=str(root))
    script = """
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($env:FDRIVE_LINK)
$shortcut.TargetPath = $env:FDRIVE_PYTHON
$shortcut.Arguments = $env:FDRIVE_ARGUMENTS
$shortcut.WorkingDirectory = $env:FDRIVE_DIRECTORY
$shortcut.IconLocation = $env:FDRIVE_PYTHON + ',0'
$shortcut.Description = 'FDrive Asset Loader'
$shortcut.Save()
"""
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            env=environment, capture_output=True)
    if result.returncode or not destination.is_file():
        raise RuntimeError("바로가기 생성 실패: " + result.stderr.decode("utf-8", errors="replace"))
    return destination


if __name__ == "__main__":
    print(create_launcher())
