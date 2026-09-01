@echo off
title WeChat Vault - Uninstall Auto Start
echo Removing shortcuts...

del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\WeChatVault.lnk" >nul 2>&1
del "%USERPROFILE%\Desktop\WeChatVault.lnk" >nul 2>&1

echo Done. Auto start and desktop shortcut removed.
pause
