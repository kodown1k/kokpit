import math

from PySide6 import QtCore, QtGui, QtWidgets

from kokpit.ui.glyph_model import SpokeScore
from kokpit.ui.theme.palette import DIM_FG, round_pen, util_rgb

GLOW_THRESHOLD = 0.5


class VitalGlyph(QtWidgets.QWidget):
    """Wielokąt anomalii: promień wierzchołka = R_BASE + score*R_SPAN.
    Spokojny = regularny wielokąt; kolec = wydłużone ramię (spec §4.3)."""

    R_BASE = 40.0
    R_SPAN = 90.0

    def __init__(self) -> None:
        super().__init__()
        self._spokes: list = []
        self._calibrating = True
        self.setMinimumSize(280, 280)

    def vertex_radius(self, score: float) -> float:
        return self.R_BASE + self.R_SPAN * max(0.0, min(1.0, score))

    def current_spokes(self) -> list:
        return self._spokes

    def set_spokes(self, spokes, calibrating: bool) -> None:
        self._spokes = list(spokes)
        self._calibrating = calibrating
        self.update()   # zażądaj repaint

    def _vertex(self, cx: float, cy: float, i: int, n: int, r: float) -> QtCore.QPointF:
        ang = -math.pi / 2 + 2 * math.pi * i / n     # start u góry, zgodnie z zegarem
        return QtCore.QPointF(cx + r * math.cos(ang), cy + r * math.sin(ang))

    def _label_radius(self, half: float) -> float:
        """Promień do wyświetlania etykiet ramion — zaciskany, by mieścić się w widgecie."""
        return min((self.R_BASE + self.R_SPAN) * (half / 130.0) + 14.0, half - 6.0)

    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        n = len(self._spokes)
        if n == 0:
            p.end()
            return
        # baseline ring (spokojny wielokąt referencyjny)
        ref = QtGui.QPolygonF([self._vertex(cx, cy, i, n, self.R_BASE) for i in range(n)])
        pen = QtGui.QPen(QtGui.QColor(DIM_FG))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPolygon(ref)
        # glif: wypełniony wielokąt z wierzchołkami wg score
        poly = QtGui.QPolygonF(
            [self._vertex(cx, cy, i, n, self.vertex_radius(s.score)) for i, s in enumerate(self._spokes)]
        )
        peak = max((s.score for s in self._spokes), default=0.0)
        r, g, b = util_rgb(peak)
        fill = QtGui.QColor(r, g, b, 70 if not self._calibrating else 35)
        edge = QtGui.QColor(r, g, b)
        # fill pass (translucent)
        p.setBrush(QtGui.QBrush(fill))
        p.setPen(QtCore.Qt.NoPen)
        p.drawPolygon(poly)
        # bloom pass (szeroki, półprzezroczysty) → miękka poświata krawędzi
        glow = QtGui.QColor(edge)
        glow.setAlpha(70)
        bloom_pen = round_pen(glow, 12.0)
        bloom_pen.setJoinStyle(QtCore.Qt.RoundJoin)
        p.setPen(bloom_pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPolygon(poly)
        # crisp pass (wąski, pełny alpha) → jasny rdzeń krawędzi
        crisp_pen = round_pen(edge, 2.5)
        crisp_pen.setJoinStyle(QtCore.Qt.RoundJoin)
        p.setPen(crisp_pen)
        p.drawPolygon(poly)
        # glow per-ramię: drugi, grubszy/półprzezroczysty obrys wierzchołków > próg
        for i, s in enumerate(self._spokes):
            if s.score >= GLOW_THRESHOLD:
                gr, gg, gb = util_rgb(s.score)
                vtx_glow = QtGui.QColor(gr, gg, gb, 90)
                vtx_pen = round_pen(vtx_glow, 10.0)
                p.setPen(vtx_pen)
                v = self._vertex(cx, cy, i, n, self.vertex_radius(s.score))
                p.drawEllipse(v, 5.0, 5.0)
        # podpisy ramion: kod osi + wartość na stałym promieniu poza max ramieniem
        half = min(cx, cy)
        label_r = self._label_radius(half)
        lf = p.font()
        lf.setPointSize(8)
        lf.setBold(False)
        p.setFont(lf)
        fm = QtGui.QFontMetrics(lf)
        for i, s in enumerate(self._spokes):
            if not s.display:
                continue
            ang = -math.pi / 2 + 2 * math.pi * i / n
            lx = cx + label_r * math.cos(ang)
            ly = cy + label_r * math.sin(ang)
            tw = fm.horizontalAdvance(s.display)
            th = fm.height()
            # quadrant-anchor: splay text outward
            cos_a = math.cos(ang)
            sin_a = math.sin(ang)
            if cos_a > 0.25:
                rx = lx
            elif cos_a < -0.25:
                rx = lx - tw
            else:
                rx = lx - tw / 2
            if sin_a > 0.25:
                ry = ly + th * 0.8
            elif sin_a < -0.25:
                ry = ly
            else:
                ry = ly + th * 0.4
            if s.score >= GLOW_THRESHOLD:
                lr, lg, lb = util_rgb(s.score)
                p.setPen(QtGui.QPen(QtGui.QColor(lr, lg, lb)))
            else:
                p.setPen(QtGui.QPen(QtGui.QColor(DIM_FG)))
            p.drawText(QtCore.QPointF(rx, ry), s.display)
        # centrum: skalar zdrowia + stan kalibracji
        p.setPen(QtGui.QPen(edge))
        f = p.font()
        f.setPointSize(20)
        f.setBold(True)
        p.setFont(f)
        label = "··" if self._calibrating else f"{int(round(peak * 100))}"
        p.drawText(self.rect(), QtCore.Qt.AlignCenter, label)
        p.end()
