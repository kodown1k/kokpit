from collections import deque

from PySide6 import QtWidgets

from kokpit.ui.history_model import HistoryModel, RAW_WINDOW_MAX_S
from kokpit.ui.plot import make_history_plot, configured_curve

TAIL_CAP_S = 3600  # twardy limit ogona live (sekundy) — chroni pamięć/fps


def follow_active(view_x_max: float, last_ts_s: float, tol_s: float = 2.0) -> bool:
    return view_x_max >= last_ts_s - tol_s


def window_mode(window_s: int) -> str:
    return "raw" if window_s <= RAW_WINDOW_MAX_S else "poll"


class HistoryStrip(QtWidgets.QWidget):
    def __init__(self, model: HistoryModel, series: list[str]) -> None:
        super().__init__()
        self._model = model
        self._series = series
        self._follow = True
        self._window_s = 3600
        self._mode = "raw"
        self._last_ts_s: float = 0.0
        self._tail: dict[str, deque] = {s: deque() for s in series}
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        self._plots = {}
        self._curves = {}
        first_plot = None
        for s in series:
            p = make_history_plot()
            label = QtWidgets.QLabel(s)
            label.setObjectName("tileTitle")
            lay.addWidget(label)
            lay.addWidget(p)
            self._plots[s] = p
            self._curves[s] = configured_curve(p, color=(0, 255, 200))
            if first_plot is None:
                first_plot = p
            else:
                p.setXLink(first_plot)
        self._master_vb = first_plot.getViewBox() if first_plot is not None else None
        if self._master_vb is not None:
            self._master_vb.sigRangeChangedManually.connect(self._on_user_pan)

    def _on_user_pan(self, *args) -> None:
        if self._master_vb is None:
            return
        view_x_max = self._master_vb.viewRange()[0][1]
        self._follow = follow_active(view_x_max, self._last_ts_s)

    def set_follow(self, on: bool) -> None:
        self._follow = on

    def set_window(self, window_s: int, now_ms: int) -> None:
        self._window_s = window_s
        self._mode = window_mode(window_s)
        self._last_ts_s = now_ms / 1000.0
        for s in self._series:
            res = self._model.window(s, window_s, now_ms)
            xs = [t for t, _ in res.line]
            ys = [v for _, v in res.line]
            self._curves[s].setData(xs, ys)
            self._tail[s] = deque(zip(xs, ys))

    def on_snapshot(self, snapshot: dict) -> None:
        if self._mode != "raw" or not self._follow:
            return  # tryb poll odświeża się przez set_window (timer w app.py); brak doklejania 1 Hz
        ts = snapshot.get("ts")
        if ts is None:
            return
        t_s = ts / 1000.0
        self._last_ts_s = t_s
        for s in self._series:
            v = snapshot.get("series", {}).get(s)
            if v is None:
                continue
            tail = self._tail[s]
            tail.append((t_s, v))
            cutoff = t_s - TAIL_CAP_S
            while tail and tail[0][0] < cutoff:
                tail.popleft()
            self._curves[s].setData([t for t, _ in tail], [y for _, y in tail])
