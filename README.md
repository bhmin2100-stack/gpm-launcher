# GPM Launcher

Windows launcher for the company GPM Curl applications.

## Features

- Stores separate launch URLs for NRD, MEMORY, and NRDK.
- Supports user-configurable global hotkeys.
- Creates desktop shortcuts named `NRD GPM`, `MEM GPM`, and `NRDK GPM`.
- Keeps the workspace session alive in the background before the 4-hour timeout.
- Runs from the Windows system tray and can start with Windows.

## Download

The packaged Windows build is in:

```text
release/GPMLauncher-windows.zip
```

Extract the ZIP and run:

```text
GPMLauncher.exe
```

## Build

Requirements:

- Windows
- Python 3.11+
- PySide6
- Pillow
- PyInstaller

Build command:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_gpm_launcher.ps1
```

The build output is written to:

```text
dist/GPMLauncher/GPMLauncher.exe
```

## Configuration

The app stores user settings under:

```text
%APPDATA%\GPM Launcher\config.json
```

Do not commit real company workspace URLs or MDM launch URLs.
