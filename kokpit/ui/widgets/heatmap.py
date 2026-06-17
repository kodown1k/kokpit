from PySide6 import QtWidgets

from kokpit.ui.theme.palette import heat_rgb, util_rgb


def thread_util_keys(n: int = 32) -> list[str]:
    return [f"cpu.thread.{i}.util" for i in range(n)]


def sorted_thermal_keys(names) -> list[str]:
    # klucze coretemp: thermal.coretemp.<cid>.core.<n> (cid = chip hwmon —
    # wielo-socket safe; n = nieciągły numer rdzenia). Sortuj po (cid, n).
    def _valid(name: str) -> bool:
        if not (name.startswith("thermal.coretemp.") and ".core." in name):
            return False
        parts = name.split(".")  # ["thermal","coretemp",<cid>,"core",<n>]
        return len(parts) == 5 and parts[2].isdigit() and parts[4].isdigit()

    def _key(name: str) -> tuple[int, int]:
        parts = name.split(".")
        return (int(parts[2]), int(parts[4]))

    return sorted((n for n in names if _valid(n)), key=_key)


def pkg_temp(series: dict) -> float | None:
    vals = [v for k, v in series.items()
            if k.startswith("thermal.coretemp.") and k.endswith(".pkg") and v is not None]
    return max(vals) if vals else None


class _CellGrid(QtWidgets.QWidget):
    def __init__(self, title: str, cols: int, ramp=heat_rgb) -> None:
        super().__init__()
        self._cols = cols
        self._ramp = ramp   # frac→(r,g,b); util→neon cyan/magenta, temp→thermal
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        label = QtWidgets.QLabel(title)
        label.setObjectName("tileTitle")
        lay.addWidget(label)
        self._grid = QtWidgets.QGridLayout()
        self._grid.setSpacing(3)
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
            cell.setStyleSheet(
                "background:#0a0f1a;border:1px solid #16263a;border-radius:3px;")
            return
        r, g, b = self._ramp(frac)
        # neonowy obrys w kolorze komórki = wrażenie poświaty bez per-cell efektu (fps)
        cell.setStyleSheet(
            f"background:rgb({r},{g},{b});"
            f"border:1px solid rgba({r},{g},{b},170);border-radius:3px;")


class CoreHeatmap(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._util = _CellGrid("THREAD UTIL (32)", cols=8, ramp=util_rgb)
        self._temp = _CellGrid("CORE TEMP (24)", cols=6, ramp=heat_rgb)
        lay.addWidget(self._util)
        lay.addWidget(self._temp)
        self._temp_keys: list[str] = []

    def set_util(self, series: dict) -> None:
        keys = thread_util_keys(32)
        self._util.ensure(len(keys))
        for i, k in enumerate(keys):
            v = series.get(k)
            self._util.paint(i, None if v is None else max(0.0, min(1.0, v / 100.0)))

    def set_temp(self, series: dict) -> None:
        seen = set(self._temp_keys) | set(sorted_thermal_keys(series.keys()))
        self._temp_keys = sorted_thermal_keys(seen)
        self._temp.ensure(len(self._temp_keys))
        for i, k in enumerate(self._temp_keys):
            v = series.get(k)
            # 20..100°C → 0..1
            self._temp.paint(i, None if v is None else max(0.0, min(1.0, (v - 20.0) / 80.0)))
