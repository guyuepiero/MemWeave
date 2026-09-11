@echo off
rem =====================================================
rem  Amazon Ops Workbench - Console Debug Mode
rem  Keeps log window open; close window to stop.
rem =====================================================
title Amazon Ops Workbench - Console
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo [ERROR] venv not found. Run:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo Starting console mode... browser will open automatically.
echo Close this window to stop the service.
".venv\Scripts\python.exe" -m app.main
pause
