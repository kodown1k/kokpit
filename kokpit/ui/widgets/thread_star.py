"""ThreadStar — przyjazna animowana rozgwiazda: każde ramię = util jednego wątku CPU.
Czyste funkcje geometrii/animacji (testowalne bez Qt) oddzielone od paintEvent —
wzorzec jak w kokpit/ui/widgets/vital_glyph.py. Spec 2026-06-19."""
import math

from PySide6 import QtCore, QtGui, QtWidgets

from kokpit.ui.glyph_model import clamp01
from kokpit.ui.theme.palette import round_pen, util_rgb
from kokpit.ui.widgets.heatmap import thread_count, thread_util_keys

EASE = 0.22
SETTLE_EPS = 0.002
TICK_MS = 25                # ~40 fps; timer biegnie ciągle (oddech), 1 paint/tick

R_BODY = 26.0               # promień centralnego dysku (przed skalą)
R_ARM_MIN = 16.0            # długość stubu przy 0% utilu (idle = wciąż rozgwiazda)
R_ARM_SPAN = 82.0           # dodatkowa długość przy 100% utilu
R_MAX = R_BODY + R_ARM_MIN + R_ARM_SPAN   # 124 — max zasięg czubka
MARGIN = 18.0              # margines do krawędzi widgetu
GLOW_THRESHOLD = 0.55      # próg bloomu dla zajętych ramion
BREATH_AMP_R = 3.0         # px (przed skalą) — puls promienia (oddech)
BREATH_AMP_A = 0.045       # rad — kołysanie kąta ramienia
BASE_HALF_ANG = 0.30       # rad — połowa kątowej szerokości bazy ramienia na ciele


def arm_angle(i: int, n: int) -> float:
    return -math.pi / 2 + 2 * math.pi * i / n


def arm_reach(body_r: float, arm_min: float, arm_span: float, frac: float) -> float:
    return body_r + arm_min + arm_span * clamp01(frac)


def ease_step(current, target, eps: float = SETTLE_EPS, ease: float = EASE):
    nxt, moving = [], False
    for c, t in zip(current, target):
        c2 = c + (t - c) * ease
        if abs(t - c2) >= eps:
            moving = True
        nxt.append(c2)
    return nxt, moving


def breath_offset(phase: int, i: int, n: int,
                  amp_r: float = BREATH_AMP_R, amp_a: float = BREATH_AMP_A):
    dr = amp_r * math.sin(phase * 0.06)
    da = amp_a * math.sin(phase * 0.05 + i * (2 * math.pi / max(1, n)))
    return dr, da


class ThreadStar(QtWidgets.QWidget):
    """Rozgwiazda wątków: n ramion = n wątków CPU, długość ramienia = util,
    kolor z rampy util_rgb. Pulchne ramiona Béziera + ciągły oddech/kołysanie."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(220, 220)
        self._target: list[float] = []
        self._current: list[float] = []
        self._phase = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._advance)

    def set_threads(self, series: dict) -> None:
        n = thread_count(series)
        self._target = [clamp01((series.get(k) or 0.0) / 100.0) for k in thread_util_keys(n)]
        if len(self._current) != n:                    # liczba wątków zmieniła się → snap
            self._current = list(self._target)
        if n and not self._timer.isActive():
            self._timer.start()
        self.update()

    def _advance(self) -> None:
        self._phase += 1
        if self._current:
            self._current, _moving = ease_step(self._current, self._target)
        self.update()                                  # timer biegnie ciągle (oddech)

    def _arm_path(self, cx: float, cy: float, a: float, body_r: float,
                  reach: float, n: int) -> QtGui.QPainterPath:
        # baza ramienia na ciele, zaciśnięta pod sektor, by ramiona się nie zlewały
        half_ang = min(BASE_HALF_ANG, (math.pi / n) * 0.8)
        a0, a1 = a - half_ang, a + half_ang
        p0 = QtCore.QPointF(cx + body_r * math.cos(a0), cy + body_r * math.sin(a0))
        p1 = QtCore.QPointF(cx + body_r * math.cos(a1), cy + body_r * math.sin(a1))
        tip = QtCore.QPointF(cx + reach * math.cos(a), cy + reach * math.sin(a))
        mid = (body_r + reach) * 0.5                   # punkty kontrolne wybrzuszone na zewnątrz
        bow = half_ang * 1.6                           # → pulchne, zaokrąglone ramię (friendly)
        c0 = QtCore.QPointF(cx + mid * math.cos(a - bow), cy + mid * math.sin(a - bow))
        c1 = QtCore.QPointF(cx + mid * math.cos(a + bow), cy + mid * math.sin(a + bow))
        path = QtGui.QPainterPath(p0)
        path.quadTo(c0, tip)
        path.quadTo(c1, p1)
        path.closeSubpath()
        return path

    def paintEvent(self, _event) -> None:
        n = len(self._current)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        if n == 0:
            p.end()
            return
        cx, cy = self.width() / 2.0, self.height() / 2.0
        center = QtCore.QPointF(cx, cy)
        half = min(cx, cy)
        sc = max(0.1, (half - MARGIN) / R_MAX)
        dr_breath, _ = breath_offset(self._phase, 0, n)     # globalny puls (oddech)
        body_r = (R_BODY + dr_breath) * sc

        for i in range(n):
            frac = self._current[i]
            _, da = breath_offset(self._phase, i, n)
            a = arm_angle(i, n) + da
            reach = arm_reach(R_BODY + dr_breath, R_ARM_MIN, R_ARM_SPAN, frac) * sc
            r, g, b = util_rgb(frac)
            path = self._arm_path(cx, cy, a, body_r, reach, n)
            tip = QtCore.QPointF(cx + reach * math.cos(a), cy + reach * math.sin(a))
            grad = QtGui.QLinearGradient(center, tip)
            base_col = QtGui.QColor(r, g, b); base_col.setAlpha(70)
            tip_col = QtGui.QColor(r, g, b); tip_col.setAlpha(235)
            grad.setColorAt(0.0, base_col)
            grad.setColorAt(1.0, tip_col)
            if frac >= GLOW_THRESHOLD:                       # bloom dla rozgrzanych wątków
                glow = QtGui.QColor(r, g, b); glow.setAlpha(70)
                p.setPen(round_pen(glow, 10.0)); p.setBrush(QtCore.Qt.NoBrush)
                p.drawPath(path)
            p.setPen(round_pen(QtGui.QColor(r, g, b, 180), 1.4))
            p.setBrush(QtGui.QBrush(grad))
            p.drawPath(path)

        bg = QtGui.QRadialGradient(center, body_r)           # ciało rozgwiazdy na wierzchu
        bg.setColorAt(0.0, QtGui.QColor(60, 80, 110, 230))
        bg.setColorAt(1.0, QtGui.QColor(28, 40, 60, 180))
        p.setPen(round_pen(QtGui.QColor(120, 150, 180, 160), 1.4))
        p.setBrush(QtGui.QBrush(bg))
        p.drawEllipse(center, body_r, body_r)
        p.end()
