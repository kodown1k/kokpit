from PySide6 import QtCore, QtWidgets

_COLS = ["PID", "NAME", "CPU%", "RSS MB", "VRAM MB"]


def bytes_to_mb(n: float) -> float:
    return float(n) / (1024 * 1024)


class ProcTableModel(QtCore.QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict] = []

    def set_rows(self, procs: list[dict]) -> None:
        self.beginResetModel()
        self._rows = procs
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
        if role != QtCore.Qt.DisplayRole:
            return None
        p = self._rows[index.row()]
        col = index.column()
        if col == 0:
            return str(p.get("pid", ""))
        if col == 1:
            return p.get("name", "")
        if col == 2:
            return f"{p.get('cpu', 0.0):.0f}"
        if col == 3:
            return f"{bytes_to_mb(p.get('rss', 0.0)):.0f}"
        if col == 4:
            return f"{bytes_to_mb(p.get('vram', 0.0)):.0f}"
        return None


class ProcTable(QtWidgets.QTableView):
    def __init__(self) -> None:
        super().__init__()
        self._model = ProcTableModel()
        self.setModel(self._model)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

    def set_rows(self, procs: list[dict]) -> None:
        self._model.set_rows(procs)
