import sys
import time

from PySide6 import QtCore, QtGui, QtWidgets

from kokpit import config
from kokpit.ui.ctl_client import ControlClient
from kokpit.ui.history_model import HistoryModel
from kokpit.ui.live_client import LiveClient
from kokpit.ui.theme.icons import neon_pixmap
from kokpit.ui.theme.palette import (
    NEON_CYAN, NEON_LIME, NEON_MAGENTA, app_icon_path, apply_glow, qss_path,
)
from kokpit.ui.widgets.core_ring_grid import CoreRingGrid
from kokpit.ui.widgets.gpu_panel import GpuPanel, expected_gpu_indices
from kokpit.ui.widgets.hero_column import HeroColumn
from kokpit.ui.widgets.history_strip import HistoryStrip, window_mode
from kokpit.ui.glyph_model import BaselineCache, GlyphModel
from kokpit.ui.widgets.gpu_proc_table import GpuProcTable
from kokpit.ui.widgets.proc_table import ProcTable
from kokpit.ui.widgets.disk_usage import DiskUsage
from kokpit.ui.widgets.dual_ring_gauge import DualRingGauge
from kokpit.ui.widgets.proposal_bar import ProposalBar
from kokpit.ui.widgets.sparkline import Sparkline
from kokpit.ui.widgets.sysinfo import SysInfo
from kokpit.ui.widgets.vital_glyph import VitalGlyph


def _titled(icon_name: str, color: str, text: str, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
    """Owija widget nagłówkiem [neon-ikona + tytuł]."""
    box = QtWidgets.QWidget()
    v = QtWidgets.QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    h = QtWidgets.QHBoxLayout()
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(5)
    ic = QtWidgets.QLabel()
    ic.setPixmap(neon_pixmap(icon_name, color, 14))
    h.addWidget(ic)
    lbl = QtWidgets.QLabel(text)
    lbl.setObjectName("tileTitle")
    h.addWidget(lbl)
    h.addStretch(1)
    v.addLayout(h)
    v.addWidget(widget)
    return box

# history-window presets: (label, seconds)
WINDOWS = [("1h", 3600), ("6h", 21600), ("24h", 86400), ("7d", 604800)]
POLL_INTERVAL_MS = 30000  # rollup windows re-poll the DB; the raw (1h) window rides the live tail


def _now_ms() -> int:
    return int(time.time() * 1000)


def first_metric_key(names: list[str], suffix: str) -> str | None:
    """Return first (sorted) name ending with *suffix*, or None."""
    return next((n for n in sorted(names) if n.endswith(suffix)), None)


_WIRED_NET_PREFIXES = ("net.en", "net.eth")  # enp*/eno*/ens*/enx* + legacy eth*


def primary_net_key(names: list[str]) -> str | None:
    """Pick the rx_bps series for the primary interface: prefer a wired one
    (en*/eth*), else fall back to the alphabetically-first. Avoids choosing a
    wifi/secondary iface (e.g. 'ath0' < 'eth0' alphabetically) on multi-iface hosts."""
    rx = sorted(n for n in names if n.endswith(".rx_bps"))
    if not rx:
        return None
    return next((n for n in rx if n.startswith(_WIRED_NET_PREFIXES)), rx[0])


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, live: LiveClient, model: HistoryModel, gpu_indices: list[int]) -> None:
        super().__init__()
        self.setWindowTitle("kokpit")
        self.setWindowIcon(QtGui.QIcon(app_icon_path()))
        self._live = live
        self._cur_window_s = 3600
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        grid = QtWidgets.QGridLayout(central)

        # resolve machine-specific series names up front (interface/disk names vary per host)
        self._net_key = primary_net_key(model.available_series("net."))
        gpu0 = gpu_indices[0] if gpu_indices else 0

        # PCI adapter (wifi) + płyta główna (chipset/ACPI) — wewn. ring spada na najgorętszy
        # dysk NVMe, gdy host nie wystawia sensora płyty (np. brak acpitz/pch).
        thermal_series = set(model.available_series("thermal."))
        self._has_board = "thermal.board" in thermal_series
        self._temps = DualRingGauge(
            "TEMPS", "PCI", "MB" if self._has_board else "SSD",
            NEON_MAGENTA, NEON_LIME, high=75, crit=90)

        self._hero = HeroColumn(gpu0)
        self._core = CoreRingGrid()
        self._sysinfo = SysInfo()
        self._net = Sparkline("NET rx (KB/s)", window_s=120, color=(61, 240, 255),
                              icon="net-rx", scale=1.0 / 1024)
        self._disk_usage = DiskUsage()
        self._procs = ProcTable()
        self._gpu_procs = GpuProcTable()
        self._gpu_extra = GpuPanel(gpu_indices[1:]) if len(gpu_indices) > 1 else None
        self._glyph = VitalGlyph()
        self._glyph_model = GlyphModel()
        self._baseline = BaselineCache(model.store, now_fn=_now_ms)
        self._ctl = ControlClient(str(config.control_socket_path()))
        self._bar = ProposalBar()
        self._glyph.capRequested.connect(self._on_cap_requested)
        self._bar.confirmed.connect(self._on_confirm)
        self._bar.denied.connect(self._on_deny)
        self._bar.commandEntered.connect(self._on_command)
        self._prop_timer = QtCore.QTimer(self)
        self._prop_timer.setInterval(2000)
        self._prop_timer.timeout.connect(self._poll_proposals)
        self._prop_timer.start()

        hist_series = ["cpu.loadavg.1", f"gpu.{gpu0}.util", "mem.used"]
        hist_formats = {
            "cpu.loadavg.1": ("CPU load (1m)", 1.0),
            f"gpu.{gpu0}.util": (f"GPU{gpu0} util (%)", 1.0),
            "mem.used": ("MEM used (GB)", 1e-9),
        }
        if self._net_key:
            hist_series.append(self._net_key)
            hist_formats[self._net_key] = ("NET rx (KB/s)", 1.0 / 1024)
        self._hist = HistoryStrip(model, hist_series, formats=hist_formats)

        self._status = QtWidgets.QLabel("disconnected")
        self._status.setObjectName("statusBar")
        self._status_glow = apply_glow(self._status, NEON_CYAN, radius=10.0)

        # history controls: [1h|6h|24h|7d] window switcher + ● LIVE (jump to now / re-follow)
        ctrl = QtWidgets.QHBoxLayout()
        self._win_buttons: dict[int, QtWidgets.QPushButton] = {}
        for label, ws in WINDOWS:
            b = QtWidgets.QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _checked=False, w=ws: self._set_window(w))
            ctrl.addWidget(b)
            self._win_buttons[ws] = b
        self._live_button = QtWidgets.QPushButton("● LIVE")
        self._live_button.setObjectName("liveButton")
        self._live_glow = apply_glow(self._live_button, NEON_LIME, radius=10.0)
        self._live_button.clicked.connect(self._jump_to_now)
        ctrl.addWidget(self._live_button)
        ctrl.addStretch(1)
        ctrl_w = QtWidgets.QWidget()
        ctrl_w.setLayout(ctrl)
        # ● LIVE pulsuje — jedyna ciągła animacja (1 mały widget, ~1 Hz wizualnie)
        self._pulse = QtCore.QVariantAnimation(self, duration=1100)
        self._pulse.setStartValue(8.0)
        self._pulse.setEndValue(20.0)
        self._pulse.setEasingCurve(QtCore.QEasingCurve.InOutSine)
        self._pulse.setLoopCount(-1)
        self._pulse.valueChanged.connect(lambda v: self._live_glow.setBlurRadius(float(v)))
        self._pulse.start()

        # ZONA 1 — VITALS + SYSTEM (lewa): małe ringi util‖temp, niżej panel sysinfo
        zone_vitals = QtWidgets.QWidget()
        zv = QtWidgets.QVBoxLayout(zone_vitals)
        zv.setContentsMargins(0, 0, 0, 0)
        zv.setSpacing(6)
        zv.addWidget(_titled("cpu", NEON_CYAN, "CORES", self._core))
        if self._gpu_extra is not None:
            zv.addWidget(self._gpu_extra)
        zv.addWidget(self._sysinfo, 1)

        # ZONA 2 — ANOMALY RADAR (środek): glyph wyśrodkowany jako bohater, dostaje sceny
        zone_glyph = QtWidgets.QWidget()
        zg = QtWidgets.QVBoxLayout(zone_glyph)
        zg.setContentsMargins(0, 0, 0, 0)
        zg.addWidget(self._glyph, 1)
        zg.addWidget(self._bar)

        # ZONA 3 — I/O & STORAGE (prawa): sparkline'y NET/DISK jeden pod drugim + zajętość
        zone_io = QtWidgets.QWidget()
        zi = QtWidgets.QVBoxLayout(zone_io)
        zi.setContentsMargins(0, 0, 0, 0)
        zi.setSpacing(6)
        zi.addWidget(self._net, 1)
        zi.addWidget(self._disk_usage, 2)   # ma własny nagłówek „DISK USAGE"

        # PROCESSES (top-CPU) ‖ GPU PROCESSES (NVML, top-VRAM) — resizable splitter
        proc_split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        proc_split.addWidget(_titled("processes", NEON_CYAN, "PROCESSES", self._procs))
        proc_split.addWidget(_titled("gpu", NEON_MAGENTA, "GPU PROCESSES", self._gpu_procs))
        proc_split.setStretchFactor(0, 3)   # PROCESSES (CPU)
        proc_split.setStretchFactor(1, 4)   # GPU-tabela ma więcej kolumn → szersza (proporcja 3:4)

        # bento: pas hero (5 kafli) → pasmo 3 stref → history (pełna szer.) → tabele → kontrolki
        top = QtWidgets.QWidget()
        top_lay = QtWidgets.QHBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(8)
        top_lay.addWidget(self._hero, 4)
        top_lay.addWidget(self._temps, 1)
        grid.addWidget(top, 0, 0, 1, 3)
        grid.addWidget(zone_vitals, 1, 0)
        grid.addWidget(zone_glyph, 1, 1)
        grid.addWidget(zone_io, 1, 2)
        grid.addWidget(self._hist, 2, 0, 1, 3)
        grid.addWidget(proc_split, 3, 0, 1, 3)
        grid.addWidget(ctrl_w, 4, 0, 1, 3)
        grid.addWidget(self._status, 5, 0, 1, 3)
        grid.setColumnStretch(0, 5)    # vitals + system
        grid.setColumnStretch(1, 5)    # glyph — bohater dostaje środek
        grid.setColumnStretch(2, 4)    # I/O stos
        grid.setRowStretch(1, 4)       # pasmo 3 stref (główna scena)
        grid.setRowStretch(2, 2)       # history
        grid.setRowStretch(3, 2)       # tabele

        live.snapshot.connect(self._on_snapshot)   # AutoConnection → wątek GUI
        live.state.connect(self._on_state)

        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.timeout.connect(self._refresh_history)
        self._poll_timer.start(POLL_INTERVAL_MS)

        self._set_window(3600)

    def _set_window(self, window_s: int) -> None:
        # explicit window switch is a "show me this window at now" action → re-engage follow.
        # (NOT done inside set_window itself, so the poll timer's refresh keeps a panned-away view.)
        self._cur_window_s = window_s
        for ws, b in self._win_buttons.items():
            b.setChecked(ws == window_s)
        self._hist.set_window(window_s, _now_ms())
        self._hist.set_follow(True)

    def _jump_to_now(self) -> None:
        self._hist.set_window(self._cur_window_s, _now_ms())
        self._hist.set_follow(True)

    def _refresh_history(self) -> None:
        # rollup windows re-poll the DB to pick up new buckets; the raw window stays
        # current via the live tail, so reseeding it would just discard the smooth tail.
        if window_mode(self._cur_window_s) == "poll":
            self._hist.set_window(self._cur_window_s, _now_ms())

    def _on_state(self, state: str) -> None:
        self._status.setText(state)
        ok = state == "connected"
        color = NEON_LIME if ok else "#ff2a2a"
        self._status.setStyleSheet(f"color:{color};font-weight:bold;letter-spacing:1px;")
        self._status_glow.setColor(QtGui.QColor(color))   # ref do QGraphicsDropShadowEffect (typed)

    def _on_cap_requested(self, axis: str, fraction: float) -> None:
        if axis in ("GPU", "VRAM", "GPU temp"):
            floor = config.GPU_POWER_FLOOR_W
            watts = int(floor + fraction * (config.GPU_POWER_CEILING_W - floor))
            self._ctl.request("apply", {"lever": "gpu_power", "target": {"index": 0},
                                        "params": {"watts": watts},
                                        "ttl_s": config.ENVELOPE_DEFAULT_TTL_S})
        elif axis in ("CPU", "CPU temp"):
            name = "powersave" if fraction < 0.5 else "performance"
            self._ctl.request("apply", {"lever": "governor", "target": {},
                                        "params": {"name": name},
                                        "ttl_s": config.ENVELOPE_DEFAULT_TTL_S})

    def _on_command(self, text: str) -> None:
        self._ctl.request("intent", {"text": text})

    def _poll_proposals(self) -> None:
        props = self._ctl.poll_proposals()
        if props:
            self._bar.show_proposal(props[0]["id"], props[0]["text"])

    def _on_confirm(self, pid: str) -> None:
        self._ctl.request("confirm", {"id": pid})

    def _on_deny(self, pid: str) -> None:
        self._ctl.request("deny", {"id": pid})

    def _on_snapshot(self, snap: dict) -> None:
        s = snap.get("series", {})
        self._hero.update_snapshot(snap)
        # PCI adapter (wifi) na zewn. ringu; płyta (board) lub najgorętszy NVMe na wewn.
        self._temps.set_outer(s.get("thermal.wifi"))
        board = s.get("thermal.board")
        if board is None:
            nvme = [v for k, v in s.items() if k.startswith("thermal.nvme.") and v is not None]
            board = max(nvme) if nvme else None
        self._temps.set_inner(board)
        self._core.set_util(s)
        self._core.set_temp(s)
        self._sysinfo.refresh()
        self._disk_usage.refresh()
        self._net.push(s.get(self._net_key) if self._net_key else None)
        if self._gpu_extra is not None:
            self._gpu_extra.update_snapshot(snap)
        self._procs.set_rows(snap.get("procs", []))
        self._gpu_procs.set_rows(snap.get("gpu_procs", []))
        self._hist.on_snapshot(snap)
        spokes = self._glyph_model.update(s, snap.get("ts", _now_ms()), self._baseline.get)
        self._glyph.set_spokes(spokes, self._glyph_model.calibrating)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon(app_icon_path()))   # ikona aplikacji (okno/pasek/dock)
    try:
        with open(qss_path()) as fh:
            app.setStyleSheet(fh.read())
    except OSError:
        pass
    from kokpit.store import Store
    store = Store(str(config.db_path()))
    model = HistoryModel(store)
    try:
        gpu_indices = expected_gpu_indices(store.list_series("gpu."))
    except Exception:
        gpu_indices = [0]
    live = LiveClient(str(config.socket_path()))
    win = MainWindow(live, model, gpu_indices)
    win.resize(1900, 950)
    win.show()
    live.start()
    try:
        return app.exec()
    finally:
        live.stop()


if __name__ == "__main__":
    raise SystemExit(main())
