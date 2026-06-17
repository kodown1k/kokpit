"""Siatka mini-ringów: 32 thread-util + 24 core-temp, rysowane w JEDNYM paintEvent
(jeden przebieg na snapshot, bez per-ring tweenów — ochrona budżetu fps z W2).
Klucze i latching wzięte z heatmap.py (współdzielone z dawną CoreHeatmap)."""
from PySide6 import QtCore, QtGui, QtWidgets

from kokpit.ui.theme.palette import heat_rgb, round_pen, util_rgb
from kokpit.ui.widgets.heatmap import sorted_thermal_keys, thread_util_keys

UTIL_N = 32
UTIL_COLS = 8
TEMP_COLS = 6
CELL = 17
GAP = 7
PAD = 2
LABEL_H = 16


def ring_rects(n: int, cols: int, cell: int, gap: int, x0: int = 0, y0: int = 0):
    """Pozycje n komórek w siatce `cols`-kolumnowej: (x, y, w, h)."""
    return [(x0 + (i % cols) * (cell + gap), y0 + (i // cols) * (cell + gap), cell, cell)
            for i in range(n)]


def _util_frac(v):
    return None if v is None else max(0.0, min(1.0, v / 100.0))


def _temp_frac(v):
    return None if v is None else max(0.0, min(1.0, (v - 20.0) / 80.0))   # 20..100°C → 0..1


class CoreRingGrid(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._util = [None] * UTIL_N
        self._temp_keys: list[str] = []
        self._temp_frac: dict[str, float | None] = {}
        util_rows = (UTIL_N + UTIL_COLS - 1) // UTIL_COLS
        self.setMinimumWidth(UTIL_COLS * (CELL + GAP) + 2 * PAD)
        self.setMinimumHeight(2 * LABEL_H + (util_rows + 4) * (CELL + GAP) + 2 * PAD)

    def set_util(self, series: dict) -> None:
        self._util = [_util_frac(series.get(k)) for k in thread_util_keys(UTIL_N)]
        self.update()

    def set_temp(self, series: dict) -> None:
        # latch kluczy: siatka nie kurczy się, gdy rdzeń chwilowo zniknie (jak w heatmapie)
        seen = set(self._temp_keys) | set(sorted_thermal_keys(series.keys()))
        self._temp_keys = sorted_thermal_keys(seen)
        self._temp_frac = {k: _temp_frac(series.get(k)) for k in self._temp_keys}
        self.update()

    def _paint_section(self, p: QtGui.QPainter, fracs, cols, y0, ramp) -> int:
        rects = ring_rects(len(fracs), cols, CELL, GAP, x0=PAD, y0=y0)
        for (x, y, w, h), frac in zip(rects, fracs):
            r = QtCore.QRectF(x, y, w, h)
            p.setPen(QtGui.QPen(QtGui.QColor("#16263a"), 2))
            p.drawArc(r, 0, 360 * 16)                       # tor (pełny pierścień)
            if frac is not None:
                p.setPen(round_pen(ramp(frac), 2))
                p.drawArc(r, 90 * 16, int(-360 * 16 * frac))   # wypełnienie od góry
        rows = (len(fracs) + cols - 1) // cols
        return y0 + rows * (CELL + GAP)

    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        f = p.font()
        f.setBold(True)
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(QtGui.QColor("#5fb8d6"))
        p.drawText(PAD, 12, "THREAD UTIL (32)")
        y = self._paint_section(p, self._util, UTIL_COLS, LABEL_H, util_rgb)
        y += LABEL_H
        p.setPen(QtGui.QColor("#5fb8d6"))
        p.drawText(PAD, y - 4, f"CORE TEMP ({len(self._temp_keys)})")
        self._paint_section(p, [self._temp_frac.get(k) for k in self._temp_keys],
                            TEMP_COLS, y, heat_rgb)
        p.end()
