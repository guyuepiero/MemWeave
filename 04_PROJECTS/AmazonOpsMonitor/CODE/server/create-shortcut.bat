@echo off
rem ============================================================
rem  Amazon Ops Monitor - Create Desktop Shortcut (with icon)
rem  Calls create-shortcut.ps1 (native COM).
rem ============================================================
setlocal
set HERE=%~dp0
echo Creating desktop shortcut with Amazon icon...
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%create-shortcut.ps1"
if errorlevel 1 (
  echo [ERROR] Failed to create shortcut.
  pause
  exit /b 1
)
echo.
echo Done. Check your Desktop for the icon.
timeout /t 3 >nul
exit /b 0
