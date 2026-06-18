import time
from collections import deque

from PySide6 import QtWidgets

from kokpit.ui.plot import make_live_plot, glow_curve
from kokpit.ui.theme.icons import neon_pixmap


def _hex(color) -> str:
    return color if isinstance(color, str) else "#{:02x}{:02x}{:02x}".format(*color[:3])


class Sparkline(QtWidgets.QWidget):
    def __init__(self, title: str, window_s: int = 300, y_range: tuple | None = None,
                 color=(61, 240, 255), icon: str | None = None, scale: float = 1.0) -> None:
        super().__init__()
        self._window_s = window_s
        self._scale = scale
        self._xs: deque[float] = deque()
        self._ys: deque[float] = deque()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(5)
        if icon:
            ic = QtWidgets.QLabel()
            ic.setPixmap(neon_pixmap(icon, _hex(color), 14))
            header.addWidget(ic)
        label = QtWidgets.QLabel(title)
        label.setObjectName("tileTitle")
        header.addWidget(label)
        header.addStretch(1)
        lay.addLayout(header)
        self._plot = make_live_plot()
        if y_range:
            self._plot.setYRange(*y_range)
        # pojedyncza linia agregatu → neonowy glow-pen OK (spec §4.6)
        self._curve = glow_curve(self._plot, color=color)
        lay.addWidget(self._plot)

    def push(self, value: float | None) -> None:
        if value is None:
            return
        now = time.monotonic()
        self._xs.append(now)
        self._ys.append(float(value) * self._scale)
        cutoff = now - self._window_s
        while self._xs and self._xs[0] < cutoff:
            self._xs.popleft()
            self._ys.popleft()
        x0 = self._xs[0]
        self._curve.setData([t - x0 for t in self._xs], list(self._ys))
        self._plot.setXRange(0, self._window_s)
