import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import parse_qs, unquote, urlparse
import winreg

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
    QKeySequenceEdit,
)


APP_NAME = "GPM Launcher"
APP_REG_NAME = "GPMLauncher"
CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "GPM Launcher"
CONFIG_PATH = CONFIG_DIR / "config.json"
LEGACY_CONFIG_PATH = Path(__file__).resolve().parent / "gpm-launcher.config.json"
HOTKEY_BASE_ID = 0x4700
WM_HOTKEY = 0x0312
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
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
shell32 = ctypes.windll.shell32
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


def normalize_mdm_url(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    lowered = text.lower()
    if lowered.startswith("curl://launch/"):
        return text

    parsed = urlparse(text)
    query = parse_qs(parsed.query)
    if "next" in query and query["next"]:
        return unquote(query["next"][0]).strip()

    index = lowered.find("curl://launch/")
    if index >= 0:
        candidate = text[index:]
        amp = candidate.find("&")
        if amp >= 0:
            candidate = candidate[:amp]
        return unquote(candidate).strip()

    if lowered.startswith(("http://", "https://")) and lowered.endswith((".dcurl", ".curl")):
        return "curl://launch/" + text

    return text


def load_config() -> dict:
    config = default_config()
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            merge_config(config, saved)
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


def merge_config(target: dict, saved: dict) -> None:
    for key in ("workspace_url", "browser", "warmup_seconds", "refresh_minutes", "refresh_enabled", "start_with_windows"):
        if key in saved:
            target[key] = saved[key]

    saved_mdm = saved.get("mdm", {})
    if isinstance(saved_mdm, dict):
        for env in ENVIRONMENTS:
            env_key = env["key"]
            if env_key in saved_mdm and isinstance(saved_mdm[env_key], dict):
                target["mdm"][env_key].update(saved_mdm[env_key])


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def show_windows_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)


def resolve_browser_path(browser: str) -> str | None:
    browser = (browser or "default").lower()
    candidates: list[str] = []
    if browser == "edge":
        candidates = [
            rf"{os.environ.get('ProgramFiles(x86)', '')}\Microsoft\Edge\Application\msedge.exe",
            rf"{os.environ.get('ProgramFiles', '')}\Microsoft\Edge\Application\msedge.exe",
            rf"{os.environ.get('LOCALAPPDATA', '')}\Microsoft\Edge\Application\msedge.exe",
        ]
    elif browser == "chrome":
        candidates = [
            rf"{os.environ.get('ProgramFiles', '')}\Google\Chrome\Application\chrome.exe",
            rf"{os.environ.get('ProgramFiles(x86)', '')}\Google\Chrome\Application\chrome.exe",
            rf"{os.environ.get('LOCALAPPDATA', '')}\Google\Chrome\Application\chrome.exe",
        ]

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def open_workspace(config: dict, minimized: bool = True) -> bool:
    url = (config.get("workspace_url") or "").strip()
    if not url:
        return False

    browser = (config.get("browser") or "default").lower()
    browser_path = resolve_browser_path(browser)
    if browser_path:
        args = ["--new-window"]
        if minimized:
            args.append("--start-minimized")
        args.append(url)
        subprocess.Popen(args=[browser_path, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    shell_open(url, SW_SHOWMINNOACTIVE if minimized else SW_SHOWNORMAL)
    return True


def launch_mdm_url(url: str) -> None:
    normalized = normalize_mdm_url(url)
    if not normalized:
        raise ValueError("MDM 주소가 비어 있습니다.")
    shell_open(normalized, SW_SHOWNORMAL)


def shell_open(target: str, show_command: int) -> None:
    result = shell32.ShellExecuteW(None, "open", target, None, None, show_command)
    value = int(result or 0)
    if value <= 32:
        raise OSError(f"ShellExecute failed ({value}): {target}")


def launch_environment(config: dict, env_key: str, include_workspace: bool = True, wait: bool = True) -> None:
    env_config = config.get("mdm", {}).get(env_key, {})
    mdm_url = normalize_mdm_url(env_config.get("url", ""))
    if not mdm_url:
        raise ValueError(f"{env_key} MDM 주소가 비어 있습니다.")

    if include_workspace and (config.get("workspace_url") or "").strip():
        open_workspace(config, minimized=True)
        delay = int(config.get("warmup_seconds", 7) or 0)
        if delay > 0 and wait:
            time.sleep(delay)

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


def launch_command_for_env(env_key: str) -> tuple[str, str, str]:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), f"--launch {env_key}", str(app_base_dir())
    return pythonw_path(), f'"{Path(__file__).resolve()}" --launch {env_key}', str(app_base_dir())


def icon_location() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve())
    ico = app_base_dir() / "assets" / "gpm_launcher.ico"
    if ico.exists():
        return str(ico)
    return str(Path(sys.executable).resolve())


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
    created: list[Path] = []
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


def hotkey_to_native(sequence: str) -> tuple[int, int]:
    text = (sequence or "").strip()
    if not text:
        raise ValueError("단축키가 비어 있습니다.")

    text = text.split(",", 1)[0].replace(" ", "")
    parts = [part for part in text.split("+") if part]
    if not parts:
        raise ValueError("단축키가 비어 있습니다.")

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
        elif token in ("META", "WIN", "WINDOWS"):
            modifiers |= MOD_WIN
        else:
            key_token = token

    if not key_token:
        raise ValueError("단축키에 실행 키가 없습니다.")

    vk = virtual_key_for_token(key_token)
    if vk is None:
        raise ValueError(f"지원하지 않는 키입니다: {key_token}")
    if modifiers == MOD_NOREPEAT:
        raise ValueError("Ctrl, Alt, Shift, Win 중 하나 이상을 같이 지정하세요.")
    return modifiers, vk


def virtual_key_for_token(token: str) -> int | None:
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


class HotkeyEventFilter(QAbstractNativeEventFilter):
    def __init__(self, manager: "HotkeyManager") -> None:
        super().__init__()
        self.manager = manager

    def nativeEventFilter(self, event_type, message):
        if event_type not in ("windows_generic_MSG", "windows_dispatcher_MSG"):
            return False, 0
        try:
            msg = MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.message == WM_HOTKEY:
            self.manager.handle_hotkey(int(msg.wParam))
            return True, 0
        return False, 0


class HotkeyManager(QObject):
    hotkey_pressed = Signal(str)

    def __init__(self, sink: QWidget) -> None:
        super().__init__()
        self.sink = sink
        self.hwnd = wintypes.HWND(int(sink.winId()))
        self.registered: dict[int, str] = {}
        self.filter = HotkeyEventFilter(self)
        QCoreApplication.instance().installNativeEventFilter(self.filter)

    def register_config(self, config: dict) -> list[str]:
        self.unregister_all()
        errors: list[str] = []
        for index, env in enumerate(ENVIRONMENTS):
            env_key = env["key"]
            env_config = config.get("mdm", {}).get(env_key, {})
            if not (env_config.get("url") or "").strip():
                continue
            hotkey = (env_config.get("hotkey") or "").strip()
            if not hotkey:
                continue
            hotkey_id = HOTKEY_BASE_ID + index
            try:
                modifiers, vk = hotkey_to_native(hotkey)
            except ValueError as exc:
                errors.append(f"{env['label']}: {exc}")
                continue
            if user32.RegisterHotKey(self.hwnd, hotkey_id, modifiers, vk):
                self.registered[hotkey_id] = env_key
            else:
                errors.append(f"{env['label']}: 단축키 등록 실패 ({hotkey})")
        return errors

    def unregister_all(self) -> None:
        for hotkey_id in list(self.registered):
            user32.UnregisterHotKey(self.hwnd, hotkey_id)
        self.registered.clear()

    def handle_hotkey(self, hotkey_id: int) -> None:
        env_key = self.registered.get(hotkey_id)
        if env_key:
            self.hotkey_pressed.emit(env_key)


def make_app_icon() -> QIcon:
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#1b5eaa"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(8, 8, 112, 112, 22, 22)
    painter.setBrush(QColor("#28a36a"))
    painter.drawRect(8, 82, 112, 38)
    painter.setPen(QColor("white"))
    font = QFont("Segoe UI", 46, QFont.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "G")
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    def __init__(self, start_minimized: bool = False) -> None:
        super().__init__()
        self.config = load_config()
        self.icon = make_app_icon()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self.icon)
        self.resize(900, 680)
        self.setMinimumSize(820, 560)
        self.env_widgets: dict[str, dict[str, object]] = {}
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_workspace)
        self.pending_launch_timers: list[QTimer] = []

        self.hotkey_sink = QWidget()
        self.hotkey_sink.setAttribute(Qt.WA_NativeWindow, True)
        self.hotkey_manager = HotkeyManager(self.hotkey_sink)
        self.hotkey_manager.hotkey_pressed.connect(self.launch_env_from_hotkey)

        self.build_ui()
        self.build_tray()
        self.load_into_ui()
        self.apply_runtime_settings(show_errors=False)

        if start_minimized:
            self.hide()
            if self.config.get("refresh_enabled", True):
                QTimer.singleShot(2500, self.refresh_workspace)
        else:
            self.show()

    def build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 12)
        root.setSpacing(14)

        title = QLabel("GPM Launcher")
        title.setObjectName("title")
        subtitle = QLabel("NRD, MEMORY, NRDK 접속 주소와 전역 단축키를 관리합니다.")
        subtitle.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)

        body.addWidget(self.workspace_group())
        body.addWidget(self.mdm_group())
        body.addWidget(self.actions_group())
        body.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        self.save_button = QPushButton("저장 / 적용")
        self.save_button.clicked.connect(self.save_from_ui)
        self.hide_button = QPushButton("트레이로 숨기기")
        self.hide_button.clicked.connect(self.hide_to_tray)
        self.quit_button = QPushButton("종료")
        self.quit_button.clicked.connect(self.quit_app)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.hide_button)
        buttons.addWidget(self.quit_button)
        root.addLayout(buttons)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.apply_style()

    def workspace_group(self) -> QGroupBox:
        group = QGroupBox("Workspace")
        layout = QFormLayout(group)
        layout.setLabelAlignment(Qt.AlignRight)
        layout.setFormAlignment(Qt.AlignTop)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        self.workspace_edit = QLineEdit()
        self.workspace_edit.setPlaceholderText("https://workspace...")
        self.browser_combo = QComboBox()
        self.browser_combo.addItem("Microsoft Edge", "edge")
        self.browser_combo.addItem("Google Chrome", "chrome")
        self.browser_combo.addItem("기본 브라우저", "default")

        self.refresh_enabled_check = QCheckBox("자동 갱신")
        self.refresh_minutes_spin = QSpinBox()
        self.refresh_minutes_spin.setRange(15, 720)
        self.refresh_minutes_spin.setSuffix("분")
        self.refresh_minutes_spin.setSingleStep(15)
        self.warmup_seconds_spin = QSpinBox()
        self.warmup_seconds_spin.setRange(0, 60)
        self.warmup_seconds_spin.setSuffix("초")

        refresh_row = QHBoxLayout()
        refresh_row.addWidget(self.refresh_enabled_check)
        refresh_row.addWidget(self.refresh_minutes_spin)
        refresh_row.addStretch(1)

        self.startup_check = QCheckBox("Windows 시작 시 백그라운드 실행")

        self.refresh_now_button = QPushButton("Workspace 갱신")
        self.refresh_now_button.clicked.connect(self.refresh_workspace_from_ui)
        self.open_workspace_button = QPushButton("Workspace 열기")
        self.open_workspace_button.clicked.connect(self.open_workspace_visible)
        workspace_buttons = QHBoxLayout()
        workspace_buttons.addWidget(self.refresh_now_button)
        workspace_buttons.addWidget(self.open_workspace_button)
        workspace_buttons.addStretch(1)

        layout.addRow("주소", self.workspace_edit)
        layout.addRow("브라우저", self.browser_combo)
        layout.addRow("갱신 간격", refresh_row)
        layout.addRow("GPM 실행 대기", self.warmup_seconds_spin)
        layout.addRow("", self.startup_check)
        layout.addRow("", workspace_buttons)
        return group

    def mdm_group(self) -> QGroupBox:
        group = QGroupBox("MDM")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("구분"), 0, 0)
        grid.addWidget(QLabel("MDM 주소"), 0, 1)
        grid.addWidget(QLabel("단축키"), 0, 2)
        grid.addWidget(QLabel("실행"), 0, 3)
        grid.setColumnStretch(1, 1)

        for row, env in enumerate(ENVIRONMENTS, start=1):
            label = QLabel(env["label"])
            url_edit = QLineEdit()
            url_edit.setPlaceholderText("curl://launch/... 또는 .../start.dcurl")
            hotkey_edit = QKeySequenceEdit()
            try:
                hotkey_edit.setMaximumSequenceLength(1)
            except AttributeError:
                pass
            launch_button = QPushButton("실행")
            launch_button.clicked.connect(lambda checked=False, key=env["key"]: self.launch_env_from_ui(key))
            grid.addWidget(label, row, 0)
            grid.addWidget(url_edit, row, 1)
            grid.addWidget(hotkey_edit, row, 2)
            grid.addWidget(launch_button, row, 3)
            self.env_widgets[env["key"]] = {
                "url": url_edit,
                "hotkey": hotkey_edit,
                "launch": launch_button,
            }
        return group

    def actions_group(self) -> QGroupBox:
        group = QGroupBox("Icons")
        layout = QHBoxLayout(group)
        self.create_icons_button = QPushButton("바탕화면 아이콘 생성")
        self.create_icons_button.clicked.connect(self.create_icons)
        layout.addWidget(self.create_icons_button)
        layout.addStretch(1)
        return group

    def build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.icon, self)
        menu = QMenu()
        show_action = QAction("설정 열기", self)
        show_action.triggered.connect(self.show_window)
        menu.addAction(show_action)
        menu.addSeparator()
        for env in ENVIRONMENTS:
            action = QAction(f"{env['label']} 실행", self)
            action.triggered.connect(lambda checked=False, key=env["key"]: self.launch_env_from_hotkey(key))
            menu.addAction(action)
        menu.addSeparator()
        refresh_action = QAction("Workspace 갱신", self)
        refresh_action.triggered.connect(self.refresh_workspace)
        quit_action = QAction("종료", self)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(refresh_action)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    def apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f6f7f9; color: #20242a; font-family: "Segoe UI"; font-size: 10pt; }
            QLabel#title { font-size: 22pt; font-weight: 700; color: #12233a; }
            QLabel#subtitle { color: #586172; margin-bottom: 6px; }
            QGroupBox { background: #ffffff; border: 1px solid #d8dde5; border-radius: 8px; margin-top: 12px; padding: 16px 12px 12px 12px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #243247; }
            QLineEdit, QComboBox, QSpinBox, QKeySequenceEdit { background: white; border: 1px solid #c8cfda; border-radius: 5px; min-height: 28px; padding: 2px 6px; }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QKeySequenceEdit:focus { border-color: #1b5eaa; }
            QPushButton { background: #1b5eaa; color: white; border: 0; border-radius: 5px; padding: 7px 13px; min-height: 26px; }
            QPushButton:hover { background: #174f91; }
            QPushButton:pressed { background: #123f76; }
            QPushButton#secondary { background: #657083; }
            QCheckBox { spacing: 8px; }
            """
        )

    def load_into_ui(self) -> None:
        config = self.config
        self.workspace_edit.setText(config.get("workspace_url", ""))
        browser = (config.get("browser") or "default").lower()
        index = self.browser_combo.findData(browser)
        self.browser_combo.setCurrentIndex(index if index >= 0 else 0)
        self.refresh_enabled_check.setChecked(bool(config.get("refresh_enabled", True)))
        self.refresh_minutes_spin.setValue(int(config.get("refresh_minutes", 210) or 210))
        self.warmup_seconds_spin.setValue(int(config.get("warmup_seconds", 7) or 7))
        self.startup_check.setChecked(bool(config.get("start_with_windows", True)) or startup_enabled_now())

        for env in ENVIRONMENTS:
            env_key = env["key"]
            env_config = config.get("mdm", {}).get(env_key, {})
            widgets = self.env_widgets[env_key]
            widgets["url"].setText(env_config.get("url", ""))  # type: ignore[attr-defined]
            hotkey = env_config.get("hotkey", DEFAULT_HOTKEYS[env_key])
            widgets["hotkey"].setKeySequence(QKeySequence(hotkey))  # type: ignore[attr-defined]

    def read_from_ui(self) -> dict:
        config = default_config()
        config["workspace_url"] = self.workspace_edit.text().strip()
        config["browser"] = self.browser_combo.currentData()
        config["refresh_enabled"] = self.refresh_enabled_check.isChecked()
        config["refresh_minutes"] = self.refresh_minutes_spin.value()
        config["warmup_seconds"] = self.warmup_seconds_spin.value()
        config["start_with_windows"] = self.startup_check.isChecked()

        for env in ENVIRONMENTS:
            env_key = env["key"]
            widgets = self.env_widgets[env_key]
            hotkey_sequence = widgets["hotkey"].keySequence().toString(QKeySequence.NativeText)  # type: ignore[attr-defined]
            config["mdm"][env_key]["url"] = normalize_mdm_url(widgets["url"].text())  # type: ignore[attr-defined]
            config["mdm"][env_key]["hotkey"] = hotkey_sequence
        return config

    def save_from_ui(self) -> None:
        self.config = self.read_from_ui()
        save_config(self.config)
        try:
            set_startup(bool(self.config.get("start_with_windows", True)))
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Windows 시작 등록 실패:\n{exc}")
        self.apply_runtime_settings(show_errors=True)
        self.statusBar().showMessage("저장했습니다.", 4000)

    def apply_runtime_settings(self, show_errors: bool) -> None:
        errors = self.hotkey_manager.register_config(self.config)
        if errors and show_errors:
            QMessageBox.warning(self, APP_NAME, "단축키 등록 확인:\n" + "\n".join(errors))
        self.configure_refresh_timer()

    def configure_refresh_timer(self) -> None:
        self.refresh_timer.stop()
        if not self.config.get("refresh_enabled", True):
            return
        if not (self.config.get("workspace_url") or "").strip():
            return
        minutes = max(15, int(self.config.get("refresh_minutes", 210) or 210))
        self.refresh_timer.start(minutes * 60 * 1000)

    def refresh_workspace(self, show_status: bool = True) -> None:
        try:
            if open_workspace(self.config, minimized=True):
                if show_status:
                    self.statusBar().showMessage("Workspace 갱신 요청을 보냈습니다.", 4000)
            elif show_status:
                self.statusBar().showMessage("Workspace 주소가 비어 있습니다.", 4000)
        except Exception as exc:
            if self.isVisible():
                QMessageBox.warning(self, APP_NAME, f"Workspace 갱신 실패:\n{exc}")

    def refresh_workspace_from_ui(self) -> None:
        self.config = self.read_from_ui()
        self.refresh_workspace(show_status=True)

    def open_workspace_visible(self) -> None:
        self.config = self.read_from_ui()
        try:
            if open_workspace(self.config, minimized=False):
                self.statusBar().showMessage("Workspace를 열었습니다.", 4000)
            else:
                self.statusBar().showMessage("Workspace 주소가 비어 있습니다.", 4000)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Workspace 열기 실패:\n{exc}")

    def launch_env_from_ui(self, env_key: str) -> None:
        self.config = self.read_from_ui()
        save_config(self.config)
        self.launch_env_async(env_key)

    def launch_env_from_hotkey(self, env_key: str) -> None:
        self.launch_env_async(env_key)

    def launch_env_async(self, env_key: str) -> None:
        try:
            env_config = self.config.get("mdm", {}).get(env_key, {})
            mdm_url = normalize_mdm_url(env_config.get("url", ""))
            if not mdm_url:
                raise ValueError(f"{env_key} MDM 주소가 비어 있습니다.")

            if (self.config.get("workspace_url") or "").strip():
                open_workspace(self.config, minimized=True)
                delay_ms = max(0, int(self.config.get("warmup_seconds", 7) or 0)) * 1000
            else:
                delay_ms = 0

            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda url=mdm_url, t=timer: self.finish_delayed_launch(url, t))
            self.pending_launch_timers.append(timer)
            timer.start(delay_ms)
            label = next(env["label"] for env in ENVIRONMENTS if env["key"] == env_key)
            self.statusBar().showMessage(f"{label} 실행 요청을 보냈습니다.", 4000)
        except Exception as exc:
            if self.isVisible():
                QMessageBox.warning(self, APP_NAME, str(exc))
            else:
                self.tray.showMessage(APP_NAME, str(exc), QSystemTrayIcon.Warning, 4000)

    def finish_delayed_launch(self, url: str, timer: QTimer) -> None:
        try:
            launch_mdm_url(url)
        except Exception as exc:
            if self.isVisible():
                QMessageBox.warning(self, APP_NAME, f"GPM 실행 실패:\n{exc}")
            else:
                self.tray.showMessage(APP_NAME, f"GPM 실행 실패: {exc}", QSystemTrayIcon.Warning, 4000)
        finally:
            if timer in self.pending_launch_timers:
                self.pending_launch_timers.remove(timer)
            timer.deleteLater()

    def create_icons(self) -> None:
        self.config = self.read_from_ui()
        save_config(self.config)
        try:
            created = create_desktop_shortcuts()
            names = "\n".join(path.name for path in created)
            QMessageBox.information(self, APP_NAME, f"바탕화면 아이콘을 만들었습니다.\n\n{names}")
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"아이콘 생성 실패:\n{exc}")

    def hide_to_tray(self) -> None:
        self.hide()
        self.tray.showMessage(APP_NAME, "백그라운드에서 실행 중입니다.", QSystemTrayIcon.Information, 2500)

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.show_window()

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide_to_tray()

    def quit_app(self) -> None:
        self.hotkey_manager.unregister_all()
        self.tray.hide()
        QApplication.quit()


def run_cli(args: argparse.Namespace) -> int:
    config = load_config()
    try:
        if args.refresh_only:
            open_workspace(config, minimized=True)
            return 0
        if args.launch:
            env_key = args.launch.upper()
            if env_key == "MEM":
                env_key = "MEMORY"
            allowed = {env["key"] for env in ENVIRONMENTS}
            if env_key not in allowed:
                raise ValueError(f"Unknown environment: {args.launch}")
            launch_environment(config, env_key, include_workspace=True, wait=True)
            return 0
    except Exception as exc:
        show_windows_error(str(exc))
        return 1
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--launch", choices=["NRD", "MEM", "MEMORY", "NRDK", "nrd", "mem", "memory", "nrdk"], help="Launch a configured GPM environment.")
    parser.add_argument("--refresh-only", action="store_true", help="Refresh workspace session and exit.")
    parser.add_argument("--background", action="store_true", help="Start minimized to tray.")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.launch or args.refresh_only:
        return run_cli(args)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(make_app_icon())
    window = MainWindow(start_minimized=args.background)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
