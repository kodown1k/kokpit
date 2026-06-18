"""Panel „informacje o systemie" w stylu KDE *About this System*, rozszerzony:
sekcje SYSTEM / CPU / MOTHERBOARD / GPU / NVIDIA z dużą ilością szczegółów.
Treść w QScrollArea — długie wartości scrollują, nie rozpychają kolumny.
Dane best-effort: /etc/os-release, lscpu, DMI (sysfs), platform/psutil, NVML."""
import os
import platform
import subprocess
import time

import psutil
from PySide6 import QtCore, QtWidgets

from kokpit.ui.theme.icons import neon_pixmap
from kokpit.ui.theme.palette import NEON_CYAN, NEON_MAGENTA

# ikona neonowego SVG per sekcja (generowane skillem svg-icon-designer)
_SECTION_ICON = {
    "SYSTEM": "system",
    "CPU": "cpu",
    "MOTHERBOARD": "motherboard",
    "GPU / NVIDIA": "gpu",
}


# ---- formatery (czyste, testowalne) ---------------------------------------
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


def format_cuda_version(v: int) -> str:
    """NVML zwraca CUDA jako int (12040) → '12.4'."""
    return f"{v // 1000}.{(v % 1000) // 10}"


def uptime_seconds() -> float:
    try:
        return max(0.0, time.time() - psutil.boot_time())
    except Exception:
        return 0.0


# ---- źródła danych ---------------------------------------------------------
def _run(cmd: list[str], c_locale: bool = False) -> str | None:
    try:
        env = {**os.environ, "LC_ALL": "C", "LANG": "C"} if c_locale else None
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=1.5, env=env)
        return out.stdout.strip() or None
    except Exception:
        return None


def _dec(x) -> str:
    return x.decode() if isinstance(x, bytes) else str(x)


def _os_release(key: str) -> str | None:
    try:
        with open("/etc/os-release") as fh:
            for line in fh:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"') or None
    except OSError:
        pass
    return None


def _dmi(field: str) -> str | None:
    try:
        v = open(f"/sys/devices/virtual/dmi/id/{field}").read().strip()
        return v or None
    except OSError:
        return None


def _lscpu() -> dict[str, str]:
    out = _run(["lscpu"], c_locale=True)   # wymuś angielskie etykiety (lokalna lokalizacja psuje klucze)
    d: dict[str, str] = {}
    if out:
        for line in out.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                d[k.strip()] = v.strip()
    return d


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
    return nvidia_info().get("Name")


def qt_version() -> str:
    return QtCore.qVersion()


def graphics_platform() -> str:
    t = os.environ.get("XDG_SESSION_TYPE")
    if not t:
        return "X11" if os.environ.get("DISPLAY") else "—"
    return {"x11": "X11", "wayland": "Wayland", "tty": "TTY"}.get(t.lower(), t)


def plasma_version() -> str | None:
    out = _run(["plasmashell", "--version"])
    return out.split()[-1] if out else None


def frameworks_version() -> str | None:
    for tool in ("kf6-config", "kf5-config"):
        out = _run([tool, "--version"])
        if out:
            for line in out.splitlines():
                if "Frameworks" in line:
                    return line.split(":")[-1].strip()
    return None


def nvidia_info() -> dict[str, str]:
    """Bogaty zestaw z NVML: nazwa, sterownik, CUDA, VRAM, VBIOS, PCI, zegary, moc."""
    info: dict[str, str] = {}
    try:
        import pynvml as nv
        nv.nvmlInit()
    except Exception:
        return info

    def _try(key, fn):
        try:
            info[key] = fn()
        except Exception:
            pass

    _try("Driver", lambda: _dec(nv.nvmlSystemGetDriverVersion()))
    _try("CUDA", lambda: format_cuda_version(nv.nvmlSystemGetCudaDriverVersion()))
    _try("GPUs", lambda: str(nv.nvmlDeviceGetCount()))
    try:
        h = nv.nvmlDeviceGetHandleByIndex(0)
    except Exception:
        return info
    _try("Name", lambda: _dec(nv.nvmlDeviceGetName(h)))
    _try("VRAM", lambda: f"{nv.nvmlDeviceGetMemoryInfo(h).total / 1e9:.0f} GB")
    _try("VBIOS", lambda: _dec(nv.nvmlDeviceGetVbiosVersion(h)))
    _try("PCI Bus", lambda: _dec(nv.nvmlDeviceGetPciInfo(h).busId))
    _try("Compute Cap", lambda: "%d.%d" % nv.nvmlDeviceGetCudaComputeCapability(h))
    _try("Max GPU Clock", lambda: f"{nv.nvmlDeviceGetMaxClockInfo(h, nv.NVML_CLOCK_GRAPHICS)} MHz")
    _try("Max Mem Clock", lambda: f"{nv.nvmlDeviceGetMaxClockInfo(h, nv.NVML_CLOCK_MEM)} MHz")
    _try("Power Limit", lambda: f"{nv.nvmlDeviceGetPowerManagementLimit(h) / 1000:.0f} W")
    return info


# ---- sekcje ----------------------------------------------------------------
def _mhz(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return f"{float(s.replace(',', '.')):.0f} MHz"   # lscpu bywa z przecinkiem (locale)
    except ValueError:
        return None


def _cpu_rows() -> list[tuple[str, str]]:
    lc = _lscpu()
    max_freq = _mhz(lc.get("CPU max MHz"))
    if max_freq is None:
        try:
            f = psutil.cpu_freq()
            max_freq = f"{f.max:.0f} MHz" if f and f.max else None
        except Exception:
            max_freq = None
    rows = [
        ("Model", cpu_model()),
        ("Vendor", lc.get("Vendor ID", "")),
        ("Architecture", lc.get("Architecture", platform.machine())),
        ("Cores / Threads",
         f"{psutil.cpu_count(logical=False)} / {psutil.cpu_count(logical=True)}"),
        ("Sockets", lc.get("Socket(s)", "")),
        ("Max Freq", max_freq or ""),
        ("L1d / L1i", f"{lc.get('L1d cache', '?')} / {lc.get('L1i cache', '?')}"),
        ("L2 / L3", f"{lc.get('L2 cache', '?')} / {lc.get('L3 cache', '?')}"),
        ("Virtualization", lc.get("Virtualization", "")),
    ]
    return [(k, v) for k, v in rows if v and not v.startswith("?")]


def _mobo_rows() -> list[tuple[str, str]]:
    rows = [
        ("Vendor", _dmi("board_vendor")),
        ("Model", _dmi("board_name")),
        ("Version", _dmi("board_version")),
        ("BIOS", " ".join(x for x in (_dmi("bios_vendor"), _dmi("bios_version")) if x) or None),
        ("BIOS Date", _dmi("bios_date")),
        ("Product", _dmi("product_name")),
        ("Chassis", _dmi("sys_vendor")),
    ]
    return [(k, v) for k, v in rows if v]


def _gpu_rows() -> list[tuple[str, str]]:
    nv = nvidia_info()
    order = ["Name", "Driver", "CUDA", "VRAM", "Compute Cap", "VBIOS",
             "PCI Bus", "Max GPU Clock", "Max Mem Clock", "Power Limit", "GPUs"]
    return [(k, nv[k]) for k in order if k in nv]


def sysinfo_sections() -> list[tuple[str, list[tuple[str, str]]]]:
    cores = psutil.cpu_count(logical=False)
    threads = psutil.cpu_count(logical=True)
    mem_gib = psutil.virtual_memory().total / (1024 ** 3)
    system = [
        ("Operating System", operating_system()),
        ("KDE Plasma Version", plasma_version()),
        ("KDE Frameworks Version", frameworks_version()),
        ("Qt Version", qt_version()),
        ("Kernel Version", f"{platform.release()} ({platform.machine()})"),
        ("Graphics Platform", graphics_platform()),
        ("Memory", f"{mem_gib:.1f} GiB"),
        ("Uptime", format_uptime(uptime_seconds())),
    ]
    sections = [
        ("SYSTEM", [(k, v) for k, v in system if v]),
        ("CPU", _cpu_rows()),
        ("MOTHERBOARD", _mobo_rows()),
        ("GPU / NVIDIA", _gpu_rows()),
    ]
    return [(name, rows) for name, rows in sections if rows]


def gather_sysinfo() -> list[tuple[str, str]]:
    """Spłaszczona lista (kompat.) — wszystkie wiersze ze wszystkich sekcji."""
    return [(k, v) for _name, rows in sysinfo_sections() for k, v in rows]


# ---- widget ----------------------------------------------------------------
class SysInfo(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)
        title = QtWidgets.QLabel("ABOUT THIS SYSTEM")
        title.setObjectName("tileTitle")
        outer.addWidget(title)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        outer.addWidget(scroll, 1)

        content = QtWidgets.QWidget()
        cv = QtWidgets.QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 6, 0)
        cv.setSpacing(2)
        self._rows: list[tuple[str, QtWidgets.QLabel]] = []
        self._uptime: QtWidgets.QLabel | None = None
        for sec, rows in sysinfo_sections():
            head = QtWidgets.QWidget()
            hl = QtWidgets.QHBoxLayout(head)
            hl.setContentsMargins(0, 4, 0, 0)
            hl.setSpacing(5)
            ic = QtWidgets.QLabel()
            ic.setPixmap(neon_pixmap(_SECTION_ICON.get(sec, "system"), NEON_MAGENTA, 14))
            hl.addWidget(ic)
            hdr = QtWidgets.QLabel(sec)
            hdr.setStyleSheet(f"color:{NEON_MAGENTA};font-weight:bold;letter-spacing:1px;")
            hl.addWidget(hdr)
            hl.addStretch(1)
            cv.addWidget(head)
            grid = QtWidgets.QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(1)
            grid.setColumnStretch(1, 1)
            for r, (label, value) in enumerate(rows):
                key = QtWidgets.QLabel(label)
                key.setStyleSheet(f"color:{NEON_CYAN};font-weight:bold;")
                val = QtWidgets.QLabel(value)
                val.setStyleSheet("color:#c7d6e6;")
                val.setWordWrap(True)
                grid.addWidget(key, r, 0, QtCore.Qt.AlignTop)
                grid.addWidget(val, r, 1)
                self._rows.append((label, val))
                if label == "Uptime":
                    self._uptime = val
            cv.addLayout(grid)
        cv.addStretch(1)
        scroll.setWidget(content)

    def refresh(self) -> None:
        if self._uptime is not None:
            self._uptime.setText(format_uptime(uptime_seconds()))
