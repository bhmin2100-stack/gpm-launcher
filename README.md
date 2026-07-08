# GPM Launcher

Windows launcher for the company GPM Curl applications.

## Features

- Stores configurable GPM entries with user-defined names, MDM URLs, and hotkeys.
- Supports user-configurable global hotkeys; click a hotkey field and press any modifier combination such as `Ctrl`, `Alt`, `Shift`, and `Win`.
- Creates desktop shortcuts named from the configured GPM entries, such as `NRD GPM`.
- Lets each GPM, OI, and agreement row create its own desktop shortcut from the row's `Download` action.
- Keeps the workspace session alive before the 4-hour timeout, with a refresh interval adjustable in 1-minute steps.
- Refreshes the workspace in a background headless browser attempt using the normal Edge/Chrome profile instead of a separate app profile.
- Launches GPM directly from hotkeys and desktop shortcuts without opening the workspace first.
- Remembers windows opened from registered GPM/OI/agreement entries and brings the existing window to the front instead of opening another one.
- Adds configurable OI entries with user-defined names, URLs, and hotkeys.
- Opens OI pages in browser app mode without the normal address bar or toolbar, using the normal Edge/Chrome profile for SSO.
- Adds configurable agreement links, such as NRD and NRDK agreement pages, with the same URL and hotkey workflow as OI.
- Generates per-entry shortcut icons that include the GPM/OI/agreement type and the user-defined entry name.
- Can hide to the Windows tray and restore from the tray icon.
- Uses a lightweight basic Windows GUI and has explicit buttons to register or remove Windows startup.
- Automatically extracts the `curl://launch/...` target when a workspace launch URL is pasted.

## Download

The packaged Windows builds are in:

```text
release/GPMLauncher.exe
release/GPMLauncher-windows.zip
```

For the ZIP build, extract the ZIP and run:

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

For OI entries, use a name that includes the page-identifying text shown in the window title, such as `P2L3` or `P1L7`. This helps the launcher find an already-open window instead of opening another one.

Do not commit real company workspace URLs or MDM launch URLs.
