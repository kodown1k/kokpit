import sys
import time

from PySide6 import QtCore, QtGui, QtWidgets

from kokpit import config
from kokpit.ui.history_model import HistoryModel
from kokpit.ui.live_client import LiveClient
from kokpit.ui.theme.icons import neon_pixmap
from kokpit.ui.theme.palette import NEON_CYAN, NEON_LIME, apply_glow, qss_path
from kokpit.ui.widgets.core_ring_grid import CoreRingGrid
from kokpit.ui.widgets.gauge import Gauge
from kokpit.ui.widgets.gpu_panel import GpuPanel, expected_gpu_indices
from kokpit.ui.widgets.hero_column import HeroColumn
from kokpit.ui.widgets.history_strip import HistoryStrip, window_mode
from kokpit.ui.glyph_model import BaselineCache, GlyphModel
from kokpit.ui.widgets.proc_table import ProcTable
from kokpit.ui.widgets.sparkline import Sparkline
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
        self._live = live
        self._cur_window_s = 3600
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        grid = QtWidgets.QGridLayout(central)

        # resolve machine-specific series names up front (interface/disk names vary per host)
        self._net_key = primary_net_key(model.available_series("net."))
        self._disk_key = first_metric_key(model.available_series("disk."), ".read_bps")
        gpu0 = gpu_indices[0] if gpu_indices else 0

        self._hero = HeroColumn(gpu0)
        self._core = CoreRingGrid()
        self._swap = Gauge("SWAP", " MB", high=4096, crit=8192, accent=NEON_CYAN)
        self._net = Sparkline("NET rx", window_s=120, color=(61, 240, 255), icon="net-rx")
        self._disk = Sparkline("DISK r", window_s=120, color=(57, 255, 20), icon="disk-read")
        self._procs = ProcTable()
        self._gpu_extra = GpuPanel(gpu_indices[1:]) if len(gpu_indices) > 1 else None
        self._glyph = VitalGlyph()
        self._glyph_model = GlyphModel()
        self._baseline = BaselineCache(model.store, now_fn=_now_ms)

        hist_series = ["cpu.loadavg.1", f"gpu.{gpu0}.util", "mem.used"]
        if self._net_key:
            hist_series.append(self._net_key)
        self._hist = HistoryStrip(model, hist_series)

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

        # kolumna I/O (NET / DISK / SWAP [+ dodatkowe GPU jeśli >1])
        io = QtWidgets.QWidget()
        io_lay = QtWidgets.QVBoxLayout(io)
        io_lay.setContentsMargins(0, 0, 0, 0)
        io_lay.setSpacing(4)
        io_lay.addWidget(self._net)
        io_lay.addWidget(self._disk)
        io_lay.addWidget(self._swap)
        if self._gpu_extra is not None:
            io_lay.addWidget(self._gpu_extra)

        # layout B: hero-kolumna z lewej (span), reszta po prawej, glyph hero z prawej
        grid.addWidget(self._hero, 0, 0, 6, 1)
        grid.addWidget(self._core, 0, 1, 2, 2)
        grid.addWidget(io, 0, 3, 2, 1)
        grid.addWidget(self._hist, 2, 1, 2, 3)
        grid.addWidget(_titled("processes", NEON_CYAN, "PROCESSES", self._procs), 4, 1, 1, 3)
        grid.addWidget(ctrl_w, 5, 1, 1, 3)
        grid.addWidget(self._glyph, 0, 4, 6, 1)   # Vital-Signs Glyph: right-side hero column
        grid.addWidget(self._status, 6, 0, 1, 5)
        grid.setColumnStretch(0, 0)
        for _c in (1, 2, 3):
            grid.setColumnStretch(_c, 1)
        grid.setColumnStretch(4, 1)

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

    def _on_snapshot(self, snap: dict) -> None:
        s = snap.get("series", {})
        self._hero.update_snapshot(snap)
        self._core.set_util(s)
        self._core.set_temp(s)
        sw = s.get("swap.used")
        self._swap.set_value(None if sw is None else sw / (1024 * 1024))
        self._net.push(s.get(self._net_key) if self._net_key else None)
        self._disk.push(s.get(self._disk_key) if self._disk_key else None)
        if self._gpu_extra is not None:
            self._gpu_extra.update_snapshot(snap)
        self._procs.set_rows(snap.get("procs", []))
        self._hist.on_snapshot(snap)
        spokes = self._glyph_model.update(s, snap.get("ts", _now_ms()), self._baseline.get)
        self._glyph.set_spokes(spokes, self._glyph_model.calibrating)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
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
