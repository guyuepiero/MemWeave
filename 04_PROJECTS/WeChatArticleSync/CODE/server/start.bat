@echo off
title WeChat Vault - Local Client
cd /d "%~dp0"

echo ============================================
echo   WeChat Vault local client starting...
echo.
echo       --  http://127.0.0.1:21888  --
echo.
echo   Open the address above, or wait 1 second
echo   for your browser to open automatically.
echo   Close this window to stop the server
echo ============================================
echo.

rem already running?
netstat -ano | findstr ":21888 " >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Server is already running on port 21888.
    echo.
    echo        --  http://127.0.0.1:21888  --
    echo.
    echo   Opening your browser...
    start "" "http://127.0.0.1:21888"
    echo   If nothing opened, copy the address above
    echo   into your browser manually, or use stop.bat
    echo   to stop the server first.
    echo.
    pause
    exit /b 0
)

if not exist .venv\Scripts\python.exe (
    echo [ERROR] venv not found. Run these first:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

rem tell main.py to auto-open the browser once the server is up
set WEICHAT_VAULT_OPEN_BROWSER=1
.venv\Scripts\python.exe -m app.main
pause
