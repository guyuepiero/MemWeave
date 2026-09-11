@echo off
rem Amazon Ops Workbench - Stop service
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
    ".venv\Scripts\python.exe" "tray.py" --stop
)
echo Service stopped (ignore if it was not running).
pause
