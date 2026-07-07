# GPM Launcher

Windows launcher for the company GPM Curl applications.

## Features

- Stores separate launch URLs for NRD, MEMORY, and NRDK.
- Supports user-configurable global hotkeys. Defaults are `Ctrl+Alt+Shift+N`, `Ctrl+Alt+Shift+M`, and `Ctrl+Alt+Shift+K`.
- Creates desktop shortcuts named `NRD GPM`, `MEM GPM`, and `NRDK GPM`.
- Keeps the workspace session alive before the 4-hour timeout, with a refresh interval adjustable in 1-minute steps.
- Opens the workspace refresh window briefly and closes it automatically after the configured number of seconds.
- Launches GPM directly from hotkeys and desktop shortcuts without opening the workspace first.
- Adds configurable OI entries with user-defined names, URLs, and hotkeys.
- Opens OI pages in browser app mode without the normal address bar or toolbar.
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
