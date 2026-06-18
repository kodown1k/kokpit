"""Panel „informacje o systemie" w stylu KDE *About this System* (KInfoCenter):
Operating System / Plasma / Frameworks / Qt / Kernel / Graphics Platform /
Processors / Memory / Graphics Processor — plus żywy Uptime.
Dane best-effort: /etc/os-release, platform/psutil, env, opcjonalnie NVML i narzędzia KDE."""
import os
import platform
import subprocess
import time

import psutil
from PySide6 import QtCore, QtWidgets

from kokpit.ui.theme.palette import NEON_CYAN


def format_uptime(seconds: float) -> str:
    s = int(seconds)
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def uptime_seconds() -> float:
    try:
        return max(0.0, time.time() - psutil.boot_time())
    except Exception:
        return 0.0


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=1.0)
        return out.stdout.strip() or None
    except Exception:
        return None


def _os_release(key: str) -> str | None:
    try:
        with open("/etc/os-release") as fh:
            for line in fh:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"') or None
    except OSError:
        pass
    return None


def operating_system() -> str:
    return _os_release("PRETTY_NAME") or _os_release("NAME") or platform.system()


def cpu_model() -> str:
    try:
        with open("/proc/cpuinfo") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def gpu_name() -> str | None:
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(h)
        return name.decode() if isinstance(name, bytes) else name
    except Exception:
        return None


def qt_version() -> str:
    return QtCore.qVersion()


def graphics_platform() -> str:
    t = os.environ.get("XDG_SESSION_TYPE") or os.environ.get("WAYLAND_DISPLAY") and "wayland"
    if not t:
        return "X11" if os.environ.get("DISPLAY") else "—"
    return {"x11": "X11", "wayland": "Wayland", "tty": "TTY"}.get(t.lower(), t)


def plasma_version() -> str | None:
    out = _run(["plasmashell", "--version"])          # "plasmashell 6.1.4"
    return out.split()[-1] if out else None


def frameworks_version() -> str | None:
    for tool in ("kf6-config", "kf5-config"):
        out = _run([tool, "--version"])               # wiersz "KDE Frameworks: 6.4.0"
        if out:
            for line in out.splitlines():
                if "Frameworks" in line:
                    return line.split(":")[-1].strip()
    return None


def gather_sysinfo() -> list[tuple[str, str]]:
    """Wiersze (etykieta, wartość) w kolejności jak ekran KDE About this System.
    Pomija pozycje niedostępne na danej maszynie (np. Plasma w headless)."""
    cores = psutil.cpu_count(logical=False)
    threads = psutil.cpu_count(logical=True)
    mem_gib = psutil.virtual_memory().total / (1024 ** 3)
    rows: list[tuple[str, str | None]] = [
        ("Operating System", operating_system()),
        ("KDE Plasma Version", plasma_version()),
        ("KDE Frameworks Version", frameworks_version()),
        ("Qt Version", qt_version()),
        ("Kernel Version", f"{platform.release()} ({platform.machine()})"),
        ("Graphics Platform", graphics_platform()),
        ("Processors", f"{cpu_model()} ({cores}C/{threads}T)" if cores else cpu_model()),
        ("Memory", f"{mem_gib:.1f} GiB"),
        ("Graphics Processor", gpu_name()),
        ("Uptime", format_uptime(uptime_seconds())),
    ]
    return [(k, v) for k, v in rows if v]


class SysInfo(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(3)
        title = QtWidgets.QLabel("ABOUT THIS SYSTEM")
        title.setObjectName("tileTitle")
        v.addWidget(title)
        form = QtWidgets.QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(2)
        form.setColumnStretch(1, 1)
        self._rows: list[tuple[str, QtWidgets.QLabel]] = []
        self._uptime: QtWidgets.QLabel | None = None
        for r, (label, value) in enumerate(gather_sysinfo()):
            key = QtWidgets.QLabel(label)
            key.setStyleSheet(f"color:{NEON_CYAN};font-weight:bold;")
            val = QtWidgets.QLabel(value)
            val.setStyleSheet("color:#c7d6e6;")
            val.setWordWrap(True)
            form.addWidget(key, r, 0, QtCore.Qt.AlignTop)
            form.addWidget(val, r, 1)
            self._rows.append((label, val))
            if label == "Uptime":
                self._uptime = val
        v.addLayout(form)
        v.addStretch(1)

    def refresh(self) -> None:
        if self._uptime is not None:
            self._uptime.setText(format_uptime(uptime_seconds()))
