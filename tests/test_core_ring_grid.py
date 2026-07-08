from kokpit.ui.widgets.core_ring_grid import ring_rects


def test_ring_rects_grid():
    r = ring_rects(4, cols=2, cell=10, gap=2)
    assert len(r) == 4
    assert r[0] == (0, 0, 10, 10)
    assert r[1] == (12, 0, 10, 10)
    assert r[2] == (0, 12, 10, 10)
    assert r[3] == (12, 12, 10, 10)


def test_ring_rects_offset():
    r = ring_rects(2, cols=4, cell=8, gap=4, x0=5, y0=7)
    assert r[0] == (5, 7, 8, 8)
    assert r[1] == (17, 7, 8, 8)


def test_core_ring_grid_latches_temp(qapp):
    from kokpit.ui.widgets.core_ring_grid import CoreRingGrid
    g = CoreRingGrid()
    g.set_util({f"cpu.thread.{i}.util": (i * 3) % 100 for i in range(32)})
    g.set_temp({f"thermal.coretemp.3.core.{i}": 40 + i for i in (0, 4, 8, 12, 16, 20)})
    assert len(g._temp_keys) == 6
    # jeden rdzeń znika w kolejnym ticku — siatka NIE kurczy się (latching jak w heatmapie)
    g.set_temp({f"thermal.coretemp.3.core.{i}": 40 + i for i in (4, 8, 12, 16, 20)})
    assert len(g._temp_keys) == 6


def test_core_ring_grid_stores_raw_temps(qapp):
    from kokpit.ui.widgets.core_ring_grid import CoreRingGrid
    g = CoreRingGrid()
    g.set_temp({"thermal.coretemp.3.core.0": 47.6})
    assert g._temp_vals["thermal.coretemp.3.core.0"] == 47.6
    g.set_temp({})                                   # klucz latchuje, wartość znika
    assert g._temp_vals["thermal.coretemp.3.core.0"] is None


def test_core_ring_grid_temp_cells_wider(qapp):
    from kokpit.ui.widgets.core_ring_grid import (
        CELL, GAP, PAD, SECTION_GAP, TEMP_CELL, TEMP_COLS, UTIL_COLS, CoreRingGrid,
    )
    assert TEMP_CELL > CELL                          # komórka temp mieści liczbę °C
    g = CoreRingGrid()
    assert g.minimumWidth() == (PAD + UTIL_COLS * (CELL + GAP) + SECTION_GAP
                                + TEMP_COLS * (TEMP_CELL + GAP) + PAD)


def test_core_ring_grid_render_smoke_numbers(qapp):
    from PySide6 import QtGui
    from kokpit.ui.widgets.core_ring_grid import CoreRingGrid
    g = CoreRingGrid()
    g.set_util({f"cpu.thread.{i}.util": (i * 3) % 100 for i in range(32)})
    g.set_temp({f"thermal.coretemp.3.core.{i}": 40 + i for i in (0, 4, 8)})
    g.resize(g.minimumWidth(), g.minimumHeight())
    img = QtGui.QImage(g.width(), g.height(), QtGui.QImage.Format_ARGB32)
    img.fill(0)
    g.render(img)
    assert img.width() == g.width()
