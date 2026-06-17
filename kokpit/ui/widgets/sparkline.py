import time
from collections import deque

from PySide6 import QtWidgets

from kokpit.ui.plot import make_live_plot, configured_curve


class Sparkline(QtWidgets.QWidget):
    def __init__(self, title: str, window_s: int = 300, y_range: tuple | None = None) -> None:
        super().__init__()
        self._window_s = window_s
        self._xs: deque[float] = deque()
        self._ys: deque[float] = deque()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        label = QtWidgets.QLabel(title)
        label.setObjectName("tileTitle")
        lay.addWidget(label)
        self._plot = make_live_plot()
        if y_range:
            self._plot.setYRange(*y_range)
        self._curve = configured_curve(self._plot, color=(57, 208, 255))
        lay.addWidget(self._plot)

    def push(self, value: float | None) -> None:
        if value is None:
            return
        now = time.monotonic()
        self._xs.append(now)
        self._ys.append(float(value))
        cutoff = now - self._window_s
        while self._xs and self._xs[0] < cutoff:
            self._xs.popleft()
            self._ys.popleft()
        x0 = self._xs[0]
        self._curve.setData([t - x0 for t in self._xs], list(self._ys))
        self._plot.setXRange(0, self._window_s)
