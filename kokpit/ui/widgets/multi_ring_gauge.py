"""Hero gauge z N koncentrycznymi łukami (zewn.→wewn.) do powiązanych temperatur
(np. dyski NVMe albo pakiet CPU + płyta): grubość ringów adaptuje się do N,
środek zawsze zostaje na N linii wartości."""
from PySide6 import QtCore, QtGui, QtWidgets

from kokpit.ui.theme.palette import DIM_FG, round_pen, value_color
from kokpit.ui.widgets.ring_gauge import START_DEG, arc_span, ring_fraction

MARGIN = 16        # margines kwadratu gauge'a (jak w dawnym Dual)
MAX_RING_W = 9.0   # grubość ringu przy małym N (dzisiejszy wygląd hero)


def ring_width(side: float, n: int) -> float:
    """N ringów zajmuje maks. 60% promienia — środek zostaje na tekst wartości."""
    r = side / 2.0 - MARGIN
    return min(MAX_RING_W, 0.6 * r / max(1, n))


class MultiRingGauge(QtWidgets.QWidget):
    def __init__(self, title: str, rings: list[tuple[str, str]],
                 high: float | None = None, crit: float | None = None,
                 unit: str = "°", vmax: float = 100.0) -> None:
        super().__init__()
        self._title = title
        self._labels = [lb for lb, _ in rings]
        self._accents = [ac for _, ac in rings]
        self._high, self._crit = high, crit
        self._unit, self._vmax = unit, vmax
        n = len(rings)
        self._vals: list[float | None] = [None] * n
        self._shown: list[float] = [0.0] * n
        self.setMinimumSize(128, 128)
        self._anims = [self._mk_anim(i) for i in range(n)]

    def _mk_anim(self, i: int) -> QtCore.QVariantAnimation:
        a = QtCore.QVariantAnimation(self, duration=450)
        a.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        a.valueChanged.connect(lambda v, i=i: self._on_anim(i, v))
        return a

    def _on_anim(self, i: int, v) -> None:
        self._shown[i] = float(v)
        self.update()

    def set_values(self, values: list[float | None]) -> None:
        """Wartości zewn.→wewn.; brakujące → None, nadmiar ignorowany."""
        n = len(self._vals)
        vals = (list(values) + [None] * n)[:n]
        for i, v in enumerate(vals):
            if v is None:
                self._vals[i] = None
                self._anims[i].stop()
                continue
            self._vals[i] = float(v)
            self._anims[i].stop()
            self._anims[i].setStartValue(self._shown[i])
            self._anims[i].setEndValue(float(v))
            self._anims[i].start()
        self.update()

    def _color(self, value: float | None, accent: str) -> QtGui.QColor:
        if value is None:
            return QtGui.QColor(DIM_FG)
        return QtGui.QColor(value_color(accent, value, self._high, self._crit))

    def _draw_ring(self, p, rect, value, shown, accent, width) -> None:
        start16 = int(START_DEG * 16)
        p.setPen(round_pen("#16263a", width))
        p.drawArc(rect, start16, int(arc_span(1.0) * 16))
        if value is None:
            return
        qc = self._color(value, accent)
        span = int(arc_span(ring_fraction(shown, self._vmax)) * 16)
        glow = QtGui.QColor(qc)
        glow.setAlpha(70)
        p.setPen(round_pen(glow, width + 6))
        p.drawArc(rect, start16, span)
        p.setPen(round_pen(qc, width))
        p.drawArc(rect, start16, span)

    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        side = min(self.width(), self.height())
        x0 = (self.width() - side) / 2
        y0 = (self.height() - side) / 2
        n = len(self._vals)
        w = ring_width(side, n)
        outer = QtCore.QRectF(x0 + MARGIN, y0 + MARGIN, side - 2 * MARGIN, side - 2 * MARGIN)
        rect = outer
        for i in range(n):
            self._draw_ring(p, rect, self._vals[i], self._shown[i], self._accents[i], w)
            rect = rect.adjusted(w, w, -w, -w)   # kolejny ring tuż przy poprzednim
        cy = outer.center().y()
        f = p.font()
        f.setBold(True)
        f.setPointSize(max(7, int(side * 0.07)))
        p.setFont(f)
        lh = side * min(0.11, 0.33 / max(1, n))   # linie ciaśniejsze, gdy ringów więcej
        top = cy - lh * n / 2
        # N linii "LABEL 72°" w centrum, każda w kolorze swojego ringu
        for i in range(n):
            t = "--" if self._vals[i] is None else f"{self._shown[i]:.0f}{self._unit}"
            p.setPen(self._color(self._vals[i], self._accents[i]))
            p.drawText(QtCore.QRectF(outer.left(), top + i * lh, outer.width(), lh),
                       QtCore.Qt.AlignCenter, f"{self._labels[i]} {t}")
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(QtGui.QColor("#5fb8d6"))
        p.drawText(QtCore.QRectF(outer.left(), outer.bottom() - side * 0.14, outer.width(), 14),
                   QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, self._title)
        p.end()
