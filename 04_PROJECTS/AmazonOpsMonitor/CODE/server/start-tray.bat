@echo off
rem =====================================================
rem  Amazon Ops Workbench - Tray Launcher
rem  Double-click: start background service + tray icon,
rem  auto-open workbench in browser (no console window).
rem  Tray right-click -> Open / Restart / Exit.
rem =====================================================
cd /d "%~dp0"

rem already running?
netstat -ano | findstr ":21889 " >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Service already running. Opening workbench...
    start "" "http://127.0.0.1:21889"
    exit /b 0
)

if not exist .venv\Scripts\pythonw.exe (
    echo [ERROR] venv not found. Run:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo Starting service in background with tray icon...
echo Closing this window is safe. Use tray icon to manage.
start "" ".venv\Scripts\pythonw.exe" "tray.py"
exit /b 0
