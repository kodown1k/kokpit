"""Hero ring-gauge: animowany counter + sweep łuku, neon glow, ikona, sub-odczyt.
Animacja (counter + sweep) tylko tutaj — to widgety-bohaterowie (hero-only motion)."""
from PySide6 import QtCore, QtGui, QtWidgets

from kokpit.ui.theme.icons import neon_pixmap
from kokpit.ui.theme.palette import DIM_FG, round_pen, value_color

SWEEP_DEG = 270.0      # łuk 270° z przerwą u dołu
START_DEG = 225.0      # start lewy-dół, sweep zgodnie z ruchem wskazówek (ujemny span)


def ring_fraction(value: float | None, vmax: float = 100.0) -> float:
    """value → 0..1 (clamp). None → 0 (pusty łuk)."""
    if value is None:
        return 0.0
    f = value / vmax
    return 0.0 if f < 0 else 1.0 if f > 1 else f


def arc_span(frac: float, sweep_deg: float = SWEEP_DEG) -> float:
    """frac 0..1 → span łuku w stopniach (ujemny = clockwise)."""
    f = 0.0 if frac < 0 else 1.0 if frac > 1 else frac
    return -sweep_deg * f


class RingGauge(QtWidgets.QWidget):
    def __init__(self, title: str, accent: str, icon: str | None = None,
                 high: float | None = None, crit: float | None = None,
                 unit: str = "%", vmax: float = 100.0) -> None:
        super().__init__()
        self._title = title
        self._accent = accent
        self._high = high
        self._crit = crit
        self._unit = unit
        self._vmax = vmax
        self._value: float | None = None   # ostatnia realna wartość (None = brak danych → „--")
        self._shown = 0.0                   # animowana wartość wyświetlana (start od 0)
        self._target = 0.0
        self._sub = ""
        self._pix = neon_pixmap(icon, accent, 18) if icon else None
        self.setMinimumSize(128, 128)
        self._anim = QtCore.QVariantAnimation(self, duration=450)
        self._anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def _on_anim(self, v) -> None:
        self._shown = float(v)
        self.update()

    def set_value(self, value: float | None) -> None:
        if value is None:
            self._value = None
            self._anim.stop()
            self.update()
            return
        self._value = float(value)
        self._target = float(value)
        self._anim.stop()
        self._anim.setStartValue(self._shown)
        self._anim.setEndValue(float(value))
        self._anim.start()

    def set_sub(self, text: str | None) -> None:
        self._sub = text or ""
        self.update()

    def _color(self) -> str:
        if self._value is None:
            return DIM_FG
        return value_color(self._accent, self._value, self._high, self._crit)

    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        side = min(self.width(), self.height())
        m = 18
        rect = QtCore.QRectF((self.width() - side) / 2 + m, (self.height() - side) / 2 + m,
                             side - 2 * m, side - 2 * m)
        start16 = int(START_DEG * 16)
        # tor
        p.setPen(round_pen("#16263a", 9))
        p.drawArc(rect, start16, int(arc_span(1.0) * 16))
        qc = QtGui.QColor(self._color())
        span = int(arc_span(ring_fraction(self._shown, self._vmax)) * 16)
        # poświata (underlay)
        glow = QtGui.QColor(qc)
        glow.setAlpha(70)
        p.setPen(round_pen(glow, 16))
        p.drawArc(rect, start16, span)
        # rdzeń łuku
        p.setPen(round_pen(qc, 9))
        p.drawArc(rect, start16, span)
        # ikona (góra środek)
        if self._pix is not None:
            p.drawPixmap(int(rect.center().x() - 9), int(rect.top() + 4), self._pix)
        # counter (środek)
        p.setPen(qc)
        f = p.font()
        f.setBold(True)
        f.setPointSize(max(12, int(side * 0.15)))
        p.setFont(f)
        txt = "--" if self._value is None else f"{self._shown:.0f}{self._unit}"
        p.drawText(rect, QtCore.Qt.AlignCenter, txt)
        # tytuł (pod counterem)
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(QtGui.QColor("#5fb8d6"))
        title_r = QtCore.QRectF(rect.left(), rect.center().y() + side * 0.12, rect.width(), 14)
        p.drawText(title_r, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, self._title)
        # sub-odczyt (temperatura / GB)
        if self._sub:
            p.setPen(qc)
            sub_r = QtCore.QRectF(rect.left(), rect.bottom() - side * 0.12, rect.width(), 14)
            p.drawText(sub_r, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, self._sub)
        p.end()
