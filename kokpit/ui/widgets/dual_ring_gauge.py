"""Hero gauge z DWOMA koncentrycznymi łukami (zewnętrzny większy + wewnętrzny mniejszy)
do dwóch powiązanych temperatur (np. PCI adapter + płyta główna). Animowane sweep'y."""
from PySide6 import QtCore, QtGui, QtWidgets

from kokpit.ui.theme.icons import neon_pixmap
from kokpit.ui.theme.palette import DIM_FG, round_pen, value_color
from kokpit.ui.widgets.ring_gauge import START_DEG, arc_span, ring_fraction


class DualRingGauge(QtWidgets.QWidget):
    def __init__(self, title: str, outer_label: str, inner_label: str,
                 accent_outer: str, accent_inner: str,
                 high: float | None = None, crit: float | None = None,
                 unit: str = "°", vmax: float = 100.0, icon: str | None = "thermal") -> None:
        super().__init__()
        self._title = title
        self._ol, self._il = outer_label, inner_label
        self._ao, self._ai = accent_outer, accent_inner
        self._high, self._crit = high, crit
        self._unit, self._vmax = unit, vmax
        self._outer_val: float | None = None
        self._inner_val: float | None = None
        self._outer_shown = 0.0
        self._inner_shown = 0.0
        self._pix = neon_pixmap(icon, accent_outer, 18) if icon else None
        self.setMinimumSize(128, 128)
        self._anim_o = self._mk_anim(True)
        self._anim_i = self._mk_anim(False)

    def _mk_anim(self, outer: bool) -> QtCore.QVariantAnimation:
        a = QtCore.QVariantAnimation(self, duration=450)
        a.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        a.valueChanged.connect(lambda v, o=outer: self._on_anim(o, v))
        return a

    def _on_anim(self, outer: bool, v) -> None:
        if outer:
            self._outer_shown = float(v)
        else:
            self._inner_shown = float(v)
        self.update()

    def _set(self, outer: bool, value, anim) -> None:
        if value is None:
            if outer:
                self._outer_val = None
            else:
                self._inner_val = None
            anim.stop()
            self.update()
            return
        v = float(value)
        if outer:
            self._outer_val = v
            start = self._outer_shown
        else:
            self._inner_val = v
            start = self._inner_shown
        anim.stop()
        anim.setStartValue(start)
        anim.setEndValue(v)
        anim.start()

    def set_outer(self, value: float | None) -> None:
        self._set(True, value, self._anim_o)

    def set_inner(self, value: float | None) -> None:
        self._set(False, value, self._anim_i)

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
        m = 16
        x0 = (self.width() - side) / 2
        y0 = (self.height() - side) / 2
        outer = QtCore.QRectF(x0 + m, y0 + m, side - 2 * m, side - 2 * m)
        gap = max(14.0, side * 0.16)
        inner = QtCore.QRectF(outer.left() + gap, outer.top() + gap,
                              outer.width() - 2 * gap, outer.height() - 2 * gap)
        self._draw_ring(p, outer, self._outer_val, self._outer_shown, self._ao, 8)
        self._draw_ring(p, inner, self._inner_val, self._inner_shown, self._ai, 7)
        if self._pix is not None:
            p.drawPixmap(int(outer.center().x() - 9), int(outer.top() + 5), self._pix)
        cx = outer.center().x()
        cy = outer.center().y()
        f = p.font()
        f.setBold(True)
        f.setPointSize(max(10, int(side * 0.11)))
        p.setFont(f)
        # dwie wartości w centrum, każda w kolorze swojego ringu
        ot = "--" if self._outer_val is None else f"{self._outer_shown:.0f}{self._unit}"
        it = "--" if self._inner_val is None else f"{self._inner_shown:.0f}{self._unit}"
        p.setPen(self._color(self._outer_val, self._ao))
        p.drawText(QtCore.QRectF(outer.left(), cy - side * 0.18, outer.width(), side * 0.16),
                   QtCore.Qt.AlignCenter, f"{self._ol} {ot}")
        p.setPen(self._color(self._inner_val, self._ai))
        p.drawText(QtCore.QRectF(outer.left(), cy + side * 0.02, outer.width(), side * 0.16),
                   QtCore.Qt.AlignCenter, f"{self._il} {it}")
        f.setBold(True)
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(QtGui.QColor("#5fb8d6"))
        p.drawText(QtCore.QRectF(outer.left(), outer.bottom() - side * 0.14, outer.width(), 14),
                   QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, self._title)
        p.end()
