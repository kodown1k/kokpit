import sys

from PySide6 import QtWidgets

from kokpit import config
from kokpit.ui.history_model import HistoryModel
from kokpit.ui.live_client import LiveClient
from kokpit.ui.theme.palette import qss_path
from kokpit.ui.widgets.gauge import Gauge
from kokpit.ui.widgets.gpu_panel import GpuPanel, expected_gpu_indices
from kokpit.ui.widgets.heatmap import CoreHeatmap, pkg_temp
from kokpit.ui.widgets.history_strip import HistoryStrip
from kokpit.ui.widgets.proc_table import ProcTable
from kokpit.ui.widgets.sparkline import Sparkline

_HIST_SERIES = ["cpu.loadavg.1", "gpu.0.util", "mem.used", "net.eth0.rx_bps"]


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, live: LiveClient, model: HistoryModel, gpu_indices: list[int]) -> None:
        super().__init__()
        self.setWindowTitle("kokpit")
        self._live = live
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        grid = QtWidgets.QGridLayout(central)

        self._heatmap = CoreHeatmap()
        self._gpu = GpuPanel(gpu_indices or [0])
        self._ram = Gauge("RAM", "%", high=85, crit=95)
        self._swap = Gauge("SWAP", " MB", high=4096, crit=8192)
        self._pkg = Gauge("CPU PKG", "°C", high=80, crit=100)
        self._net = Sparkline("NET rx", window_s=120)
        self._disk = Sparkline("DISK r", window_s=120)
        self._procs = ProcTable()
        self._hist = HistoryStrip(model, _HIST_SERIES)
        self._status = QtWidgets.QLabel("disconnected")
        self._status.setObjectName("tileTitle")

        grid.addWidget(self._heatmap, 0, 0, 1, 2)
        grid.addWidget(self._gpu, 0, 2, 1, 2)
        grid.addWidget(self._pkg, 1, 0)
        grid.addWidget(self._ram, 1, 1)
        grid.addWidget(self._swap, 1, 2)
        grid.addWidget(self._net, 1, 3)
        grid.addWidget(self._disk, 2, 0, 1, 2)
        grid.addWidget(self._procs, 2, 2, 1, 2)
        grid.addWidget(self._hist, 3, 0, 1, 4)
        grid.addWidget(self._status, 4, 0, 1, 4)

        live.snapshot.connect(self._on_snapshot)   # AutoConnection → wątek GUI
        live.state.connect(self._on_state)
        self._hist.set_window(3600, now_ms=0)       # placeholder dopóki nie znamy now

    def _on_state(self, state: str) -> None:
        self._status.setText(state)

    def _on_snapshot(self, snap: dict) -> None:
        s = snap.get("series", {})
        self._heatmap.set_util(s)
        self._heatmap.set_temp(s)
        self._gpu.update_snapshot(snap)
        self._pkg.set_value(pkg_temp(s))
        mt = s.get("mem.total")
        self._ram.set_value(None if not mt else s.get("mem.used", 0) / mt * 100)
        sw = s.get("swap.used"); self._swap.set_value(None if sw is None else sw / (1024 * 1024))
        self._net.push(s.get("net.eth0.rx_bps"))
        self._disk.push(s.get("disk.nvme0n1.read_bps"))
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
