# GPM Launcher

Windows launcher for the company GPM Curl applications.

## Features

- Stores separate launch URLs for NRD, MEMORY, and NRDK.
- Supports user-configurable global hotkeys.
- Creates desktop shortcuts named `NRD GPM`, `MEM GPM`, and `NRDK GPM`.
- Keeps the workspace session alive in the background before the 4-hour timeout, with a refresh interval adjustable in 1-minute steps.
- Launches GPM directly from hotkeys and desktop shortcuts without opening the workspace first.
- Uses a lightweight basic Windows GUI and can start with Windows.
- Automatically extracts the `curl://launch/...` target when a workspace launch URL is pasted.

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
- Pillow
- PyInstaller

The GUI uses Tkinter from the Python standard library.

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
