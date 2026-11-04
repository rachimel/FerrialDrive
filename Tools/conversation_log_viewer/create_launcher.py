"""현재 환경의 프로젝트 루트 대화 기록 바로가기."""

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def create_launcher(destination=None):
    if sys.platform != "win32":
        raise OSError("바로가기는 Windows에서 생성한다.")
    if importlib.util.find_spec("pico2d") is None:
        raise RuntimeError("Pico2D가 설치된 Python 환경에서 실행한다.")
    tool = Path(__file__).resolve().parent
    root = tool.parents[1]
    destination = Path(destination or root / "대화 기록.lnk").resolve()
    if destination.suffix.lower() != ".lnk":
        raise ValueError("바로가기 확장자는 .lnk여야 한다.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    environment = os.environ.copy()
    environment.update({"FD_LOG_LINK": str(destination), "FD_LOG_PYTHON": str(pythonw if pythonw.is_file() else Path(sys.executable)),
                        "FD_LOG_ARGS": subprocess.list2cmdline([str(tool / "run.py")]), "FD_LOG_ROOT": str(root)})
    script = """
$ErrorActionPreference = 'Stop'
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($env:FD_LOG_LINK)
$link.TargetPath = $env:FD_LOG_PYTHON
$link.Arguments = $env:FD_LOG_ARGS
$link.WorkingDirectory = $env:FD_LOG_ROOT
$link.IconLocation = $env:FD_LOG_PYTHON + ',0'
$link.Description = 'Ferrial Drive 대화 기록'
$link.Save()
"""
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                            env=environment, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    if not destination.is_file():
        raise RuntimeError("바로가기 생성 확인 실패")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="루트 대화 기록 바로가기 생성")
    parser.add_argument("--destination", type=Path)
    print(create_launcher(parser.parse_args().destination))
