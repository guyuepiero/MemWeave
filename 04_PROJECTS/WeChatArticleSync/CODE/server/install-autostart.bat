@echo off
title WeChat Vault - Install Auto Start
rem Creates shortcuts so the local client starts automatically at login
rem (minimized) and adds a desktop shortcut for manual start.

set HERE=%~dp0

echo Creating auto-start shortcut (login)...
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Startup') + '\WeChatVault.lnk'); $s.TargetPath = '%HERE%start.bat'; $s.WorkingDirectory = '%HERE%'; $s.WindowStyle = 7; $s.Save()"
if errorlevel 1 goto :fail

echo Creating desktop shortcut...
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\WeChatVault.lnk'); $s.TargetPath = '%HERE%start.bat'; $s.WorkingDirectory = '%HERE%'; $s.WindowStyle = 7; $s.Save()"
if errorlevel 1 goto :fail

echo.
echo Done!
echo   - Auto start at login: installed
echo   - Desktop shortcut: WeChatVault (double-click to start)
echo   - Stop the server: use stop.bat
echo.
pause
exit /b 0

:fail
echo [ERROR] Failed to create shortcuts. Run this file as normal user (no admin needed).
pause
exit /b 1
