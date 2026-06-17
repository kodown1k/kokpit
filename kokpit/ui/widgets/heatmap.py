import math

from PySide6 import QtWidgets

from kokpit.ui.theme.palette import heat_rgb


def thread_util_keys(n: int = 32) -> list[str]:
    return [f"cpu.thread.{i}.util" for i in range(n)]


def sorted_thermal_keys(names) -> list[str]:
    cores = [n for n in names if n.startswith("thermal.core.")]
    return sorted(cores, key=lambda n: int(n.rsplit(".", 1)[1]))


class _CellGrid(QtWidgets.QWidget):
    def __init__(self, title: str, cols: int) -> None:
        super().__init__()
        self._cols = cols
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        label = QtWidgets.QLabel(title)
        label.setObjectName("tileTitle")
        lay.addWidget(label)
        self._grid = QtWidgets.QGridLayout()
        self._grid.setSpacing(2)
        lay.addLayout(self._grid)
        self._cells: list[QtWidgets.QFrame] = []

    def ensure(self, count: int) -> None:
        while len(self._cells) < count:
            cell = QtWidgets.QFrame()
            cell.setFixedSize(18, 18)
            i = len(self._cells)
            self._grid.addWidget(cell, i // self._cols, i % self._cols)
            self._cells.append(cell)

    def paint(self, index: int, frac: float | None) -> None:
        cell = self._cells[index]
        if frac is None:
            cell.setStyleSheet("background:#0c111b;border:1px solid #14202e;")
            return
        r, g, b = heat_rgb(frac)
        cell.setStyleSheet(f"background:rgb({r},{g},{b});border:1px solid #14202e;")


class CoreHeatmap(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._util = _CellGrid("THREAD UTIL (32)", cols=8)
        self._temp = _CellGrid("CORE TEMP (24)", cols=6)
        lay.addWidget(self._util)
        lay.addWidget(self._temp)

    def set_util(self, series: dict) -> None:
        keys = thread_util_keys(32)
        self._util.ensure(len(keys))
        for i, k in enumerate(keys):
            v = series.get(k)
            self._util.paint(i, None if v is None else max(0.0, min(1.0, v / 100.0)))

    def set_temp(self, series: dict) -> None:
        keys = sorted_thermal_keys(series.keys())
        self._temp.ensure(len(keys))
        for i, k in enumerate(keys):
            v = series.get(k)
            # 20..100°C → 0..1
            self._temp.paint(i, None if v is None else max(0.0, min(1.0, (v - 20.0) / 80.0)))
