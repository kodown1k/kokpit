import math

from PySide6 import QtCore, QtGui, QtWidgets

from kokpit.ui.glyph_model import SpokeScore, clamp01
from kokpit.ui.theme.palette import DIM_FG, round_pen

GLOW_THRESHOLD = 0.5

# Każdy parametr ma własny neonowy odcień (radar wielokolorowy zamiast 1 koloru peak).
AXIS_RGB: dict[str, tuple[int, int, int]] = {
    "CPU":      (61, 240, 255),    # cyan
    "RAM":      (57, 255, 20),     # lime
    "Swap":     (0, 210, 160),     # teal
    "GPU":      (255, 60, 200),    # magenta
    "VRAM":     (170, 90, 255),    # violet
    "CPU temp": (255, 150, 0),     # orange
    "GPU temp": (255, 60, 60),     # red
    "Disk IO":  (255, 220, 40),    # yellow
    "Net IO":   (70, 130, 255),    # blue
}
_DEFAULT_RGB = (150, 160, 180)


def axis_rgb(name: str) -> tuple[int, int, int]:
    return AXIS_RGB.get(name, _DEFAULT_RGB)


def axis_qcolor(name: str, score: float) -> QtGui.QColor:
    """Kolor osi z jaskrawością wg wartości: score 0 → przygaszony (blado),
    score 1 → pełny neon. Skaluje zarówno RGB (brightness) jak i alpha."""
    r, g, b = axis_rgb(name)
    s = clamp01(score)
    t = 0.18 + 0.82 * s                 # brightness 0.18..1.0
    a = int(55 + 200 * s)               # alpha 55..255
    return QtGui.QColor(int(r * t), int(g * t), int(b * t), a)

EASE = 0.25
TRAIL_ALPHA0 = 90
TRAIL_TICKS = 14        # ~350 ms persystencji przy 40 fps (krótsza, snappy smuga)
TRAIL_INTERVAL_MS = 25
SETTLE_EPS = 0.002


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
        self._target: list[float] = []
        self._current: list[float] = []
        self._trail: list[tuple[tuple[float, ...], float]] = []
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(TRAIL_INTERVAL_MS)
        self._timer.timeout.connect(self._advance)

    def vertex_radius(self, score: float) -> float:
        return self.R_BASE + self.R_SPAN * max(0.0, min(1.0, score))

    def current_spokes(self) -> list:
        return self._spokes

    def set_spokes(self, spokes, calibrating: bool) -> None:
        self._spokes = list(spokes)
        self._calibrating = calibrating
        self._target = [s.score for s in self._spokes]
        # Snap current on first frame or if spoke count changed
        if not self._current or len(self._current) != len(self._target):
            self._current = list(self._target)
            self._trail = []   # stare wpisy mają radii innej długości → usuń (uniknij IndexError)
        # Start timer to animate toward target
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def _advance(self) -> None:
        if not self._current:
            return
        n = len(self._current)

        # Ease current toward target
        moving = False
        for i in range(n):
            delta = (self._target[i] - self._current[i]) * EASE
            self._current[i] += delta
            if abs(self._target[i] - self._current[i]) >= SETTLE_EPS:
                moving = True

        # Decay existing entries first, THEN append the fresh full-alpha snapshot,
        # so a new ghost starts at TRAIL_ALPHA0 (nie ~86) — i tylko gdy faktycznie się rusza.
        decay = TRAIL_ALPHA0 / TRAIL_TICKS
        self._trail = [(r, a - decay) for r, a in self._trail if a - decay > 6]
        if moving:
            radii = tuple(self.vertex_radius(self._current[i]) for i in range(n))
            self._trail.append((radii, TRAIL_ALPHA0))

        # Cap buffer length
        if len(self._trail) > TRAIL_TICKS:
            self._trail = self._trail[-TRAIL_TICKS:]

        # Check settled
        settled = (
            all(abs(self._target[i] - self._current[i]) < SETTLE_EPS for i in range(n))
            and len(self._trail) == 0
        )
        if settled:
            self._current = list(self._target)
            self._timer.stop()
            self.update()
        else:
            self.update()

    def _vertex(self, cx: float, cy: float, i: int, n: int, r: float) -> QtCore.QPointF:
        ang = -math.pi / 2 + 2 * math.pi * i / n     # start u góry, zgodnie z zegarem
        return QtCore.QPointF(cx + r * math.cos(ang), cy + r * math.sin(ang))

    def _label_radius(self, half: float) -> float:
        """Promień etykiet ramion: stały offset tuż za najdłuższym możliwym
        ramieniem (R_BASE/R_SPAN są w pikselach, więc wielokąt nie skaluje się
        z widgetem), zaciśnięty do `half - 6`, by przy małym widgecie etykiety
        mieściły się w granicach zamiast być obcinane."""
        return min(self.R_BASE + self.R_SPAN + 14.0, half - 6.0)

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

        # trail ghosts: neutralny, przygaszony ślad ruchu (kolory niesie teraz każda oś osobno)
        trail_n = len(self._current) if self._current else 0
        if trail_n == n and self._trail:
            for radii, alpha in self._trail:
                ghost_poly = QtGui.QPolygonF(
                    [self._vertex(cx, cy, i, n, radii[i]) for i in range(n)]
                )
                ghost_pen = round_pen(QtGui.QColor(120, 140, 160, int(alpha)), 1.0)
                p.setPen(ghost_pen)
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawPolygon(ghost_poly)

        # geometria z _current (wygładzona), kolor/score z self._spokes
        cur = self._current if (self._current and len(self._current) == n) else [s.score for s in self._spokes]
        peak = max((s.score for s in self._spokes), default=0.0)
        peak_name = max(self._spokes, key=lambda s: s.score).name if self._spokes else ""
        vtxs = [self._vertex(cx, cy, i, n, self.vertex_radius(cur[i])) for i in range(n)]

        # struktura gwiazdy: cienki, przygaszony wielokąt łączący wierzchołki
        p.setPen(round_pen(QtGui.QColor(90, 110, 130, 130), 1.0))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPolygon(QtGui.QPolygonF(vtxs))

        # promień per-oś: linia środek→wierzchołek + kropka, każda we własnym kolorze,
        # jaskrawość wg score (0 blado → 100 pełny neon + bloom)
        center = QtCore.QPointF(cx, cy)
        for i, s in enumerate(self._spokes):
            col = axis_qcolor(s.name, s.score)
            if s.score >= GLOW_THRESHOLD:          # bloom tylko dla rozjarzonych ramion
                bloom = QtGui.QColor(col)
                bloom.setAlpha(80)
                p.setPen(round_pen(bloom, 9.0))
                p.drawLine(center, vtxs[i])
            p.setPen(round_pen(col, 2.5))
            p.drawLine(center, vtxs[i])
            dot = max(3.0, 3.0 + 3.0 * clamp01(s.score))
            p.setBrush(QtGui.QBrush(col))
            p.setPen(QtCore.Qt.NoPen)
            p.drawEllipse(vtxs[i], dot, dot)
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
            # etykieta w kolorze swojej osi; przy idle przygaszona do czytelnego minimum
            lc = axis_qcolor(s.name, max(s.score, 0.45))
            p.setPen(QtGui.QPen(lc))
            p.drawText(QtCore.QPointF(rx, ry), s.display)
        # centrum: skalar zdrowia (kolor najgorętszej osi) + stan kalibracji
        p.setPen(QtGui.QPen(axis_qcolor(peak_name, max(peak, 0.6))))
        f = p.font()
        f.setPointSize(20)
        f.setBold(True)
        p.setFont(f)
        label = "··" if self._calibrating else f"{int(round(peak * 100))}"
        p.drawText(self.rect(), QtCore.Qt.AlignCenter, label)
        p.end()
