import argparse
import ctypes
from ctypes import wintypes
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
LEGACY_CONFIG_PATH = Path(__file__).resolve().parent / "gpm-launcher.config.json"
HOTKEY_BASE_ID = 0x4700
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
CREATE_NO_WINDOW = 0x08000000
SW_SHOWNORMAL = 1
SW_SHOWMINNOACTIVE = 7

ENVIRONMENTS = [
    {"key": "NRD", "label": "NRD", "shortcut": "NRD GPM"},
    {"key": "MEMORY", "label": "MEMORY", "shortcut": "MEM GPM"},
    {"key": "NRDK", "label": "NRDK", "shortcut": "NRDK GPM"},
]

DEFAULT_HOTKEYS = {
    "NRD": "Ctrl+Alt+Shift+N",
    "MEMORY": "Ctrl+Alt+Shift+M",
    "NRDK": "Ctrl+Alt+Shift+K",
}

OLD_DEFAULT_HOTKEYS = {
    "NRD": "Ctrl+Alt+1",
    "MEMORY": "Ctrl+Alt+2",
    "NRDK": "Ctrl+Alt+3",
}


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


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
shell32.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
shell32.ShellExecuteW.restype = ctypes.c_void_p


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def default_config() -> dict:
    return {
        "workspace_url": "",
        "browser": "default",
        "warmup_seconds": 7,
        "workspace_close_seconds": 8,
        "refresh_minutes": 210,
        "refresh_enabled": True,
        "start_with_windows": True,
        "mdm": {
            env["key"]: {
                "url": "",
                "hotkey": DEFAULT_HOTKEYS[env["key"]],
            }
            for env in ENVIRONMENTS
        },
    }


def merge_config(target: dict, saved: dict) -> None:
    for key in ("workspace_url", "browser", "warmup_seconds", "workspace_close_seconds", "refresh_minutes", "refresh_enabled", "start_with_windows"):
        if key in saved:
            target[key] = saved[key]

    saved_mdm = saved.get("mdm", {})
    if isinstance(saved_mdm, dict):
        for env in ENVIRONMENTS:
            env_key = env["key"]
            if isinstance(saved_mdm.get(env_key), dict):
                target["mdm"][env_key].update(saved_mdm[env_key])
                if target["mdm"][env_key].get("hotkey") == OLD_DEFAULT_HOTKEYS[env_key]:
                    target["mdm"][env_key]["hotkey"] = DEFAULT_HOTKEYS[env_key]


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
                config["mdm"]["NRD"]["url"] = legacy_curl
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


def open_workspace(config: dict, minimized: bool = True, auto_close_seconds: int | None = None) -> bool:
    url = (config.get("workspace_url") or "").strip()
    if not url:
        return False

    browser_path = resolve_browser_path(config.get("browser") or "default")
    if browser_path:
        args = []
        if auto_close_seconds and auto_close_seconds > 0:
            profile_dir = CONFIG_DIR / "workspace-refresh-profile"
            profile_dir.mkdir(parents=True, exist_ok=True)
            args.extend([
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--disable-default-browser-check",
                f"--app={url}",
            ])
        else:
            args.append("--new-window")
            args.append(url)
        if minimized and not (auto_close_seconds and auto_close_seconds > 0):
            args.append("--start-minimized")
        process = subprocess.Popen([browser_path, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if auto_close_seconds and auto_close_seconds > 0:
            close_process_tree_later(process, auto_close_seconds)
        return True

    shell_open(url, SW_SHOWMINNOACTIVE if minimized else SW_SHOWNORMAL)
    return True


def launch_mdm_url(url: str) -> None:
    normalized = normalize_mdm_url(url)
    if not normalized:
        raise ValueError("MDM 주소가 비어 있습니다.")
    shell_open(normalized, SW_SHOWNORMAL)


def launch_environment(config: dict, env_key: str) -> None:
    env_config = config.get("mdm", {}).get(env_key, {})
    mdm_url = normalize_mdm_url(env_config.get("url", ""))
    if not mdm_url:
        raise ValueError(f"{env_key} MDM 주소가 비어 있습니다.")
    launch_mdm_url(mdm_url)


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
        return str(Path(sys.executable).resolve())
    ico = app_base_dir() / "assets" / "gpm_launcher.ico"
    if ico.exists():
        return str(ico)
    return str(Path(sys.executable).resolve())


def launch_command_for_env(env_key: str) -> tuple[str, str, str]:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), f"--launch {env_key}", str(app_base_dir())
    return pythonw_path(), f'"{Path(__file__).resolve()}" --launch {env_key}', str(app_base_dir())


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


def create_desktop_shortcuts() -> list[Path]:
    desktop = get_desktop_path()
    desktop.mkdir(parents=True, exist_ok=True)
    created = []
    for env in ENVIRONMENTS:
        target, args, working_dir = launch_command_for_env(env["key"])
        shortcut = desktop / f"{env['shortcut']}.lnk"
        create_shortcut(shortcut, target, args, working_dir, icon_location())
        created.append(shortcut)
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
            for index, env in enumerate(ENVIRONMENTS):
                env_key = env["key"]
                env_config = self.config.get("mdm", {}).get(env_key, {})
                if not (env_config.get("url") or "").strip():
                    continue
                hotkey = (env_config.get("hotkey") or "").strip()
                if not hotkey:
                    continue
                try:
                    modifiers, vk = hotkey_to_native(hotkey)
                except ValueError as exc:
                    errors.append(f"{env['label']}: {exc}")
                    continue
                hotkey_id = HOTKEY_BASE_ID + index
                if user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
                    registered[hotkey_id] = env_key
                else:
                    errors.append(f"{env['label']}: 단축키 등록 실패 ({hotkey})")

            if errors:
                self.on_errors(errors)
            self.ready.set()

            msg = MSG()
            while not self.stopping.is_set() and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY:
                    env_key = registered.get(int(msg.wParam))
                    if env_key:
                        self.on_hotkey(env_key)
        finally:
            for hotkey_id in registered:
                user32.UnregisterHotKey(None, hotkey_id)
            self.ready.set()


class LauncherApp:
    def __init__(self, background: bool = False) -> None:
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("760x520")
        self.root.minsize(700, 480)
        ico = app_base_dir() / "assets" / "gpm_launcher.ico"
        if ico.exists():
            try:
                self.root.iconbitmap(str(ico))
            except tk.TclError:
                pass

        self.config = load_config()
        self.hotkey_service: HotkeyService | None = None
        self.refresh_after_id: str | None = None
        self.url_vars: dict[str, tk.StringVar] = {}
        self.hotkey_vars: dict[str, tk.StringVar] = {}

        self._build_ui()
        self._load_config_to_ui()
        self.apply_runtime_settings(show_errors=False)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        if background:
            self.root.withdraw()
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
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        self._build_workspace_frame(body)
        self._build_mdm_frame(body)
        self._build_button_row(outer)

        self.status_var = tk.StringVar(value="준비됨")
        status = ttk.Label(outer, textvariable=self.status_var, anchor="w")
        status.grid(row=3, column=0, sticky="ew", pady=(8, 0))

    def _build_workspace_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Workspace", padding=10)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
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
        ttk.Label(refresh_row, text="닫기").pack(side="left", padx=(10, 4))
        tk.Spinbox(refresh_row, from_=1, to=120, increment=1, width=5, textvariable=self.workspace_close_seconds_var).pack(side="left")
        ttk.Label(refresh_row, text="초").pack(side="left", padx=(4, 0))
        ttk.Button(refresh_row, text="지금 갱신", command=self.refresh_workspace_from_ui).pack(side="left", padx=(12, 0))
        ttk.Button(refresh_row, text="Workspace 열기", command=self.open_workspace_visible).pack(side="left", padx=(6, 0))

        ttk.Checkbutton(frame, text="Windows 시작 시 백그라운드 실행", variable=self.startup_var).grid(row=3, column=1, sticky="w", pady=3)

    def _build_mdm_frame(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="GPM", padding=10)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="구분").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(frame, text="MDM 주소").grid(row=0, column=1, sticky="w")
        ttk.Label(frame, text="단축키").grid(row=0, column=2, sticky="w", padx=(8, 0))

        for row, env in enumerate(ENVIRONMENTS, start=1):
            env_key = env["key"]
            self.url_vars[env_key] = tk.StringVar()
            self.hotkey_vars[env_key] = tk.StringVar()

            ttk.Label(frame, text=env["label"]).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=5)
            entry = ttk.Entry(frame, textvariable=self.url_vars[env_key])
            entry.grid(row=row, column=1, sticky="ew", pady=5)
            self._bind_auto_normalize(entry, self.url_vars[env_key])
            ttk.Entry(frame, textvariable=self.hotkey_vars[env_key], width=16).grid(row=row, column=2, sticky="w", padx=(8, 0), pady=5)
            ttk.Button(frame, text="실행", command=lambda key=env_key: self.launch_env_from_ui(key)).grid(row=row, column=3, sticky="w", padx=(8, 0), pady=5)

        hint = ttk.Label(frame, text="GPM 임시 주소나 curl://launch/... 주소를 붙여넣으면 자동으로 실행 주소만 정리합니다.", foreground="#555")
        hint.grid(row=len(ENVIRONMENTS) + 1, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def _build_button_row(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent)
        row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        row.columnconfigure(0, weight=1)
        ttk.Button(row, text="저장 / 적용", command=self.save_from_ui).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(row, text="바탕화면 아이콘 생성", command=self.create_icons).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(row, text="숨기기", command=self.root.withdraw).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(row, text="종료", command=self.quit).grid(row=0, column=4)

    def _bind_auto_normalize(self, entry: ttk.Entry, var: tk.StringVar) -> None:
        def normalize_later(_event=None) -> None:
            self.root.after(80, lambda: self._normalize_var(var))

        entry.bind("<<Paste>>", normalize_later)
        entry.bind("<Control-v>", normalize_later)
        entry.bind("<FocusOut>", normalize_later)

    def _normalize_var(self, var: tk.StringVar) -> None:
        before = var.get()
        after = normalize_mdm_url(before)
        if after != before:
            var.set(after)
            self.set_status("주소를 curl 실행 주소로 정리했습니다.")

    def _load_config_to_ui(self) -> None:
        self.workspace_var.set(self.config.get("workspace_url", ""))
        self.browser_var.set(self.config.get("browser", "default") or "default")
        self.refresh_enabled_var.set(bool(self.config.get("refresh_enabled", True)))
        self.refresh_minutes_var.set(max(1, int(self.config.get("refresh_minutes", 210) or 210)))
        self.workspace_close_seconds_var.set(max(1, int(self.config.get("workspace_close_seconds", 8) or 8)))
        self.startup_var.set(bool(self.config.get("start_with_windows", True)) or startup_enabled_now())

        for env in ENVIRONMENTS:
            env_key = env["key"]
            env_config = self.config.get("mdm", {}).get(env_key, {})
            self.url_vars[env_key].set(env_config.get("url", ""))
            self.hotkey_vars[env_key].set(env_config.get("hotkey", DEFAULT_HOTKEYS[env_key]))

    def read_from_ui(self) -> dict:
        config = default_config()
        config["workspace_url"] = self.workspace_var.get().strip()
        config["browser"] = self.browser_var.get().strip() or "default"
        config["refresh_enabled"] = bool(self.refresh_enabled_var.get())
        config["refresh_minutes"] = max(1, int(self.refresh_minutes_var.get() or 1))
        config["workspace_close_seconds"] = max(1, int(self.workspace_close_seconds_var.get() or 1))
        config["start_with_windows"] = bool(self.startup_var.get())

        for env in ENVIRONMENTS:
            env_key = env["key"]
            normalized = normalize_mdm_url(self.url_vars[env_key].get())
            self.url_vars[env_key].set(normalized)
            config["mdm"][env_key]["url"] = normalized
            config["mdm"][env_key]["hotkey"] = self.hotkey_vars[env_key].get().strip()
        return config

    def save_from_ui(self, silent: bool = False) -> None:
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
            on_hotkey=lambda key: self.root.after(0, lambda: self.launch_env(key)),
            on_errors=lambda errors: self.root.after(0, lambda: self.handle_hotkey_errors(errors, show_errors)),
        )
        self.hotkey_service.start()

    def handle_hotkey_errors(self, errors: list[str], show_errors: bool) -> None:
        self.set_status("일부 단축키 미등록: 이미 쓰는 조합이면 다른 키로 바꿔주세요.")
        if show_errors:
            messagebox.showwarning(APP_NAME, "단축키 확인:\n" + "\n".join(errors))

    def refresh_workspace(self, show_status: bool = True) -> None:
        try:
            close_seconds = max(1, int(self.config.get("workspace_close_seconds", 8) or 8))
            if open_workspace(self.config, minimized=True, auto_close_seconds=close_seconds):
                if show_status:
                    self.set_status(f"Workspace 갱신 창을 열고 {close_seconds}초 뒤 닫습니다.")
            elif show_status:
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

    def launch_env(self, env_key: str) -> None:
        try:
            launch_environment(self.config, env_key)
            label = next(env["label"] for env in ENVIRONMENTS if env["key"] == env_key)
            self.set_status(f"{label} 실행 요청을 보냈습니다.")
        except Exception as exc:
            messagebox.showwarning(APP_NAME, str(exc))

    def create_icons(self) -> None:
        self.save_from_ui(silent=True)
        try:
            created = create_desktop_shortcuts()
            names = "\n".join(path.name for path in created)
            messagebox.showinfo(APP_NAME, f"바탕화면 아이콘을 만들었습니다.\n\n{names}")
            self.set_status("바탕화면 아이콘을 만들었습니다.")
        except Exception as exc:
            messagebox.showwarning(APP_NAME, f"아이콘 생성 실패:\n{exc}")

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def quit(self) -> None:
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
            env_key = args.launch.upper()
            if env_key == "MEM":
                env_key = "MEMORY"
            allowed = {env["key"] for env in ENVIRONMENTS}
            if env_key not in allowed:
                raise ValueError(f"Unknown environment: {args.launch}")
            launch_environment(config, env_key)
            return 0
    except Exception as exc:
        show_windows_error(str(exc))
        return 1
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--launch", choices=["NRD", "MEM", "MEMORY", "NRDK", "nrd", "mem", "memory", "nrdk"], help="Launch a configured GPM environment.")
    parser.add_argument("--refresh-only", action="store_true", help="Refresh workspace session and exit.")
    parser.add_argument("--background", action="store_true", help="Start hidden in the background.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.launch or args.refresh_only:
        return run_cli(args)
    close_other_gui_instances()
    return LauncherApp(background=args.background).run()


if __name__ == "__main__":
    raise SystemExit(main())
