import sys
import time

from PySide6 import QtCore, QtGui, QtWidgets

from kokpit import config
from kokpit.ui.history_model import HistoryModel
from kokpit.ui.live_client import LiveClient
from kokpit.ui.theme.palette import NEON_CYAN, NEON_LIME, NEON_MAGENTA, apply_glow, qss_path
from kokpit.ui.widgets.gauge import Gauge
from kokpit.ui.widgets.gpu_panel import GpuPanel, expected_gpu_indices
from kokpit.ui.widgets.heatmap import CoreHeatmap, pkg_temp
from kokpit.ui.widgets.history_strip import HistoryStrip, window_mode
from kokpit.ui.widgets.proc_table import ProcTable
from kokpit.ui.widgets.sparkline import Sparkline

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

        self._heatmap = CoreHeatmap()
        self._gpu = GpuPanel(gpu_indices or [0])
        self._ram = Gauge("RAM", "%", high=85, crit=95, accent=NEON_CYAN)
        self._swap = Gauge("SWAP", " MB", high=4096, crit=8192, accent=NEON_CYAN)
        self._pkg = Gauge("CPU PKG", "°C", high=80, crit=100, accent=NEON_MAGENTA)
        self._net = Sparkline("NET rx", window_s=120, color=(61, 240, 255))   # cyan
        self._disk = Sparkline("DISK r", window_s=120, color=(57, 255, 20))   # lime
        self._procs = ProcTable()

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
        apply_glow(self._live_button, NEON_LIME, radius=14.0)
        self._live_button.clicked.connect(self._jump_to_now)
        ctrl.addWidget(self._live_button)
        ctrl.addStretch(1)
        ctrl_w = QtWidgets.QWidget()
        ctrl_w.setLayout(ctrl)

        grid.addWidget(self._heatmap, 0, 0, 1, 2)
        grid.addWidget(self._gpu, 0, 2, 1, 2)
        grid.addWidget(self._pkg, 1, 0)
        grid.addWidget(self._ram, 1, 1)
        grid.addWidget(self._swap, 1, 2)
        grid.addWidget(self._net, 1, 3)
        grid.addWidget(self._disk, 2, 0, 1, 2)
        grid.addWidget(self._procs, 2, 2, 1, 2)
        grid.addWidget(ctrl_w, 3, 0, 1, 4)
        grid.addWidget(self._hist, 4, 0, 1, 4)
        grid.addWidget(self._status, 5, 0, 1, 4)

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
        self._heatmap.set_util(s)
        self._heatmap.set_temp(s)
        self._gpu.update_snapshot(snap)
        self._pkg.set_value(pkg_temp(s))
        mt = s.get("mem.total")
        self._ram.set_value(None if not mt else s.get("mem.used", 0) / mt * 100)
        sw = s.get("swap.used")
        self._swap.set_value(None if sw is None else sw / (1024 * 1024))
        self._net.push(s.get(self._net_key) if self._net_key else None)
        self._disk.push(s.get(self._disk_key) if self._disk_key else None)
        self._procs.set_rows(snap.get("procs", []))
        self._hist.on_snapshot(snap)


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
    win.resize(1500, 950)
    win.show()
    live.start()
    try:
        return app.exec()
    finally:
        live.stop()


if __name__ == "__main__":
    raise SystemExit(main())
