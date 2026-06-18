from PySide6 import QtCore, QtGui, QtWidgets

from kokpit.ui.theme.palette import DIM_FG, NEON_CYAN, NEON_LIME, NEON_MAGENTA
from kokpit.ui.widgets.proc_table import bytes_to_mb

_COLS = ["PID", "NAME", "TYPE", "GPU", "VRAM MB", "SM%", "ENC%", "DEC%"]
_RIGHT = {0, 4, 5, 6, 7}                       # kolumny liczbowe → do prawej
_TYPE_COLOR = {"C": NEON_CYAN, "G": NEON_MAGENTA, "C+G": NEON_LIME}


def gpus_str(gpus) -> str:
    """[0, 1] → '0,1' (indeksy kart, na których proces ma kontekst)."""
    return ",".join(str(g) for g in gpus)


class GpuProcTableModel(QtCore.QAbstractTableModel):
    """Tabela procesów GPU (NVML `gpu_procs`): VRAM, typ C/G/C+G, karty, util SM/enc/dec."""

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict] = []

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return len(_COLS)

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if orientation == QtCore.Qt.Horizontal and role == QtCore.Qt.DisplayRole:
            return _COLS[section]
        return None

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        col = index.column()
        if role == QtCore.Qt.TextAlignmentRole:
            if col in _RIGHT:
                return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            return int(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        if role == QtCore.Qt.ForegroundRole and col == 2:
            return QtGui.QColor(_TYPE_COLOR.get(r.get("type", ""), DIM_FG))
        if role != QtCore.Qt.DisplayRole:
            return None
        if col == 0:
            return str(r.get("pid", ""))
        if col == 1:
            return r.get("name", "")
        if col == 2:
            return r.get("type", "")
        if col == 3:
            return gpus_str(r.get("gpus", []))
        if col == 4:
            return f"{bytes_to_mb(r.get('vram', 0.0)):.0f}"
        if col == 5:
            return f"{r.get('sm', 0.0):.0f}"
        if col == 6:
            return f"{r.get('enc', 0.0):.0f}"
        if col == 7:
            return f"{r.get('dec', 0.0):.0f}"
        return None


class GpuProcTable(QtWidgets.QTableView):
    def __init__(self) -> None:
        super().__init__()
        self._model = GpuProcTableModel()
        self.setModel(self._model)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        hh = self.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)   # NAME bierze luz

        # stan pusty (brak NVML / brak procesów na GPU) — placeholder nad viewportem
        self._placeholder = QtWidgets.QLabel("brak procesów GPU", self.viewport())
        self._placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self._placeholder.setStyleSheet(f"color:{DIM_FG};font-style:italic;")
        self._placeholder.hide()

    def set_rows(self, rows: list[dict]) -> None:
        self._model.set_rows(rows)
        self._placeholder.setVisible(not rows)
        self._place_overlay()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_overlay()

    def _place_overlay(self) -> None:
        self._placeholder.setGeometry(self.viewport().rect())
