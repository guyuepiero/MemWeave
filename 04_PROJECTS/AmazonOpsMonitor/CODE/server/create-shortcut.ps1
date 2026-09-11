# create-shortcut.ps1 - Create desktop shortcut with Amazon icon
# Encoding: UTF-8 with BOM (PowerShell reads Chinese filenames correctly)
# Paths are ABSOLUTE so this script works from any location (Desktop, server dir, etc.)
$ErrorActionPreference = 'Stop'

$server = 'C:\Users\guyuepiero\Documents\MemWeave v1.0\04_PROJECTS\AmazonOpsMonitor\CODE\server'
$pyw = Join-Path $server '.venv\Scripts\pythonw.exe'
$ico = Join-Path $server 'appicon.ico'
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) '亚马逊运营工作台.lnk'

if (-not (Test-Path $pyw)) { throw "pythonw not found: $pyw" }
if (-not (Test-Path $ico)) { throw "icon not found: $ico" }

$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = $pyw
$s.Arguments = 'tray.py'
$s.WorkingDirectory = $server
$s.IconLocation = "$ico,0"
$s.Description = 'Amazon Ops Monitor - tray'
$s.Save()

Write-Output "OK shortcut created: $lnk"
Write-Output "Icon: $ico"
