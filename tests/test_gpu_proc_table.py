from PySide6 import QtCore, QtGui

from kokpit.ui.theme.palette import NEON_CYAN, NEON_LIME, NEON_MAGENTA
from kokpit.ui.widgets.gpu_proc_table import (
    GpuProcTable,
    GpuProcTableModel,
    gpus_str,
)

_ROW = {"pid": 543701, "name": "uvicorn", "vram": 2766143488.0,
        "gpus": [0, 1], "type": "C", "sm": 30.0, "enc": 5.0, "dec": 0.0}


def test_gpus_str_joins_indices():
    assert gpus_str([0, 1]) == "0,1"
    assert gpus_str([2]) == "2"
    assert gpus_str([]) == ""


def test_headers_and_column_count():
    m = GpuProcTableModel()
    assert m.columnCount() == 8
    headers = [m.headerData(c, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole)
               for c in range(8)]
    assert headers == ["PID", "NAME", "TYPE", "GPU", "VRAM MB", "SM%", "ENC%", "DEC%"]


def test_row_display_formatting():
    m = GpuProcTableModel()
    m.set_rows([_ROW])

    def disp(col):
        return m.data(m.index(0, col), QtCore.Qt.DisplayRole)

    assert disp(0) == "543701"
    assert disp(1) == "uvicorn"
    assert disp(2) == "C"
    assert disp(3) == "0,1"
    assert disp(4) == "2638"      # 2766143488 / 2^20, zaokrąglone
    assert disp(5) == "30"
    assert disp(6) == "5"
    assert disp(7) == "0"


def test_type_cell_is_color_coded():
    m = GpuProcTableModel()
    m.set_rows([
        {**_ROW, "type": "C"},
        {**_ROW, "type": "G"},
        {**_ROW, "type": "C+G"},
    ])

    def fg(r):
        return m.data(m.index(r, 2), QtCore.Qt.ForegroundRole)

    assert fg(0) == QtGui.QColor(NEON_CYAN)      # compute
    assert fg(1) == QtGui.QColor(NEON_MAGENTA)   # graphics
    assert fg(2) == QtGui.QColor(NEON_LIME)      # oba


def test_numeric_columns_right_aligned():
    m = GpuProcTableModel()
    m.set_rows([_ROW])
    for col in (0, 4, 5, 6, 7):
        align = m.data(m.index(0, col), QtCore.Qt.TextAlignmentRole)
        assert align & QtCore.Qt.AlignRight
    # NAME zostaje do lewej (brak wymuszonego prawego wyrównania)
    assert not (m.data(m.index(0, 1), QtCore.Qt.TextAlignmentRole) or 0) & QtCore.Qt.AlignRight


def test_widget_empty_state_toggles_placeholder(qapp):
    t = GpuProcTable()
    t.set_rows([])
    assert t._model.rowCount() == 0
    assert t._placeholder.isVisibleTo(t.viewport())   # pusto → placeholder
    t.set_rows([_ROW])
    assert t._model.rowCount() == 1
    assert not t._placeholder.isVisibleTo(t.viewport())
