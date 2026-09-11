@echo off
rem =====================================================
rem  WeChat Vault - Background Tray Launcher (v0806-3)
rem  Double-click: starts the server in background with a
rem  system tray icon (no console window kept open).
rem  Tray right-click -> Exit to stop the server.
rem =====================================================
cd /d "%~dp0"

rem already running? only trust LISTENING state;
rem TIME_WAIT / other leftover states must NOT be treated as "running".
netstat -ano | findstr ":21888" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Server already running in background.
    echo        Opening workbench...
    start "" "http://127.0.0.1:21888"
    exit /b 0
)

if not exist .venv\Scripts\pythonw.exe (
    echo [ERROR] venv not found. Run these first:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo Starting server in background with tray icon...
start "" ".venv\Scripts\pythonw.exe" "tray_vault.py"

echo Waiting for server to start (up to 15s)...
for /l %%i in (1,1,15) do (
    timeout /t 1 /nobreak >nul
    netstat -ano | findstr ":21888" | findstr "LISTENING" >nul 2>&1
    if not errorlevel 1 goto ready
)
echo.
echo [WARN] Server did not start within 15s. See logs\server.log for details.
pause
exit /b 1

:ready
echo [OK] Server is running: http://127.0.0.1:21888
start "" "http://127.0.0.1:21888"
exit /b 0
