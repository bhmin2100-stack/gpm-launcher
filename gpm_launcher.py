import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import parse_qs, unquote, urlparse
import winreg


APP_NAME = "GPM Launcher"
APP_REG_NAME = "GPMLauncher"
CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "GPM Launcher"
CONFIG_PATH = CONFIG_DIR / "config.json"
WINDOW_CACHE_PATH = CONFIG_DIR / "window-cache.json"
LEGACY_CONFIG_PATH = Path(__file__).resolve().parent / "gpm-launcher.config.json"
HOTKEY_BASE_ID = 0x4700
OI_HOTKEY_BASE_ID = 0x4800
AGREEMENT_HOTKEY_BASE_ID = 0x4900
WM_HOTKEY = 0x0312
WM_COMMAND = 0x0111
WM_NULL = 0x0000
WM_QUIT = 0x0012
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
CREATE_NO_WINDOW = 0x08000000
SW_SHOWNORMAL = 1
SW_SHOWMINNOACTIVE = 7
SW_MAXIMIZE = 3
SW_RESTORE = 9
GWL_WNDPROC = -4
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040
MF_STRING = 0x00000000
TPM_RIGHTBUTTON = 0x00000002
ID_TRAY_SHOW = 1001
ID_TRAY_EXIT = 1002

ENVIRONMENTS = [
    {"key": "NRD", "label": "NRD", "shortcut": "NRD GPM"},
    {"key": "MEMORY", "label": "MEMORY", "shortcut": "MEM GPM"},
    {"key": "NRDK", "label": "NRDK", "shortcut": "NRDK GPM"},
]

DEFAULT_HOTKEYS = {
    "NRD": "",
    "MEMORY": "",
    "NRDK": "",
}

DEFAULT_OI_ENTRIES = [
    {"name": "NRD", "url": "", "hotkey": ""},
]

DEFAULT_AGREEMENT_ENTRIES = [
    {"name": "NRD", "url": "", "hotkey": ""},
    {"name": "NRDK", "url": "", "hotkey": ""},
]
HOTKEY_CAPTURE_PROMPT = "키를 누르세요"

DEFAULT_GPM_ENTRIES = [
    {"name": env["label"], "url": "", "hotkey": DEFAULT_HOTKEYS[env["key"]]}
    for env in ENVIRONMENTS
]
WINDOW_HANDLE_CACHE: dict[str, int] = {}


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
    ]


LONG_PTR = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
LRESULT = LONG_PTR
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

if ctypes.sizeof(ctypes.c_void_p) == 8:
    GetWindowLongPtrW = user32.GetWindowLongPtrW
    SetWindowLongPtrW = user32.SetWindowLongPtrW
else:
    GetWindowLongPtrW = user32.GetWindowLongW
    SetWindowLongPtrW = user32.SetWindowLongW

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
GetWindowLongPtrW.restype = LONG_PTR
SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
SetWindowLongPtrW.restype = LONG_PTR
user32.CallWindowProcW.argtypes = [LONG_PTR, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CallWindowProcW.restype = LRESULT
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.DestroyIcon.restype = wintypes.BOOL
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.AppendMenuW.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
user32.TrackPopupMenu.restype = wintypes.BOOL
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.DestroyMenu.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
shell32.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
shell32.ShellExecuteW.restype = ctypes.c_void_p
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return app_base_dir()


def default_config() -> dict:
    return {
        "workspace_url": "",
        "browser": "default",
        "warmup_seconds": 7,
        "workspace_close_seconds": 8,
        "refresh_minutes": 210,
        "refresh_enabled": True,
        "start_with_windows": True,
        "gpm_entries": [entry.copy() for entry in DEFAULT_GPM_ENTRIES],
        "oi_entries": [entry.copy() for entry in DEFAULT_OI_ENTRIES],
        "agreement_entries": [entry.copy() for entry in DEFAULT_AGREEMENT_ENTRIES],
    }


def merge_config(target: dict, saved: dict) -> None:
    for key in ("workspace_url", "browser", "warmup_seconds", "workspace_close_seconds", "refresh_minutes", "refresh_enabled", "start_with_windows"):
        if key in saved:
            target[key] = saved[key]

    gpm_loaded = False
    saved_gpm = saved.get("gpm_entries", [])
    if "gpm_entries" in saved and isinstance(saved_gpm, list):
        entries = []
        for item in saved_gpm:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            url = str(item.get("url", "")).strip()
            hotkey = str(item.get("hotkey", "")).strip()
            if name or url or hotkey:
                entries.append({"name": name, "url": url, "hotkey": hotkey})
        target["gpm_entries"] = entries
        gpm_loaded = True
    if not gpm_loaded:
        saved_mdm = saved.get("mdm", {})
        if isinstance(saved_mdm, dict):
            migrated = []
            for env in ENVIRONMENTS:
                env_key = env["key"]
                entry = {"name": env["label"], "url": "", "hotkey": DEFAULT_HOTKEYS[env_key]}
                if isinstance(saved_mdm.get(env_key), dict):
                    entry["url"] = str(saved_mdm[env_key].get("url", "") or "")
                    entry["hotkey"] = str(saved_mdm[env_key].get("hotkey", DEFAULT_HOTKEYS[env_key]) or "")
                migrated.append(entry)
            target["gpm_entries"] = migrated

    saved_oi = saved.get("oi_entries", [])
    if "oi_entries" in saved and isinstance(saved_oi, list):
        entries = []
        for item in saved_oi:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            url = str(item.get("url", "")).strip()
            hotkey = str(item.get("hotkey", "")).strip()
            if name or url or hotkey:
                entries.append({"name": name, "url": url, "hotkey": hotkey})
        target["oi_entries"] = entries

    saved_agreement = saved.get("agreement_entries", [])
    if "agreement_entries" in saved and isinstance(saved_agreement, list):
        entries = []
        for item in saved_agreement:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            url = str(item.get("url", "")).strip()
            hotkey = str(item.get("hotkey", "")).strip()
            if name or url or hotkey:
                entries.append({"name": name, "url": url, "hotkey": hotkey})
        target["agreement_entries"] = entries


def load_config() -> dict:
    config = default_config()
    if CONFIG_PATH.exists():
        try:
            merge_config(config, json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    elif LEGACY_CONFIG_PATH.exists():
        try:
            legacy = json.loads(LEGACY_CONFIG_PATH.read_text(encoding="utf-8-sig"))
            config["workspace_url"] = legacy.get("WorkspaceUrl", "") or ""
            config["browser"] = (legacy.get("Browser", "") or "default").lower()
            config["warmup_seconds"] = int(legacy.get("WarmupSeconds", 7) or 7)
            legacy_curl = normalize_mdm_url(legacy.get("CurlLaunchUrl", "") or "")
            if legacy_curl:
                config["gpm_entries"][0]["url"] = legacy_curl
        except Exception:
            pass
    return config


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_mdm_url(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    candidates = [text, unquote(text)]
    for candidate in candidates:
        if candidate.lower().startswith("curl://launch/"):
            return candidate.strip()

    for candidate in candidates:
        try:
            parsed = urlparse(candidate)
            query = parse_qs(parsed.query)
        except Exception:
            query = {}
        for key in ("next", "url", "target"):
            values = query.get(key)
            if values:
                nested = normalize_mdm_url(values[0])
                if nested.lower().startswith("curl://launch/"):
                    return nested

    for candidate in candidates:
        match = re.search(r"curl://launch/[^\s\"'<>]+", candidate, flags=re.IGNORECASE)
        if match:
            found = match.group(0)
            amp = found.find("&")
            if amp >= 0:
                found = found[:amp]
            return found.strip()

    lowered = text.lower()
    if lowered.startswith(("http://", "https://")) and lowered.endswith((".dcurl", ".curl")):
        return "curl://launch/" + text

    return text


def shell_open(target: str, show_command: int = SW_SHOWNORMAL) -> None:
    result = shell32.ShellExecuteW(None, "open", target, None, None, show_command)
    value = int(result or 0)
    if value <= 32:
        raise OSError(f"ShellExecute failed ({value}): {target}")


def browser_candidates(browser: str) -> list[str]:
    browser = (browser or "default").lower()
    if browser == "edge":
        return [
            rf"{os.environ.get('ProgramFiles(x86)', '')}\Microsoft\Edge\Application\msedge.exe",
            rf"{os.environ.get('ProgramFiles', '')}\Microsoft\Edge\Application\msedge.exe",
            rf"{os.environ.get('LOCALAPPDATA', '')}\Microsoft\Edge\Application\msedge.exe",
        ]
    if browser == "chrome":
        return [
            rf"{os.environ.get('ProgramFiles', '')}\Google\Chrome\Application\chrome.exe",
            rf"{os.environ.get('ProgramFiles(x86)', '')}\Google\Chrome\Application\chrome.exe",
            rf"{os.environ.get('LOCALAPPDATA', '')}\Google\Chrome\Application\chrome.exe",
        ]
    return browser_candidates("edge") + browser_candidates("chrome")


def resolve_browser_path(browser: str) -> str | None:
    candidates = browser_candidates(browser)

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def close_process_tree_later(process: subprocess.Popen, seconds: int) -> None:
    def close_process_tree() -> None:
        if process.poll() is not None:
            return
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )

    timer = threading.Timer(max(1, seconds), close_process_tree)
    timer.daemon = True
    timer.start()


def refresh_workspace_background(config: dict, timeout_seconds: int) -> bool:
    url = (config.get("workspace_url") or "").strip()
    if not url:
        return False

    browser_path = resolve_browser_path(config.get("browser") or "default")
    if not browser_path:
        return False

    args = [
        "--headless=new",
        "--disable-gpu",
        "--dump-dom",
        "--no-first-run",
        "--disable-default-browser-check",
        url,
    ]
    try:
        result = subprocess.run(
            [browser_path, *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            timeout=max(5, int(timeout_seconds or 8)),
        )
    except subprocess.TimeoutExpired:
        return True
    return result.returncode == 0


def open_workspace(config: dict, minimized: bool = True, auto_close_seconds: int | None = None) -> bool:
    url = (config.get("workspace_url") or "").strip()
    if not url:
        return False

    if auto_close_seconds and auto_close_seconds > 0:
        return refresh_workspace_background(config, auto_close_seconds)

    browser_path = resolve_browser_path(config.get("browser") or "default")
    if browser_path:
        args = ["--new-window", url]
        if minimized:
            args.append("--start-minimized")
        subprocess.Popen([browser_path, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        return True

    shell_open(url, SW_SHOWMINNOACTIVE if minimized else SW_SHOWNORMAL)
    return True


def launch_mdm_url(url: str) -> None:
    normalized = normalize_mdm_url(url)
    if not normalized:
        raise ValueError("MDM 주소가 비어 있습니다.")
    shell_open(normalized, SW_SHOWNORMAL)


def normalized_entry_url(kind: str, entry: dict) -> str:
    if kind == "gpm":
        return normalize_mdm_url(entry.get("url", ""))
    return normalize_web_url(entry.get("url", ""))


def kind_display_name(kind: str) -> str:
    return {"gpm": "GPM", "oi": "OI", "agreement": "합의"}.get(kind, kind.upper())


def window_cache_key(kind: str, entry: dict, index: int) -> str:
    name = safe_name(entry.get("name", ""), f"{kind.upper()} {index + 1}")
    identity = f"{kind}|{name}|{normalized_entry_url(kind, entry)}"
    digest = hashlib.sha1(identity.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{kind}:{slug_name(name, kind)}:{digest}"


def load_window_handle_cache() -> None:
    if not WINDOW_CACHE_PATH.exists():
        return
    try:
        data = json.loads(WINDOW_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        try:
            WINDOW_HANDLE_CACHE[str(key)] = int(value)
        except (TypeError, ValueError):
            continue


def save_window_handle_cache() -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        WINDOW_CACHE_PATH.write_text(json.dumps(WINDOW_HANDLE_CACHE, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def cache_entry_window(kind: str, entry: dict, index: int, hwnd: int) -> None:
    load_window_handle_cache()
    WINDOW_HANDLE_CACHE[window_cache_key(kind, entry, index)] = int(hwnd)
    save_window_handle_cache()


def get_window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, length + 1)
    return buffer.value.strip()


def enumerate_visible_windows() -> list[dict]:
    windows: list[dict] = []

    @WNDENUMPROC
    def callback(hwnd, _lparam):
        hwnd_int = int(hwnd)
        if not user32.IsWindowVisible(hwnd):
            return True
        title = get_window_text(hwnd_int)
        if not title or title == APP_NAME:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        windows.append({"hwnd": hwnd_int, "title": title, "pid": int(pid.value)})
        return True

    user32.EnumWindows(callback, 0)
    return windows


def visible_window_handles() -> set[int]:
    return {window["hwnd"] for window in enumerate_visible_windows()}


def focus_window(hwnd: int, maximize: bool = True) -> bool:
    handle = wintypes.HWND(hwnd)
    if not user32.IsWindow(handle):
        return False
    if maximize:
        user32.ShowWindow(handle, SW_MAXIMIZE)
    elif user32.IsIconic(handle):
        user32.ShowWindow(handle, SW_RESTORE)
    else:
        user32.ShowWindow(handle, SW_SHOWNORMAL)
    user32.SetForegroundWindow(handle)
    return True


def focus_cached_entry_window(kind: str, entry: dict, index: int) -> bool:
    load_window_handle_cache()
    key = window_cache_key(kind, entry, index)
    hwnd = WINDOW_HANDLE_CACHE.get(key)
    if not hwnd:
        return False
    if not cached_window_matches_entry(hwnd, kind, entry, index):
        WINDOW_HANDLE_CACHE.pop(key, None)
        save_window_handle_cache()
        return False
    if focus_window(hwnd):
        return True
    WINDOW_HANDLE_CACHE.pop(key, None)
    save_window_handle_cache()
    return False


def cached_window_matches_entry(hwnd: int, kind: str, entry: dict, index: int) -> bool:
    handle = wintypes.HWND(hwnd)
    if not user32.IsWindow(handle) or not user32.IsWindowVisible(handle):
        return False
    title = get_window_text(hwnd)
    if not title:
        return False
    if kind in {"oi", "agreement"}:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        command_line = get_process_command_lines({int(pid.value)}).get(int(pid.value), "")
        return command_line_matches_web_entry(command_line, entry) or title_matches_entry(title, entry, kind, index)
    return title_matches_entry(title, entry, kind, index)


def title_matches_entry(title: str, entry: dict, kind: str, index: int) -> bool:
    lowered = title.lower()
    if lowered == APP_NAME.lower() or "gpm launcher" in lowered:
        return False
    name = safe_name(entry.get("name", ""), f"{kind.upper()} {index + 1}").lower()
    if kind == "oi":
        return bool(name and len(name) >= 2 and name in lowered and title_has_oi_marker(lowered) and not title_has_gpm_marker(lowered))
    if kind == "agreement":
        return bool(name and len(name) >= 2 and name in lowered and title_has_agreement_marker(lowered) and not title_has_gpm_marker(lowered) and not title_has_oi_marker(lowered))
    if kind == "gpm":
        return bool(name and len(name) >= 2 and name in lowered and title_has_gpm_marker(lowered) and not title_has_oi_marker(lowered))
    return False


def title_has_gpm_marker(title: str) -> bool:
    return bool(re.search(r"\bgpm\b", title, flags=re.IGNORECASE))


def title_has_oi_marker(title: str) -> bool:
    return bool(re.search(r"\bo\s*/\s*i\b|\boi\b", title, flags=re.IGNORECASE))


def title_has_agreement_marker(title: str) -> bool:
    return "합의" in title or bool(re.search(r"\bagreement\b", title, flags=re.IGNORECASE))


def get_process_command_lines(pids: set[int]) -> dict[int, str]:
    if not pids:
        return {}
    ids = ",".join(str(pid) for pid in sorted(pids) if pid > 0)
    if not ids:
        return {}
    script = (
        f"$ids = @({ids}); "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $ids -contains $_.ProcessId } | "
        "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=CREATE_NO_WINDOW,
            timeout=3,
        )
    except Exception:
        return {}
    text = (result.stdout or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        data = [data]
    command_lines: dict[int, str] = {}
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                pid = int(item.get("ProcessId"))
            except (TypeError, ValueError):
                continue
            command_lines[pid] = str(item.get("CommandLine") or "")
    return command_lines


def command_line_matches_web_entry(command_line: str, entry: dict) -> bool:
    url = normalize_web_url(entry.get("url", ""))
    if not url:
        return False
    command = unquote(command_line or "").lower()
    if "--app" not in command:
        return False
    lowered_url = unquote(url).lower()
    if lowered_url and lowered_url in command:
        return True
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    return bool(host and host in command)


def focus_existing_entry_window(kind: str, entry: dict, index: int, config: dict | None = None) -> bool:
    if focus_cached_entry_window(kind, entry, index):
        return True

    windows = enumerate_visible_windows()
    if kind in {"oi", "agreement"}:
        command_lines = get_process_command_lines({window["pid"] for window in windows})
        for window in windows:
            if command_line_matches_web_entry(command_lines.get(window["pid"], ""), entry):
                cache_entry_window(kind, entry, index, window["hwnd"])
                return focus_window(window["hwnd"])

    for window in windows:
        if title_matches_entry(window["title"], entry, kind, index):
            cache_entry_window(kind, entry, index, window["hwnd"])
            return focus_window(window["hwnd"])

    return False


def pick_new_entry_window(kind: str, entry: dict, before_handles: set[int]) -> dict | None:
    windows = [window for window in enumerate_visible_windows() if window["hwnd"] not in before_handles]
    if not windows:
        return None

    if kind in {"oi", "agreement"}:
        command_lines = get_process_command_lines({window["pid"] for window in windows})
        for window in windows:
            if command_line_matches_web_entry(command_lines.get(window["pid"], ""), entry):
                return window

    for window in windows:
        if title_matches_entry(window["title"], entry, kind, 0):
            return window

    system_fragments = ("windows 입력 환경", "명령 도구 모음", "software update", "소프트웨어 업데이트")
    for window in reversed(windows):
        title = window["title"].lower()
        if any(fragment in title for fragment in system_fragments):
            continue
        return window
    return windows[-1]


def remember_new_entry_window(kind: str, entry: dict, index: int, before_handles: set[int], timeout_seconds: float = 10.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        window = pick_new_entry_window(kind, entry, before_handles)
        if window:
            cache_entry_window(kind, entry, index, window["hwnd"])
            focus_window(window["hwnd"], maximize=True)
            return
        time.sleep(0.4)


def remember_new_entry_window_async(kind: str, entry: dict, index: int, before_handles: set[int]) -> None:
    thread = threading.Thread(
        target=remember_new_entry_window,
        args=(kind, entry.copy(), index, set(before_handles)),
        name=f"GPMRememberWindow-{kind}-{index}",
        daemon=False,
    )
    thread.start()


def resolve_entry_index(entries: list[dict], target: str, aliases: dict[str, str] | None = None) -> int | None:
    text = (target or "").strip()
    if not text:
        return None
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(entries):
            return index
        return None

    lowered = text.lower()
    if aliases:
        lowered = aliases.get(lowered, lowered)
    for index, entry in enumerate(entries):
        if str(entry.get("name", "")).strip().lower() == lowered:
            return index
    return None


def launch_gpm_entry(config: dict, index: int) -> str:
    entries = config.get("gpm_entries", [])
    if index < 0 or index >= len(entries):
        raise ValueError("GPM 항목을 찾지 못했습니다.")
    entry = entries[index]
    url = normalize_mdm_url(entry.get("url", ""))
    if not url:
        name = safe_name(entry.get("name", ""), f"GPM {index + 1}")
        raise ValueError(f"{name} GPM 주소가 비어 있습니다.")
    if focus_existing_entry_window("gpm", entry, index, config):
        return "focused"
    before_handles = visible_window_handles()
    launch_mdm_url(url)
    remember_new_entry_window_async("gpm", entry, index, before_handles)
    return "launched"


def launch_environment(config: dict, env_key: str) -> str:
    target = "MEMORY" if env_key.upper() == "MEM" else env_key
    index = resolve_entry_index(config.get("gpm_entries", []), target, {"mem": "memory"})
    if index is None:
        raise ValueError(f"Unknown GPM entry: {env_key}")
    return launch_gpm_entry(config, index)


def normalize_web_url(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        return text
    return "http://" + text


def safe_name(value: str, fallback: str = "OI") -> str:
    text = (value or "").strip() or fallback
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:80] or fallback


def slug_name(value: str, fallback: str = "oi") -> str:
    text = safe_name(value, fallback).lower()
    text = re.sub(r"[^a-z0-9가-힣._ -]+", "_", text)
    text = re.sub(r"\s+", "-", text).strip("._-")
    return text[:80] or fallback


def get_desktop_path() -> Path:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            value, _ = winreg.QueryValueEx(key, "Desktop")
            return Path(os.path.expandvars(value))
    except OSError:
        return Path.home() / "Desktop"


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def pythonw_path() -> str:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    if candidate.exists():
        return str(candidate)
    return str(exe)


def icon_location() -> str:
    if getattr(sys, "frozen", False):
        ico = resource_base_dir() / "assets" / "gpm_launcher.ico"
        if ico.exists():
            return str(ico)
        return str(Path(sys.executable).resolve())
    ico = resource_base_dir() / "assets" / "gpm_launcher.ico"
    if ico.exists():
        return str(ico)
    return str(Path(sys.executable).resolve())


def oi_icon_location() -> str:
    ico = resource_base_dir() / "assets" / "oi_launcher.ico"
    if ico.exists():
        return str(ico)
    return icon_location()


def generated_icon_location(kind: str, entry: dict) -> str:
    fallback = oi_icon_location() if kind in {"oi", "agreement"} else icon_location()
    name = safe_name(entry.get("name", ""), kind_display_name(kind))
    digest = hashlib.sha1(f"{kind}|{name}|{normalized_entry_url(kind, entry)}".encode("utf-8", errors="ignore")).hexdigest()[:12]
    icon_dir = CONFIG_DIR / "icons"
    icon_dir.mkdir(parents=True, exist_ok=True)
    icon_path = icon_dir / f"{kind}-{slug_name(name, kind)}-{digest}.ico"
    if icon_path.exists():
        return str(icon_path)

    specs = {
        "gpm": ("GPM", (27, 94, 170, 255), (40, 163, 106, 255)),
        "oi": ("OI", (38, 76, 89, 255), (42, 126, 161, 255)),
        "agreement": ("합의", (92, 64, 140, 255), (48, 132, 130, 255)),
    }
    main_text, top_color, bottom_color = specs.get(kind, specs["gpm"])
    label = icon_label(name)
    try:
        create_icon_with_powershell(icon_path, main_text, label, top_color, bottom_color)
        return str(icon_path) if icon_path.exists() else fallback
    except Exception:
        return fallback


def icon_label(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z가-힣]+", "", value or "").strip()
    if not text:
        return ""
    if len(text) <= 5:
        return text.upper()
    uppercase = "".join(ch for ch in text if ch.isupper() or ch.isdigit())
    if 2 <= len(uppercase) <= 5:
        return uppercase
    return text[:5].upper()


def create_icon_with_powershell(icon_path: Path, main_text: str, label: str, top_color: tuple[int, int, int, int], bottom_color: tuple[int, int, int, int]) -> None:
    main_size = 86 if len(main_text) <= 2 else 58
    label_size = 42 if len(label) <= 4 else 32
    script = f"""
Add-Type -AssemblyName System.Drawing
$path = {ps_quote(str(icon_path))}
$mainText = {ps_quote(main_text)}
$labelText = {ps_quote(label)}
$bitmap = New-Object System.Drawing.Bitmap 256, 256
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.Clear([System.Drawing.Color]::Transparent)
$topBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb({top_color[3]}, {top_color[0]}, {top_color[1]}, {top_color[2]}))
$bottomBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb({bottom_color[3]}, {bottom_color[0]}, {bottom_color[1]}, {bottom_color[2]}))
$whiteBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::White)
$pathShape = New-Object System.Drawing.Drawing2D.GraphicsPath
$r = 44
$pathShape.AddArc(16, 16, $r, $r, 180, 90)
$pathShape.AddArc(196, 16, $r, $r, 270, 90)
$pathShape.AddArc(196, 196, $r, $r, 0, 90)
$pathShape.AddArc(16, 196, $r, $r, 90, 90)
$pathShape.CloseFigure()
$graphics.FillPath($topBrush, $pathShape)
$graphics.FillRectangle($bottomBrush, 16, 164, 224, 76)
$format = New-Object System.Drawing.StringFormat
$format.Alignment = [System.Drawing.StringAlignment]::Center
$format.LineAlignment = [System.Drawing.StringAlignment]::Center
$mainFont = New-Object System.Drawing.Font('Malgun Gothic', {main_size}, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$labelFont = New-Object System.Drawing.Font('Malgun Gothic', {label_size}, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$graphics.DrawString($mainText, $mainFont, $whiteBrush, (New-Object System.Drawing.RectangleF 16, 34, 224, 120), $format)
$graphics.DrawString($labelText, $labelFont, $whiteBrush, (New-Object System.Drawing.RectangleF 16, 168, 224, 68), $format)
$memory = New-Object System.IO.MemoryStream
$bitmap.Save($memory, [System.Drawing.Imaging.ImageFormat]::Png)
$png = $memory.ToArray()
$stream = [System.IO.File]::Open($path, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
$writer = New-Object System.IO.BinaryWriter($stream)
$writer.Write([UInt16]0)
$writer.Write([UInt16]1)
$writer.Write([UInt16]1)
$writer.Write([Byte]0)
$writer.Write([Byte]0)
$writer.Write([Byte]0)
$writer.Write([Byte]0)
$writer.Write([UInt16]1)
$writer.Write([UInt16]32)
$writer.Write([UInt32]$png.Length)
$writer.Write([UInt32]22)
$writer.Write($png)
$writer.Close()
$stream.Close()
$graphics.Dispose()
$bitmap.Dispose()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def launch_command_for_gpm(index: int) -> tuple[str, str, str]:
    launch_arg = str(index + 1)
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), f"--launch {launch_arg}", str(app_base_dir())
    return pythonw_path(), f'"{Path(__file__).resolve()}" --launch {launch_arg}', str(app_base_dir())


def create_shortcut(shortcut_path: Path, target: str, arguments: str, working_dir: str, icon: str) -> None:
    script = "\n".join(
        [
            "$shell = New-Object -ComObject WScript.Shell",
            f"$shortcut = $shell.CreateShortcut({ps_quote(str(shortcut_path))})",
            f"$shortcut.TargetPath = {ps_quote(target)}",
            f"$shortcut.Arguments = {ps_quote(arguments)}",
            f"$shortcut.WorkingDirectory = {ps_quote(working_dir)}",
            f"$shortcut.IconLocation = {ps_quote(icon)}",
            "$shortcut.Save()",
        ]
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def oi_shortcut_path(entry: dict, index: int) -> Path:
    shortcuts_dir = CONFIG_DIR / "oi-shortcuts"
    shortcuts_dir.mkdir(parents=True, exist_ok=True)
    name = safe_name(entry.get("name", ""), f"OI {index + 1}")
    return shortcuts_dir / f"{name} OI.lnk"


def web_shortcut_path(kind: str, entry: dict, index: int) -> Path:
    shortcuts_dir = CONFIG_DIR / f"{kind}-shortcuts"
    shortcuts_dir.mkdir(parents=True, exist_ok=True)
    name = safe_name(entry.get("name", ""), f"{kind_display_name(kind)} {index + 1}")
    return shortcuts_dir / f"{name} {kind_display_name(kind)}.lnk"


def create_web_app_shortcut(kind: str, entry: dict, index: int, config: dict, desktop: bool = False) -> Path:
    label = kind_display_name(kind)
    name = safe_name(entry.get("name", ""), f"{label} {index + 1}")
    url = normalize_web_url(entry.get("url", ""))
    if not url:
        raise ValueError(f"{name} {label} 주소가 비어 있습니다.")

    browser_path = resolve_browser_path(config.get("browser") or "default")
    if not browser_path:
        raise ValueError("Edge 또는 Chrome을 찾지 못했습니다.")

    args = " ".join(
        [
            "--no-first-run",
            "--disable-default-browser-check",
            "--start-maximized",
            f"--app={quote_arg(url)}",
        ]
    )
    if desktop:
        target_dir = get_desktop_path()
        target_dir.mkdir(parents=True, exist_ok=True)
        shortcut = target_dir / f"{name} {label}.lnk"
    else:
        shortcut = web_shortcut_path(kind, entry, index)
    create_shortcut(shortcut, browser_path, args, str(app_base_dir()), generated_icon_location(kind, entry))
    return shortcut


def create_oi_shortcut(entry: dict, index: int, config: dict) -> Path:
    return create_web_app_shortcut("oi", entry, index, config, desktop=False)


def create_oi_desktop_shortcut(entry: dict, index: int, config: dict) -> Path:
    return create_web_app_shortcut("oi", entry, index, config, desktop=True)


def create_agreement_shortcut(entry: dict, index: int, config: dict) -> Path:
    return create_web_app_shortcut("agreement", entry, index, config, desktop=False)


def create_agreement_desktop_shortcut(entry: dict, index: int, config: dict) -> Path:
    return create_web_app_shortcut("agreement", entry, index, config, desktop=True)


def quote_arg(value: str) -> str:
    if not value or re.search(r"\s|\"", value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def launch_oi_entry(config: dict, index: int) -> str:
    entries = config.get("oi_entries", [])
    if index < 0 or index >= len(entries):
        raise ValueError("OI 항목을 찾지 못했습니다.")
    entry = entries[index]
    if focus_existing_entry_window("oi", entry, index, config):
        return "focused"
    before_handles = visible_window_handles()
    shortcut = create_oi_shortcut(entry, index, config)
    shell_open(str(shortcut), SW_SHOWNORMAL)
    remember_new_entry_window_async("oi", entry, index, before_handles)
    return "launched"


def launch_agreement_entry(config: dict, index: int) -> str:
    entries = config.get("agreement_entries", [])
    if index < 0 or index >= len(entries):
        raise ValueError("합의 항목을 찾지 못했습니다.")
    entry = entries[index]
    if focus_existing_entry_window("agreement", entry, index, config):
        return "focused"
    before_handles = visible_window_handles()
    shortcut = create_agreement_shortcut(entry, index, config)
    shell_open(str(shortcut), SW_SHOWNORMAL)
    remember_new_entry_window_async("agreement", entry, index, before_handles)
    return "launched"


def create_gpm_desktop_shortcut(entry: dict, index: int) -> Path:
    desktop = get_desktop_path()
    desktop.mkdir(parents=True, exist_ok=True)
    name = safe_name(entry.get("name", ""), f"GPM {index + 1}")
    target, args, working_dir = launch_command_for_gpm(index)
    shortcut = desktop / f"{name} GPM.lnk"
    create_shortcut(shortcut, target, args, working_dir, generated_icon_location("gpm", entry))
    return shortcut


def create_desktop_shortcuts(config: dict) -> list[Path]:
    created = []
    for index, entry in enumerate(config.get("gpm_entries", [])):
        if not isinstance(entry, dict):
            continue
        if not (entry.get("url") or "").strip():
            continue
        created.append(create_gpm_desktop_shortcut(entry, index))
    return created


def set_startup(enabled: bool) -> None:
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            if getattr(sys, "frozen", False):
                command = f'"{Path(sys.executable).resolve()}" --background'
            else:
                command = f'"{pythonw_path()}" "{Path(__file__).resolve()}" --background'
            winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, APP_REG_NAME)
            except FileNotFoundError:
                pass


def startup_enabled_now() -> bool:
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_REG_NAME)
            return True
    except OSError:
        return False


def virtual_key_for_token(token: str) -> int | None:
    token = token.upper()
    if len(token) == 1 and ("A" <= token <= "Z" or "0" <= token <= "9"):
        return ord(token)
    if re.fullmatch(r"F([1-9]|1[0-9]|2[0-4])", token):
        return 0x6F + int(token[1:])
    special = {
        "SPACE": 0x20,
        "TAB": 0x09,
        "ENTER": 0x0D,
        "RETURN": 0x0D,
        "BACKSPACE": 0x08,
        "ESC": 0x1B,
        "ESCAPE": 0x1B,
        "INSERT": 0x2D,
        "INS": 0x2D,
        "DELETE": 0x2E,
        "DEL": 0x2E,
        "HOME": 0x24,
        "END": 0x23,
        "PAGEUP": 0x21,
        "PAGEDOWN": 0x22,
        "UP": 0x26,
        "DOWN": 0x28,
        "LEFT": 0x25,
        "RIGHT": 0x27,
    }
    return special.get(token)


def hotkey_to_native(sequence: str) -> tuple[int, int]:
    text = (sequence or "").strip().replace(" ", "")
    if not text:
        raise ValueError("단축키가 비어 있습니다.")

    parts = [part for part in text.split("+") if part]
    modifiers = MOD_NOREPEAT
    key_token = ""
    for part in parts:
        token = part.upper()
        if token in ("CTRL", "CONTROL"):
            modifiers |= MOD_CONTROL
        elif token == "ALT":
            modifiers |= MOD_ALT
        elif token == "SHIFT":
            modifiers |= MOD_SHIFT
        elif token in ("WIN", "WINDOWS", "META"):
            modifiers |= MOD_WIN
        else:
            key_token = token

    if not key_token:
        raise ValueError("실행 키가 없습니다.")
    vk = virtual_key_for_token(key_token)
    if vk is None:
        raise ValueError(f"지원하지 않는 키입니다: {key_token}")
    if modifiers == MOD_NOREPEAT:
        raise ValueError("Ctrl, Alt, Shift, Win 중 하나 이상을 같이 지정하세요.")
    return modifiers, vk


class TrayIcon:
    def __init__(self, root: tk.Tk, title: str, icon_path: str, on_show, on_exit) -> None:
        self.root = root
        self.title = title
        self.icon_path = icon_path
        self.on_show = on_show
        self.on_exit = on_exit
        self.hwnd = wintypes.HWND(int(root.winfo_id()))
        self.icon_id = 1
        self.hicon: int | None = None
        self.visible = False
        self.old_wndproc: int | None = None
        self._wndproc = WNDPROC(self._handle_message)

    def show(self) -> bool:
        if self.visible:
            return True
        if not self._ensure_window_proc():
            return False

        self.hicon = self._load_icon()
        if not self.hicon:
            return False

        data = self._notify_data()
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
            user32.DestroyIcon(wintypes.HICON(self.hicon))
            self.hicon = None
            return False

        self.visible = True
        return True

    def hide(self) -> None:
        if self.visible:
            data = self._notify_data()
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
            self.visible = False
        if self.hicon:
            user32.DestroyIcon(wintypes.HICON(self.hicon))
            self.hicon = None

    def destroy(self) -> None:
        self.hide()
        if self.old_wndproc:
            SetWindowLongPtrW(self.hwnd, GWL_WNDPROC, self.old_wndproc)
            self.old_wndproc = None

    def _ensure_window_proc(self) -> bool:
        if self.old_wndproc:
            return True
        proc_ptr = ctypes.cast(self._wndproc, ctypes.c_void_p).value
        if not proc_ptr:
            return False
        old = SetWindowLongPtrW(self.hwnd, GWL_WNDPROC, int(proc_ptr))
        if not old:
            return False
        self.old_wndproc = int(old)
        return True

    def _load_icon(self) -> int | None:
        if self.icon_path and Path(self.icon_path).exists():
            handle = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if handle:
                return int(handle)
        return None

    def _notify_data(self) -> NOTIFYICONDATAW:
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self.hwnd
        data.uID = self.icon_id
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAYICON
        data.hIcon = wintypes.HICON(self.hicon or 0)
        data.szTip = self.title[:127]
        return data

    def _handle_message(self, hwnd, message, wparam, lparam):
        if message == WM_TRAYICON:
            event = int(lparam)
            if event == WM_LBUTTONDBLCLK:
                self.root.after(0, self.on_show)
            elif event == WM_RBUTTONUP:
                self._show_menu()
            return 0

        if message == WM_COMMAND:
            command_id = int(wparam) & 0xFFFF
            if command_id == ID_TRAY_SHOW:
                self.root.after(0, self.on_show)
                return 0
            if command_id == ID_TRAY_EXIT:
                self.root.after(0, self.on_exit)
                return 0

        if self.old_wndproc:
            return user32.CallWindowProcW(self.old_wndproc, hwnd, message, wparam, lparam)
        return 0

    def _show_menu(self) -> None:
        point = POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return

        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            user32.AppendMenuW(menu, MF_STRING, ID_TRAY_SHOW, "열기")
            user32.AppendMenuW(menu, MF_STRING, ID_TRAY_EXIT, "종료")
            user32.SetForegroundWindow(self.hwnd)
            user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON, point.x, point.y, 0, self.hwnd, None)
            user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        finally:
            user32.DestroyMenu(menu)


class HotkeyService:
    def __init__(self, config: dict, on_hotkey, on_errors) -> None:
        self.config = config
        self.on_hotkey = on_hotkey
        self.on_errors = on_errors
        self.thread: threading.Thread | None = None
        self.thread_id: int | None = None
        self.ready = threading.Event()
        self.stopping = threading.Event()

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="GPMHotkeys", daemon=True)
        self.thread.start()
        self.ready.wait(timeout=2)

    def stop(self) -> None:
        self.stopping.set()
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

    def _run(self) -> None:
        self.thread_id = int(kernel32.GetCurrentThreadId())
        registered: dict[int, str] = {}
        errors = []
        try:
            for index, entry in enumerate(self.config.get("gpm_entries", [])):
                if not isinstance(entry, dict):
                    continue
                name = safe_name(entry.get("name", ""), f"GPM {index + 1}")
                if not (entry.get("url") or "").strip():
                    continue
                hotkey = (entry.get("hotkey") or "").strip()
                if not hotkey:
                    continue
                try:
                    modifiers, vk = hotkey_to_native(hotkey)
                except ValueError as exc:
                    errors.append(f"GPM {name}: {exc}")
                    continue
                hotkey_id = HOTKEY_BASE_ID + index
                if user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
                    registered[hotkey_id] = f"gpm:{index}"
                else:
                    errors.append(f"GPM {name}: 단축키 등록 실패 ({hotkey})")

            for index, entry in enumerate(self.config.get("oi_entries", [])):
                if not isinstance(entry, dict):
                    continue
                name = safe_name(entry.get("name", ""), f"OI {index + 1}")
                if not (entry.get("url") or "").strip():
                    continue
                hotkey = (entry.get("hotkey") or "").strip()
                if not hotkey:
                    continue
                try:
                    modifiers, vk = hotkey_to_native(hotkey)
                except ValueError as exc:
                    errors.append(f"OI {name}: {exc}")
                    continue
                hotkey_id = OI_HOTKEY_BASE_ID + index
                if user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
                    registered[hotkey_id] = f"oi:{index}"
                else:
                    errors.append(f"OI {name}: 단축키 등록 실패 ({hotkey})")

            for index, entry in enumerate(self.config.get("agreement_entries", [])):
                if not isinstance(entry, dict):
                    continue
                name = safe_name(entry.get("name", ""), f"합의 {index + 1}")
                if not (entry.get("url") or "").strip():
                    continue
                hotkey = (entry.get("hotkey") or "").strip()
                if not hotkey:
                    continue
                try:
                    modifiers, vk = hotkey_to_native(hotkey)
                except ValueError as exc:
                    errors.append(f"합의 {name}: {exc}")
                    continue
                hotkey_id = AGREEMENT_HOTKEY_BASE_ID + index
                if user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
                    registered[hotkey_id] = f"agreement:{index}"
                else:
                    errors.append(f"합의 {name}: 단축키 등록 실패 ({hotkey})")

            if errors:
                self.on_errors(errors)
            self.ready.set()

            msg = MSG()
            while not self.stopping.is_set() and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY:
                    action = registered.get(int(msg.wParam))
                    if action:
                        self.on_hotkey(action)
        finally:
            for hotkey_id in registered:
                user32.UnregisterHotKey(None, hotkey_id)
            self.ready.set()


class LauncherApp:
    def __init__(self, background: bool = False) -> None:
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("1280x760")
        self.root.minsize(1100, 680)
        ico = resource_base_dir() / "assets" / "gpm_launcher.ico"
        if ico.exists():
            try:
                self.root.iconbitmap(str(ico))
            except tk.TclError:
                pass

        self.config = load_config()
        self.hotkey_service: HotkeyService | None = None
        self.refresh_after_id: str | None = None
        self.gpm_entries: list[dict] = []
        self.oi_entries: list[dict] = []
        self.agreement_entries: list[dict] = []
        self.tray_icon: TrayIcon | None = None
        self.hotkey_capture_var: tk.StringVar | None = None
        self.hotkey_capture_modifiers: set[str] = set()
        self.hotkey_capture_original_value = ""

        self._build_ui()
        self._load_config_to_ui()
        self.apply_runtime_settings(show_errors=False)
        self.root.update_idletasks()
        self.tray_icon = TrayIcon(self.root, APP_NAME, icon_location(), self.show_from_tray, self.quit)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        if background:
            self.hide_to_tray(show_warning=False, force=True)
            if self.config.get("refresh_enabled", True):
                self.root.after(2500, lambda: self.refresh_workspace(show_status=False))

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        outer = ttk.Frame(self.root, padding=12)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        title = ttk.Label(outer, text="GPM Launcher", font=("Segoe UI", 16, "bold"))
        title.grid(row=0, column=0, sticky="w", pady=(0, 10))

        body = ttk.Frame(outer)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1, uniform="main")
        body.columnconfigure(1, weight=1, uniform="main")
        body.rowconfigure(0, weight=1, uniform="main")
        body.rowconfigure(1, weight=1, uniform="main")

        self._build_workspace_frame(body, row=0, column=0)
        self._build_gpm_frame(body, row=1, column=0)
        self._build_oi_frame(body, row=0, column=1)
        self._build_agreement_frame(body, row=1, column=1)
        self._build_button_row(outer)

        self.status_var = tk.StringVar(value="준비됨")
        status = ttk.Label(outer, textvariable=self.status_var, anchor="w")
        status.grid(row=3, column=0, sticky="ew", pady=(8, 0))

    def _build_workspace_frame(self, parent: ttk.Frame, row: int, column: int) -> None:
        frame = ttk.LabelFrame(parent, text="Workspace", padding=10)
        frame.grid(row=row, column=column, sticky="nsew", padx=(0, 6), pady=(0, 6))
        frame.columnconfigure(1, weight=1)

        self.workspace_var = tk.StringVar()
        self.browser_var = tk.StringVar(value="default")
        self.refresh_enabled_var = tk.BooleanVar(value=True)
        self.refresh_minutes_var = tk.IntVar(value=210)
        self.workspace_close_seconds_var = tk.IntVar(value=8)
        self.startup_var = tk.BooleanVar(value=True)

        ttk.Label(frame, text="주소").grid(row=0, column=0, sticky="e", padx=(0, 8), pady=3)
        ttk.Entry(frame, textvariable=self.workspace_var).grid(row=0, column=1, sticky="ew", pady=3)

        ttk.Label(frame, text="브라우저").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=3)
        browser = ttk.Combobox(frame, textvariable=self.browser_var, values=("default", "edge", "chrome"), state="readonly", width=12)
        browser.grid(row=1, column=1, sticky="w", pady=3)

        ttk.Label(frame, text="리프레시").grid(row=2, column=0, sticky="e", padx=(0, 8), pady=3)
        refresh_row = ttk.Frame(frame)
        refresh_row.grid(row=2, column=1, sticky="w", pady=3)
        ttk.Checkbutton(refresh_row, text="자동", variable=self.refresh_enabled_var).pack(side="left")
        tk.Spinbox(refresh_row, from_=1, to=720, increment=1, width=6, textvariable=self.refresh_minutes_var).pack(side="left", padx=(10, 4))
        ttk.Label(refresh_row, text="분").pack(side="left")
        ttk.Label(refresh_row, text="제한").pack(side="left", padx=(10, 4))
        tk.Spinbox(refresh_row, from_=1, to=120, increment=1, width=5, textvariable=self.workspace_close_seconds_var).pack(side="left")
        ttk.Label(refresh_row, text="초").pack(side="left", padx=(4, 0))
        ttk.Button(refresh_row, text="지금 갱신", command=self.refresh_workspace_from_ui).pack(side="left", padx=(12, 0))
        ttk.Button(refresh_row, text="Workspace 열기", command=self.open_workspace_visible).pack(side="left", padx=(6, 0))

        ttk.Checkbutton(frame, text="Windows 시작 시 백그라운드 실행", variable=self.startup_var).grid(row=3, column=1, sticky="w", pady=3)

    def _build_gpm_frame(self, parent: ttk.Frame, row: int, column: int) -> None:
        frame = ttk.LabelFrame(parent, text="GPM", padding=10)
        frame.grid(row=row, column=column, sticky="nsew", padx=(0, 6), pady=(6, 0))
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)

        self.gpm_name_var = tk.StringVar()
        self.gpm_url_var = tk.StringVar()
        self.gpm_hotkey_var = tk.StringVar()

        editor = ttk.Frame(frame)
        editor.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        editor.columnconfigure(3, weight=1)
        ttk.Label(editor, text="이름").grid(row=0, column=0, sticky="e", padx=(0, 6))
        ttk.Entry(editor, textvariable=self.gpm_name_var, width=14).grid(row=0, column=1, sticky="w", padx=(0, 10))
        ttk.Label(editor, text="주소").grid(row=0, column=2, sticky="e", padx=(0, 6))
        gpm_url_entry = ttk.Entry(editor, textvariable=self.gpm_url_var)
        gpm_url_entry.grid(row=0, column=3, sticky="ew", padx=(0, 10))
        gpm_url_entry.bind("<FocusOut>", lambda _event=None: self._normalize_gpm_editor_url())
        gpm_url_entry.bind("<<Paste>>", lambda _event=None: self.root.after(80, self._normalize_gpm_editor_url))
        ttk.Label(editor, text="단축키").grid(row=0, column=4, sticky="e", padx=(0, 6))
        self._create_hotkey_entry(editor, self.gpm_hotkey_var).grid(row=0, column=5, sticky="w")

        self.gpm_tree = ttk.Treeview(frame, columns=("name", "url", "hotkey", "icon"), show="headings", height=4)
        self.gpm_tree.heading("name", text="이름")
        self.gpm_tree.heading("url", text="MDM 주소")
        self.gpm_tree.heading("hotkey", text="단축키")
        self.gpm_tree.heading("icon", text="아이콘")
        self.gpm_tree.column("name", width=90, stretch=False)
        self.gpm_tree.column("url", width=260, stretch=True)
        self.gpm_tree.column("hotkey", width=120, stretch=False)
        self.gpm_tree.column("icon", width=80, stretch=False, anchor="center")
        self.gpm_tree.grid(row=1, column=0, columnspan=4, sticky="nsew")
        self.gpm_tree.bind("<<TreeviewSelect>>", lambda _event=None: self._load_selected_gpm_to_editor())
        self.gpm_tree.bind("<ButtonRelease-1>", self._handle_gpm_tree_click)

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="추가 / 수정", command=self.add_or_update_gpm).pack(side="left")
        ttk.Button(buttons, text="삭제", command=self.delete_selected_gpm).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="실행", command=self.launch_selected_gpm).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="선택 GPM 아이콘 다운로드", command=self.create_selected_gpm_icon).pack(side="left", padx=(6, 0))

        hint = ttk.Label(frame, text="GPM 임시 주소나 curl://launch/... 주소를 붙여넣으면 자동으로 실행 주소만 정리합니다.", foreground="#555")
        hint.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def _build_oi_frame(self, parent: ttk.Frame, row: int, column: int) -> None:
        frame = ttk.LabelFrame(parent, text="OI", padding=10)
        frame.grid(row=row, column=column, sticky="nsew", padx=(6, 0), pady=(0, 6))
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)

        self.oi_name_var = tk.StringVar()
        self.oi_url_var = tk.StringVar()
        self.oi_hotkey_var = tk.StringVar()

        editor = ttk.Frame(frame)
        editor.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        editor.columnconfigure(3, weight=1)
        ttk.Label(editor, text="이름").grid(row=0, column=0, sticky="e", padx=(0, 6))
        ttk.Entry(editor, textvariable=self.oi_name_var, width=14).grid(row=0, column=1, sticky="w", padx=(0, 10))
        ttk.Label(editor, text="주소").grid(row=0, column=2, sticky="e", padx=(0, 6))
        oi_url_entry = ttk.Entry(editor, textvariable=self.oi_url_var)
        oi_url_entry.grid(row=0, column=3, sticky="ew", padx=(0, 10))
        oi_url_entry.bind("<FocusOut>", lambda _event=None: self._normalize_oi_editor_url())
        oi_url_entry.bind("<<Paste>>", lambda _event=None: self.root.after(80, self._normalize_oi_editor_url))
        ttk.Label(editor, text="단축키").grid(row=0, column=4, sticky="e", padx=(0, 6))
        self._create_hotkey_entry(editor, self.oi_hotkey_var).grid(row=0, column=5, sticky="w")

        self.oi_tree = ttk.Treeview(frame, columns=("name", "url", "hotkey", "icon"), show="headings", height=4)
        self.oi_tree.heading("name", text="이름")
        self.oi_tree.heading("url", text="주소")
        self.oi_tree.heading("hotkey", text="단축키")
        self.oi_tree.heading("icon", text="아이콘")
        self.oi_tree.column("name", width=90, stretch=False)
        self.oi_tree.column("url", width=260, stretch=True)
        self.oi_tree.column("hotkey", width=120, stretch=False)
        self.oi_tree.column("icon", width=80, stretch=False, anchor="center")
        self.oi_tree.grid(row=1, column=0, columnspan=4, sticky="nsew")
        self.oi_tree.bind("<<TreeviewSelect>>", lambda _event=None: self._load_selected_oi_to_editor())
        self.oi_tree.bind("<ButtonRelease-1>", self._handle_oi_tree_click)

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="추가 / 수정", command=self.add_or_update_oi).pack(side="left")
        ttk.Button(buttons, text="삭제", command=self.delete_selected_oi).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="실행", command=self.launch_selected_oi).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="선택 OI 아이콘 다운로드", command=self.create_selected_oi_icon).pack(side="left", padx=(6, 0))

        hint = ttk.Label(frame, text="OI는 주소창 없는 앱 창으로 열립니다. 작업표시줄 분리를 위해 항목별 바로가기를 만들어 실행합니다.", foreground="#555")
        hint.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def _build_agreement_frame(self, parent: ttk.Frame, row: int, column: int) -> None:
        frame = ttk.LabelFrame(parent, text="합의", padding=10)
        frame.grid(row=row, column=column, sticky="nsew", padx=(6, 0), pady=(6, 0))
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)

        self.agreement_name_var = tk.StringVar()
        self.agreement_url_var = tk.StringVar()
        self.agreement_hotkey_var = tk.StringVar()

        editor = ttk.Frame(frame)
        editor.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        editor.columnconfigure(3, weight=1)
        ttk.Label(editor, text="이름").grid(row=0, column=0, sticky="e", padx=(0, 6))
        ttk.Entry(editor, textvariable=self.agreement_name_var, width=14).grid(row=0, column=1, sticky="w", padx=(0, 10))
        ttk.Label(editor, text="주소").grid(row=0, column=2, sticky="e", padx=(0, 6))
        agreement_url_entry = ttk.Entry(editor, textvariable=self.agreement_url_var)
        agreement_url_entry.grid(row=0, column=3, sticky="ew", padx=(0, 10))
        agreement_url_entry.bind("<FocusOut>", lambda _event=None: self._normalize_agreement_editor_url())
        agreement_url_entry.bind("<<Paste>>", lambda _event=None: self.root.after(80, self._normalize_agreement_editor_url))
        ttk.Label(editor, text="단축키").grid(row=0, column=4, sticky="e", padx=(0, 6))
        self._create_hotkey_entry(editor, self.agreement_hotkey_var).grid(row=0, column=5, sticky="w")

        self.agreement_tree = ttk.Treeview(frame, columns=("name", "url", "hotkey", "icon"), show="headings", height=4)
        self.agreement_tree.heading("name", text="이름")
        self.agreement_tree.heading("url", text="주소")
        self.agreement_tree.heading("hotkey", text="단축키")
        self.agreement_tree.heading("icon", text="아이콘")
        self.agreement_tree.column("name", width=90, stretch=False)
        self.agreement_tree.column("url", width=260, stretch=True)
        self.agreement_tree.column("hotkey", width=120, stretch=False)
        self.agreement_tree.column("icon", width=80, stretch=False, anchor="center")
        self.agreement_tree.grid(row=1, column=0, columnspan=4, sticky="nsew")
        self.agreement_tree.bind("<<TreeviewSelect>>", lambda _event=None: self._load_selected_agreement_to_editor())
        self.agreement_tree.bind("<ButtonRelease-1>", self._handle_agreement_tree_click)

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="추가 / 수정", command=self.add_or_update_agreement).pack(side="left")
        ttk.Button(buttons, text="삭제", command=self.delete_selected_agreement).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="실행", command=self.launch_selected_agreement).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="선택 합의 아이콘 다운로드", command=self.create_selected_agreement_icon).pack(side="left", padx=(6, 0))

        hint = ttk.Label(frame, text="합의 링크는 OI처럼 주소창 없는 앱 창으로 열립니다.", foreground="#555")
        hint.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def _build_button_row(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent)
        row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        row.columnconfigure(0, weight=1)
        ttk.Button(row, text="저장 / 적용", command=self.save_from_ui).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(row, text="전체 GPM 아이콘 다운로드", command=self.create_icons).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(row, text="숨기기", command=self.hide_to_tray).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(row, text="종료", command=self.quit).grid(row=0, column=4)

    def _bind_auto_normalize(self, entry: ttk.Entry, var: tk.StringVar) -> None:
        def normalize_later(_event=None) -> None:
            self.root.after(80, lambda: self._normalize_var(var))

        entry.bind("<<Paste>>", normalize_later)
        entry.bind("<Control-v>", normalize_later)
        entry.bind("<FocusOut>", normalize_later)

    def _create_hotkey_entry(self, parent: tk.Widget, var: tk.StringVar) -> ttk.Entry:
        entry = ttk.Entry(parent, textvariable=var, width=18, state="readonly")

        def start_capture(_event=None) -> None:
            self.root.after_idle(lambda: self.start_hotkey_capture(var))

        def restore_if_unfinished(_event=None) -> None:
            self._restore_hotkey_capture_if_target(var)

        entry.bind("<FocusIn>", start_capture)
        entry.bind("<Button-1>", start_capture)
        entry.bind("<FocusOut>", restore_if_unfinished)
        return entry

    def _normalize_var(self, var: tk.StringVar) -> None:
        before = var.get()
        after = normalize_mdm_url(before)
        if after != before:
            var.set(after)
            self.set_status("주소를 curl 실행 주소로 정리했습니다.")

    def start_hotkey_capture(self, target_var: tk.StringVar) -> None:
        if self.hotkey_capture_var is target_var:
            return
        self.stop_hotkey_capture(restore_original=True)
        self.hotkey_capture_var = target_var
        self.hotkey_capture_modifiers = set()
        self.hotkey_capture_original_value = target_var.get()
        target_var.set(HOTKEY_CAPTURE_PROMPT)
        self.set_status("등록할 단축키 조합을 누르세요. Esc는 취소, Backspace/Delete는 삭제입니다.")
        self.root.bind_all("<KeyPress>", self._capture_hotkey_event)
        self.root.bind_all("<KeyRelease>", self._release_hotkey_modifier)

    def stop_hotkey_capture(self, restore_original: bool = False) -> None:
        if self.hotkey_capture_var is not None:
            target_var = self.hotkey_capture_var
            original_value = self.hotkey_capture_original_value
            self.root.unbind_all("<KeyPress>")
            self.root.unbind_all("<KeyRelease>")
            self.hotkey_capture_var = None
            self.hotkey_capture_modifiers = set()
            self.hotkey_capture_original_value = ""
            if restore_original and target_var.get() == HOTKEY_CAPTURE_PROMPT:
                target_var.set(original_value)

    def _restore_hotkey_capture_if_target(self, target_var: tk.StringVar) -> None:
        if self.hotkey_capture_var is target_var:
            self.stop_hotkey_capture(restore_original=True)

    def _capture_hotkey_event(self, event) -> str:
        if self.hotkey_capture_var is None:
            return "break"
        if event.keysym == "Escape":
            self.stop_hotkey_capture(restore_original=True)
            self.set_status("단축키 입력을 취소했습니다.")
            return "break"
        if event.keysym in {"BackSpace", "Delete"}:
            self.hotkey_capture_var.set("")
            self.stop_hotkey_capture()
            self.set_status("단축키를 비웠습니다.")
            return "break"

        key = self._hotkey_key_name(event.keysym)
        if not key:
            return "break"

        if key in {"Ctrl", "Alt", "Shift", "Win"}:
            self.hotkey_capture_modifiers.add(key)
            return "break"

        modifiers = self._event_modifiers(event)
        if not modifiers:
            self.set_status("Ctrl, Alt, Shift, Win 중 하나 이상과 같이 누르세요.")
            return "break"

        hotkey = "+".join([*modifiers, key])
        self.hotkey_capture_var.set(hotkey)
        self.stop_hotkey_capture()
        self.set_status(f"단축키를 {hotkey}로 입력했습니다.")
        return "break"

    def _release_hotkey_modifier(self, event) -> str:
        key = self._hotkey_key_name(event.keysym)
        if key in {"Ctrl", "Alt", "Shift", "Win"}:
            self.hotkey_capture_modifiers.discard(key)
        return "break"

    def _event_modifiers(self, event) -> list[str]:
        modifiers = set(self.hotkey_capture_modifiers)
        if event.state & 0x0004:
            modifiers.add("Ctrl")
        if event.state & 0x0008 or event.state & 0x20000:
            modifiers.add("Alt")
        if event.state & 0x0001:
            modifiers.add("Shift")
        if event.state & 0x0040 or event.state & 0x0080:
            modifiers.add("Win")
        return [name for name in ("Ctrl", "Alt", "Shift", "Win") if name in modifiers]

    def _hotkey_key_name(self, keysym: str) -> str:
        aliases = {
            "Control_L": "Ctrl",
            "Control_R": "Ctrl",
            "Alt_L": "Alt",
            "Alt_R": "Alt",
            "Shift_L": "Shift",
            "Shift_R": "Shift",
            "Super_L": "Win",
            "Super_R": "Win",
            "Win_L": "Win",
            "Win_R": "Win",
            "Return": "Enter",
            "Escape": "Esc",
            "Prior": "PageUp",
            "Next": "PageDown",
            "BackSpace": "Backspace",
            "Delete": "Delete",
            "Insert": "Insert",
            "space": "Space",
        }
        if keysym in aliases:
            return aliases[keysym]
        if len(keysym) == 1 and keysym.isalnum():
            return keysym.upper()
        if re.fullmatch(r"F([1-9]|1[0-9]|2[0-4])", keysym, flags=re.IGNORECASE):
            return keysym.upper()
        if keysym in {"Tab", "Home", "End", "Up", "Down", "Left", "Right"}:
            return keysym
        return ""

    def _normalize_gpm_editor_url(self) -> None:
        before = self.gpm_url_var.get()
        after = normalize_mdm_url(before)
        if before.strip() and after != before:
            self.gpm_url_var.set(after)
            self.set_status("GPM 주소를 curl 실행 주소로 정리했습니다.")

    def _refresh_gpm_tree(self) -> None:
        for item in self.gpm_tree.get_children():
            self.gpm_tree.delete(item)
        for index, entry in enumerate(self.gpm_entries):
            self.gpm_tree.insert("", "end", iid=str(index), values=(entry.get("name", ""), entry.get("url", ""), entry.get("hotkey", ""), "다운로드"))

    def _handle_gpm_tree_click(self, event) -> None:
        if self.gpm_tree.identify_column(event.x) != "#4":
            return
        row_id = self.gpm_tree.identify_row(event.y)
        if not row_id:
            return
        self.gpm_tree.selection_set(row_id)
        self.create_selected_gpm_icon()

    def _selected_gpm_index(self) -> int | None:
        selection = self.gpm_tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def _load_selected_gpm_to_editor(self) -> None:
        index = self._selected_gpm_index()
        if index is None or index >= len(self.gpm_entries):
            return
        entry = self.gpm_entries[index]
        self.gpm_name_var.set(entry.get("name", ""))
        self.gpm_url_var.set(entry.get("url", ""))
        self.gpm_hotkey_var.set(entry.get("hotkey", ""))

    def add_or_update_gpm(self) -> None:
        self.stop_hotkey_capture(restore_original=True)
        name = safe_name(self.gpm_name_var.get(), f"GPM {len(self.gpm_entries) + 1}")
        url = normalize_mdm_url(self.gpm_url_var.get())
        hotkey = self.gpm_hotkey_var.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, "GPM 주소를 입력하세요.")
            return
        entry = {"name": name, "url": url, "hotkey": hotkey}
        index = self._selected_gpm_index()
        if index is None or index >= len(self.gpm_entries):
            self.gpm_entries.append(entry)
            index = len(self.gpm_entries) - 1
        else:
            self.gpm_entries[index] = entry
        self._refresh_gpm_tree()
        self.gpm_tree.selection_set(str(index))
        self.save_from_ui(silent=True)
        self.set_status(f"GPM {name} 항목을 저장했습니다.")

    def delete_selected_gpm(self) -> None:
        index = self._selected_gpm_index()
        if index is None or index >= len(self.gpm_entries):
            self.set_status("삭제할 GPM 항목을 선택하세요.")
            return
        name = self.gpm_entries[index].get("name", f"GPM {index + 1}")
        del self.gpm_entries[index]
        self.gpm_name_var.set("")
        self.gpm_url_var.set("")
        self.gpm_hotkey_var.set("")
        self._refresh_gpm_tree()
        self.save_from_ui(silent=True)
        self.set_status(f"GPM {name} 항목을 삭제했습니다.")

    def launch_selected_gpm(self) -> None:
        index = self._selected_gpm_index()
        if index is None:
            self.add_or_update_gpm()
            index = self._selected_gpm_index()
        if index is not None:
            self.launch_gpm(index)

    def create_selected_gpm_icon(self) -> None:
        index = self._selected_gpm_index()
        if index is None or index >= len(self.gpm_entries):
            self.set_status("아이콘을 만들 GPM 항목을 선택하세요.")
            return
        self.save_from_ui(silent=True)
        try:
            entry = self.gpm_entries[index]
            shortcut = create_gpm_desktop_shortcut(entry, index)
            messagebox.showinfo(APP_NAME, f"바탕화면 아이콘을 만들었습니다.\n\n{shortcut.name}")
            self.set_status(f"{shortcut.name} 아이콘을 만들었습니다.")
        except Exception as exc:
            messagebox.showwarning(APP_NAME, f"GPM 아이콘 생성 실패:\n{exc}")

    def _normalize_oi_editor_url(self) -> None:
        before = self.oi_url_var.get()
        after = normalize_web_url(before)
        if before.strip() and after != before:
            self.oi_url_var.set(after)
            self.set_status("OI 주소를 브라우저 주소로 정리했습니다.")

    def _refresh_oi_tree(self) -> None:
        for item in self.oi_tree.get_children():
            self.oi_tree.delete(item)
        for index, entry in enumerate(self.oi_entries):
            self.oi_tree.insert("", "end", iid=str(index), values=(entry.get("name", ""), entry.get("url", ""), entry.get("hotkey", ""), "다운로드"))

    def _handle_oi_tree_click(self, event) -> None:
        if self.oi_tree.identify_column(event.x) != "#4":
            return
        row_id = self.oi_tree.identify_row(event.y)
        if not row_id:
            return
        self.oi_tree.selection_set(row_id)
        self.create_selected_oi_icon()

    def _selected_oi_index(self) -> int | None:
        selection = self.oi_tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def _load_selected_oi_to_editor(self) -> None:
        index = self._selected_oi_index()
        if index is None or index >= len(self.oi_entries):
            return
        entry = self.oi_entries[index]
        self.oi_name_var.set(entry.get("name", ""))
        self.oi_url_var.set(entry.get("url", ""))
        self.oi_hotkey_var.set(entry.get("hotkey", ""))

    def add_or_update_oi(self) -> None:
        self.stop_hotkey_capture(restore_original=True)
        name = safe_name(self.oi_name_var.get(), f"OI {len(self.oi_entries) + 1}")
        url = normalize_web_url(self.oi_url_var.get())
        hotkey = self.oi_hotkey_var.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, "OI 주소를 입력하세요.")
            return
        entry = {"name": name, "url": url, "hotkey": hotkey}
        index = self._selected_oi_index()
        if index is None or index >= len(self.oi_entries):
            self.oi_entries.append(entry)
            index = len(self.oi_entries) - 1
        else:
            self.oi_entries[index] = entry
        self._refresh_oi_tree()
        self.oi_tree.selection_set(str(index))
        self.save_from_ui(silent=True)
        self.set_status(f"OI {name} 항목을 저장했습니다.")

    def delete_selected_oi(self) -> None:
        index = self._selected_oi_index()
        if index is None or index >= len(self.oi_entries):
            self.set_status("삭제할 OI 항목을 선택하세요.")
            return
        name = self.oi_entries[index].get("name", f"OI {index + 1}")
        del self.oi_entries[index]
        self.oi_name_var.set("")
        self.oi_url_var.set("")
        self.oi_hotkey_var.set("")
        self._refresh_oi_tree()
        self.save_from_ui(silent=True)
        self.set_status(f"OI {name} 항목을 삭제했습니다.")

    def launch_selected_oi(self) -> None:
        index = self._selected_oi_index()
        if index is None:
            self.add_or_update_oi()
            index = self._selected_oi_index()
        if index is not None:
            self.launch_oi(index)

    def create_selected_oi_icon(self) -> None:
        index = self._selected_oi_index()
        if index is None or index >= len(self.oi_entries):
            self.set_status("아이콘을 만들 OI 항목을 선택하세요.")
            return
        self.save_from_ui(silent=True)
        try:
            entry = self.oi_entries[index]
            shortcut = create_oi_desktop_shortcut(entry, index, self.config)
            messagebox.showinfo(APP_NAME, f"바탕화면 아이콘을 만들었습니다.\n\n{shortcut.name}")
            self.set_status(f"{shortcut.name} 아이콘을 만들었습니다.")
        except Exception as exc:
            messagebox.showwarning(APP_NAME, f"OI 아이콘 생성 실패:\n{exc}")

    def _normalize_agreement_editor_url(self) -> None:
        before = self.agreement_url_var.get()
        after = normalize_web_url(before)
        if before.strip() and after != before:
            self.agreement_url_var.set(after)
            self.set_status("합의 주소를 브라우저 주소로 정리했습니다.")

    def _refresh_agreement_tree(self) -> None:
        for item in self.agreement_tree.get_children():
            self.agreement_tree.delete(item)
        for index, entry in enumerate(self.agreement_entries):
            self.agreement_tree.insert("", "end", iid=str(index), values=(entry.get("name", ""), entry.get("url", ""), entry.get("hotkey", ""), "다운로드"))

    def _handle_agreement_tree_click(self, event) -> None:
        if self.agreement_tree.identify_column(event.x) != "#4":
            return
        row_id = self.agreement_tree.identify_row(event.y)
        if not row_id:
            return
        self.agreement_tree.selection_set(row_id)
        self.create_selected_agreement_icon()

    def _selected_agreement_index(self) -> int | None:
        selection = self.agreement_tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def _load_selected_agreement_to_editor(self) -> None:
        index = self._selected_agreement_index()
        if index is None or index >= len(self.agreement_entries):
            return
        entry = self.agreement_entries[index]
        self.agreement_name_var.set(entry.get("name", ""))
        self.agreement_url_var.set(entry.get("url", ""))
        self.agreement_hotkey_var.set(entry.get("hotkey", ""))

    def add_or_update_agreement(self) -> None:
        self.stop_hotkey_capture(restore_original=True)
        name = safe_name(self.agreement_name_var.get(), f"합의 {len(self.agreement_entries) + 1}")
        url = normalize_web_url(self.agreement_url_var.get())
        hotkey = self.agreement_hotkey_var.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, "합의 주소를 입력하세요.")
            return
        entry = {"name": name, "url": url, "hotkey": hotkey}
        index = self._selected_agreement_index()
        if index is None or index >= len(self.agreement_entries):
            self.agreement_entries.append(entry)
            index = len(self.agreement_entries) - 1
        else:
            self.agreement_entries[index] = entry
        self._refresh_agreement_tree()
        self.agreement_tree.selection_set(str(index))
        self.save_from_ui(silent=True)
        self.set_status(f"합의 {name} 항목을 저장했습니다.")

    def delete_selected_agreement(self) -> None:
        index = self._selected_agreement_index()
        if index is None or index >= len(self.agreement_entries):
            self.set_status("삭제할 합의 항목을 선택하세요.")
            return
        name = self.agreement_entries[index].get("name", f"합의 {index + 1}")
        del self.agreement_entries[index]
        self.agreement_name_var.set("")
        self.agreement_url_var.set("")
        self.agreement_hotkey_var.set("")
        self._refresh_agreement_tree()
        self.save_from_ui(silent=True)
        self.set_status(f"합의 {name} 항목을 삭제했습니다.")

    def launch_selected_agreement(self) -> None:
        index = self._selected_agreement_index()
        if index is None:
            self.add_or_update_agreement()
            index = self._selected_agreement_index()
        if index is not None:
            self.launch_agreement(index)

    def create_selected_agreement_icon(self) -> None:
        index = self._selected_agreement_index()
        if index is None or index >= len(self.agreement_entries):
            self.set_status("아이콘을 만들 합의 항목을 선택하세요.")
            return
        self.save_from_ui(silent=True)
        try:
            entry = self.agreement_entries[index]
            shortcut = create_agreement_desktop_shortcut(entry, index, self.config)
            messagebox.showinfo(APP_NAME, f"바탕화면 아이콘을 만들었습니다.\n\n{shortcut.name}")
            self.set_status(f"{shortcut.name} 아이콘을 만들었습니다.")
        except Exception as exc:
            messagebox.showwarning(APP_NAME, f"합의 아이콘 생성 실패:\n{exc}")

    def _load_config_to_ui(self) -> None:
        self.workspace_var.set(self.config.get("workspace_url", ""))
        self.browser_var.set(self.config.get("browser", "default") or "default")
        self.refresh_enabled_var.set(bool(self.config.get("refresh_enabled", True)))
        self.refresh_minutes_var.set(max(1, int(self.config.get("refresh_minutes", 210) or 210)))
        self.workspace_close_seconds_var.set(max(1, int(self.config.get("workspace_close_seconds", 8) or 8)))
        self.startup_var.set(bool(self.config.get("start_with_windows", True)) or startup_enabled_now())

        self.gpm_entries = [entry.copy() for entry in self.config.get("gpm_entries", []) if isinstance(entry, dict)]
        self._refresh_gpm_tree()
        self.oi_entries = [entry.copy() for entry in self.config.get("oi_entries", []) if isinstance(entry, dict)]
        self._refresh_oi_tree()
        self.agreement_entries = [entry.copy() for entry in self.config.get("agreement_entries", []) if isinstance(entry, dict)]
        self._refresh_agreement_tree()

    def read_from_ui(self) -> dict:
        config = default_config()
        config["workspace_url"] = self.workspace_var.get().strip()
        config["browser"] = self.browser_var.get().strip() or "default"
        config["refresh_enabled"] = bool(self.refresh_enabled_var.get())
        config["refresh_minutes"] = max(1, int(self.refresh_minutes_var.get() or 1))
        config["workspace_close_seconds"] = max(1, int(self.workspace_close_seconds_var.get() or 1))
        config["start_with_windows"] = bool(self.startup_var.get())

        config["gpm_entries"] = []
        for index, entry in enumerate(self.gpm_entries):
            name = safe_name(entry.get("name", ""), f"GPM {index + 1}")
            url = normalize_mdm_url(entry.get("url", ""))
            hotkey = (entry.get("hotkey") or "").strip()
            if name or url or hotkey:
                config["gpm_entries"].append({"name": name, "url": url, "hotkey": hotkey})
        config["oi_entries"] = []
        for index, entry in enumerate(self.oi_entries):
            name = safe_name(entry.get("name", ""), f"OI {index + 1}")
            url = normalize_web_url(entry.get("url", ""))
            hotkey = (entry.get("hotkey") or "").strip()
            if name or url or hotkey:
                config["oi_entries"].append({"name": name, "url": url, "hotkey": hotkey})
        config["agreement_entries"] = []
        for index, entry in enumerate(self.agreement_entries):
            name = safe_name(entry.get("name", ""), f"합의 {index + 1}")
            url = normalize_web_url(entry.get("url", ""))
            hotkey = (entry.get("hotkey") or "").strip()
            if name or url or hotkey:
                config["agreement_entries"].append({"name": name, "url": url, "hotkey": hotkey})
        return config

    def save_from_ui(self, silent: bool = False) -> None:
        self.stop_hotkey_capture(restore_original=True)
        self.config = self.read_from_ui()
        save_config(self.config)
        try:
            set_startup(bool(self.config.get("start_with_windows", True)))
        except Exception as exc:
            messagebox.showwarning(APP_NAME, f"Windows 시작 등록 실패:\n{exc}")
        self.apply_runtime_settings(show_errors=False)
        if not silent:
            self.set_status("저장했습니다.")

    def apply_runtime_settings(self, show_errors: bool) -> None:
        self.configure_refresh_timer()
        self.restart_hotkeys(show_errors=show_errors)

    def configure_refresh_timer(self) -> None:
        if self.refresh_after_id:
            self.root.after_cancel(self.refresh_after_id)
            self.refresh_after_id = None
        if not self.config.get("refresh_enabled", True):
            return
        if not (self.config.get("workspace_url") or "").strip():
            return
        minutes = max(1, int(self.config.get("refresh_minutes", 210) or 210))
        self.refresh_after_id = self.root.after(minutes * 60 * 1000, self.refresh_workspace_timer)

    def refresh_workspace_timer(self) -> None:
        self.refresh_workspace(show_status=False)
        self.configure_refresh_timer()

    def restart_hotkeys(self, show_errors: bool) -> None:
        if self.hotkey_service:
            self.hotkey_service.stop()
        self.hotkey_service = HotkeyService(
            self.config,
            on_hotkey=lambda action: self.root.after(0, lambda: self.handle_hotkey_action(action)),
            on_errors=lambda errors: self.root.after(0, lambda: self.handle_hotkey_errors(errors, show_errors)),
        )
        self.hotkey_service.start()

    def handle_hotkey_action(self, action: str) -> None:
        if action.startswith("gpm:"):
            try:
                self.launch_gpm(int(action.split(":", 1)[1]))
            except ValueError:
                self.set_status("GPM 단축키 실행 대상을 찾지 못했습니다.")
        elif action.startswith("oi:"):
            try:
                self.launch_oi(int(action.split(":", 1)[1]))
            except ValueError:
                self.set_status("OI 단축키 실행 대상을 찾지 못했습니다.")
        elif action.startswith("agreement:"):
            try:
                self.launch_agreement(int(action.split(":", 1)[1]))
            except ValueError:
                self.set_status("합의 단축키 실행 대상을 찾지 못했습니다.")

    def handle_hotkey_errors(self, errors: list[str], show_errors: bool) -> None:
        self.set_status("일부 단축키 미등록: 이미 쓰는 조합이면 다른 키로 바꿔주세요.")
        if show_errors:
            messagebox.showwarning(APP_NAME, "단축키 확인:\n" + "\n".join(errors))

    def refresh_workspace(self, show_status: bool = True) -> None:
        try:
            close_seconds = max(1, int(self.config.get("workspace_close_seconds", 8) or 8))
            if open_workspace(self.config, minimized=True, auto_close_seconds=close_seconds):
                if show_status:
                    self.set_status(f"Workspace를 백그라운드로 갱신했습니다. 제한 시간 {close_seconds}초.")
            elif show_status:
                if (self.config.get("workspace_url") or "").strip():
                    self.set_status("Workspace 백그라운드 갱신에 실패했습니다. Workspace 열기로 로그인 상태를 확인하세요.")
                else:
                    self.set_status("Workspace 주소가 비어 있습니다.")
        except Exception as exc:
            if show_status:
                messagebox.showwarning(APP_NAME, f"Workspace 갱신 실패:\n{exc}")

    def refresh_workspace_from_ui(self) -> None:
        self.config = self.read_from_ui()
        self.refresh_workspace(show_status=True)

    def open_workspace_visible(self) -> None:
        self.config = self.read_from_ui()
        try:
            if open_workspace(self.config, minimized=False):
                self.set_status("Workspace를 열었습니다.")
            else:
                self.set_status("Workspace 주소가 비어 있습니다.")
        except Exception as exc:
            messagebox.showwarning(APP_NAME, f"Workspace 열기 실패:\n{exc}")

    def launch_env_from_ui(self, env_key: str) -> None:
        self.save_from_ui(silent=True)
        self.launch_env(env_key)

    def launch_gpm(self, index: int) -> None:
        try:
            self.config = self.read_from_ui()
            save_config(self.config)
            result = launch_gpm_entry(self.config, index)
            name = self.config.get("gpm_entries", [])[index].get("name", f"GPM {index + 1}")
            if result == "focused":
                self.set_status(f"GPM {name} 창을 앞으로 가져왔습니다.")
            else:
                self.set_status(f"GPM {name} 실행 요청을 보냈습니다.")
        except Exception as exc:
            messagebox.showwarning(APP_NAME, f"GPM 실행 실패:\n{exc}")

    def launch_env(self, env_key: str) -> None:
        try:
            result = launch_environment(self.config, env_key)
            index = resolve_entry_index(self.config.get("gpm_entries", []), env_key, {"mem": "memory"})
            label = self.config.get("gpm_entries", [])[index].get("name", env_key) if index is not None else env_key
            if result == "focused":
                self.set_status(f"{label} 창을 앞으로 가져왔습니다.")
            else:
                self.set_status(f"{label} 실행 요청을 보냈습니다.")
        except Exception as exc:
            messagebox.showwarning(APP_NAME, str(exc))

    def launch_oi(self, index: int) -> None:
        try:
            self.config = self.read_from_ui()
            save_config(self.config)
            result = launch_oi_entry(self.config, index)
            name = self.config.get("oi_entries", [])[index].get("name", f"OI {index + 1}")
            if result == "focused":
                self.set_status(f"OI {name} 창을 앞으로 가져왔습니다.")
            else:
                self.set_status(f"OI {name} 실행 요청을 보냈습니다.")
        except Exception as exc:
            messagebox.showwarning(APP_NAME, f"OI 실행 실패:\n{exc}")

    def launch_agreement(self, index: int) -> None:
        try:
            self.config = self.read_from_ui()
            save_config(self.config)
            result = launch_agreement_entry(self.config, index)
            name = self.config.get("agreement_entries", [])[index].get("name", f"합의 {index + 1}")
            if result == "focused":
                self.set_status(f"합의 {name} 창을 앞으로 가져왔습니다.")
            else:
                self.set_status(f"합의 {name} 실행 요청을 보냈습니다.")
        except Exception as exc:
            messagebox.showwarning(APP_NAME, f"합의 실행 실패:\n{exc}")

    def create_icons(self) -> None:
        self.save_from_ui(silent=True)
        try:
            created = create_desktop_shortcuts(self.config)
            names = "\n".join(path.name for path in created)
            if names:
                messagebox.showinfo(APP_NAME, f"바탕화면 아이콘을 만들었습니다.\n\n{names}")
                self.set_status("바탕화면 아이콘을 만들었습니다.")
            else:
                self.set_status("아이콘을 만들 GPM 주소가 없습니다.")
        except Exception as exc:
            messagebox.showwarning(APP_NAME, f"아이콘 생성 실패:\n{exc}")

    def hide_to_tray(self, show_warning: bool = True, force: bool = False) -> None:
        if self.tray_icon and self.tray_icon.show():
            self.root.withdraw()
            return
        if force:
            self.root.withdraw()
            return
        if show_warning:
            messagebox.showwarning(APP_NAME, "트레이 아이콘을 만들 수 없습니다.")

    def show_from_tray(self) -> None:
        if self.tray_icon:
            self.tray_icon.hide()
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.after(50, self.root.focus_force)

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def quit(self) -> None:
        if self.tray_icon:
            self.tray_icon.destroy()
            self.tray_icon = None
        if self.refresh_after_id:
            self.root.after_cancel(self.refresh_after_id)
        if self.hotkey_service:
            self.hotkey_service.stop()
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def show_windows_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)


def close_other_gui_instances() -> None:
    current_pid = os.getpid()
    if getattr(sys, "frozen", False):
        executable = str(Path(sys.executable).resolve())
        script = (
            "$target = " + ps_quote(executable) + "\n"
            "$current = " + str(current_pid) + "\n"
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.ProcessId -ne $current -and $_.ExecutablePath -eq $target } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
    else:
        script_path = str(Path(__file__).resolve())
        script = (
            "$needle = " + ps_quote(script_path) + "\n"
            "$current = " + str(current_pid) + "\n"
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.ProcessId -ne $current -and $_.CommandLine -like ('*' + $needle + '*') } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def run_cli(args: argparse.Namespace) -> int:
    config = load_config()
    try:
        if args.refresh_only:
            close_seconds = max(1, int(config.get("workspace_close_seconds", 8) or 8))
            open_workspace(config, minimized=True, auto_close_seconds=close_seconds)
            return 0
        if args.launch:
            index = resolve_entry_index(config.get("gpm_entries", []), args.launch, {"mem": "memory"})
            if index is None:
                raise ValueError(f"Unknown GPM entry: {args.launch}")
            launch_gpm_entry(config, index)
            return 0
        if args.launch_oi:
            target = args.launch_oi.strip()
            entries = config.get("oi_entries", [])
            selected_index = resolve_entry_index(entries, target)
            if selected_index is None:
                raise ValueError(f"Unknown OI entry: {args.launch_oi}")
            launch_oi_entry(config, selected_index)
            return 0
        if args.launch_agreement:
            target = args.launch_agreement.strip()
            entries = config.get("agreement_entries", [])
            selected_index = resolve_entry_index(entries, target)
            if selected_index is None:
                raise ValueError(f"Unknown agreement entry: {args.launch_agreement}")
            launch_agreement_entry(config, selected_index)
            return 0
    except Exception as exc:
        show_windows_error(str(exc))
        return 1
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--launch", help="Launch a configured GPM entry by name or index.")
    parser.add_argument("--launch-oi", help="Launch a configured OI entry by name or index.")
    parser.add_argument("--launch-agreement", help="Launch a configured agreement entry by name or index.")
    parser.add_argument("--refresh-only", action="store_true", help="Refresh workspace session and exit.")
    parser.add_argument("--background", action="store_true", help="Start hidden in the background.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.launch or args.launch_oi or args.launch_agreement or args.refresh_only:
        return run_cli(args)
    close_other_gui_instances()
    return LauncherApp(background=args.background).run()


if __name__ == "__main__":
    raise SystemExit(main())
