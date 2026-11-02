@echo off
cd /d "%~dp0"
start "" ".venv-capability-test\Scripts\pythonw.exe" "Tools\portrait_editor\app.py" %*
