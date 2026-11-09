@echo off
cd /d "%~dp0\..\.."
if exist "%USERPROFILE%\miniconda3\envs\game2d\python.exe" (
    "%USERPROFILE%\miniconda3\envs\game2d\python.exe" "Tools\pose_tool\run.py" %*
) else if exist ".venv-capability-test\Scripts\python.exe" (
    ".venv-capability-test\Scripts\python.exe" "Tools\pose_tool\run.py" %*
) else (
    python "Tools\pose_tool\run.py" %*
)
if errorlevel 1 pause
