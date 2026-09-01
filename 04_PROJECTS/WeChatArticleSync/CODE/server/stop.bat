@echo off
title WeChat Vault - Stop
echo Stopping WeChat Vault server...
taskkill /F /FI "WINDOWTITLE eq WeChat Vault*" >nul 2>&1
echo Done. (If nothing was running, ignore the message above.)
pause
