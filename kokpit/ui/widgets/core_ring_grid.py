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
SECTION_GAP = 22   # odstęp poziomy między blokiem THREAD UTIL a CORE TEMP


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
        self._temp_fracs: dict[str, float | None] = {}
        util_rows = (UTIL_N + UTIL_COLS - 1) // UTIL_COLS
        util_w = UTIL_COLS * (CELL + GAP)
        temp_w = TEMP_COLS * (CELL + GAP)
        # util ‖ temp obok siebie → szerokość = suma bloków, wysokość = wyższy z bloków
        self.setMinimumWidth(PAD + util_w + SECTION_GAP + temp_w + PAD)
        self.setMinimumHeight(LABEL_H + (util_rows + 1) * (CELL + GAP) + 2 * PAD)

    def set_util(self, series: dict) -> None:
        self._util = [_util_frac(series.get(k)) for k in thread_util_keys(UTIL_N)]
        self.update()

    def set_temp(self, series: dict) -> None:
        # latch kluczy: siatka nie kurczy się, gdy rdzeń chwilowo zniknie (jak w heatmapie)
        seen = set(self._temp_keys) | set(sorted_thermal_keys(series.keys()))
        self._temp_keys = sorted_thermal_keys(seen)
        self._temp_fracs = {k: _temp_frac(series.get(k)) for k in self._temp_keys}
        self.update()

    def _paint_section(self, p: QtGui.QPainter, fracs, cols, y0, ramp, x0=PAD) -> int:
        rects = ring_rects(len(fracs), cols, CELL, GAP, x0=x0, y0=y0)
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
        temp_x0 = PAD + UTIL_COLS * (CELL + GAP) + SECTION_GAP   # blok temp na prawo od util
        p.setPen(QtGui.QColor("#5fb8d6"))
        p.drawText(PAD, 12, "THREAD UTIL (32)")
        p.drawText(temp_x0, 12, f"CORE TEMP ({len(self._temp_keys)})")
        self._paint_section(p, self._util, UTIL_COLS, LABEL_H, util_rgb)
        self._paint_section(p, [self._temp_fracs.get(k) for k in self._temp_keys],
                            TEMP_COLS, LABEL_H, heat_rgb, x0=temp_x0)
        p.end()
