$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

python tools\make_icon.py

python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --onedir `
  --name GPMLauncher `
  --exclude-module PySide6 `
  --exclude-module shiboken6 `
  --icon assets\gpm_launcher.ico `
  gpm_launcher.py

Write-Host ""
Write-Host "Built: $root\dist\GPMLauncher\GPMLauncher.exe"
