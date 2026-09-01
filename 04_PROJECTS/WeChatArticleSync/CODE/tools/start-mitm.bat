@echo off
title WeChat Vault - MITM (Plan B)
rem Starts mitmproxy with the vault addon.
rem 1) Run this once (installs mitmproxy into the server venv)
rem 2) Set system proxy to 127.0.0.1:8080, trust mitmproxy CA
rem 3) Open the target account profile inside WeChat PC client
rem 4) The addon pushes the captured session to the local server

cd /d "%~dp0..\server"

if not exist .venv\Scripts\mitmdump.exe (
    echo [INFO] Installing mitmproxy into venv...
    .venv\Scripts\pip install mitmproxy
)

echo Starting mitmproxy on 127.0.0.1:8080 ...
.venv\Scripts\mitmdump.exe -s "%~dp0..\tools\mitm_addon.py" --set console_eventlog_verbosity=info
pause
