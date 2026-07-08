$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$release = Join-Path $root 'release'
New-Item -ItemType Directory -Force -Path $release | Out-Null

python tools\make_icon.py

python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --onedir `
  --name GPMLauncher `
  --exclude-module PySide6 `
  --exclude-module shiboken6 `
  --add-data "assets\gpm_launcher.ico;assets" `
  --add-data "assets\oi_launcher.ico;assets" `
  --icon assets\gpm_launcher.ico `
  gpm_launcher.py

python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --onefile `
  --name GPMLauncher `
  --exclude-module PySide6 `
  --exclude-module shiboken6 `
  --add-data "assets\gpm_launcher.ico;assets" `
  --add-data "assets\oi_launcher.ico;assets" `
  --icon assets\gpm_launcher.ico `
  gpm_launcher.py

$zip = Join-Path $release 'GPMLauncher-windows.zip'
if (Test-Path -LiteralPath $zip) {
  Remove-Item -LiteralPath $zip -Force
}
Compress-Archive -Path (Join-Path $root 'dist\GPMLauncher\*') -DestinationPath $zip -CompressionLevel Optimal

$oneFile = Join-Path $release 'GPMLauncher.exe'
Copy-Item -LiteralPath (Join-Path $root 'dist\GPMLauncher.exe') -Destination $oneFile -Force

Write-Host ""
Write-Host "Built: $root\dist\GPMLauncher\GPMLauncher.exe"
Write-Host "Packaged: $zip"
Write-Host "One-file EXE: $oneFile"
