@echo off
rem 微文收纳 · 托盘模式启动（无黑框，右下角常驻图标）
rem 右键托盘图标可：打开工作台 / 重启服务 / 退出
rem 服务日志：server.log
title WeChat Vault - Tray
cd /d "%~dp0"

rem already running? (tray or server)
netstat -ano | findstr ":21888 " >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Server is already running on port 21888.
    echo.
    echo   If the tray icon is missing, close this window
    echo   and start again to re-attach the tray icon.
    echo.
    pause
    exit /b 0
)

if not exist .venv\Scripts\pythonw.exe (
    echo [ERROR] venv not found. Run these first:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

rem start tray in background with no console window
start "" ".venv\Scripts\pythonw.exe" "tray.py"
echo.
echo   Tray icon started. Look for the icon in the system tray
echo   (bottom-right corner, may need to click ^"show hidden icons^").
echo.
echo   Close this window is safe - the service keeps running.
echo.
pause
