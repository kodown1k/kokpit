import pytest


def test_multi_ring_stores_values(qapp):
    from kokpit.ui.widgets.multi_ring_gauge import MultiRingGauge
    g = MultiRingGauge("NVME TEMPS", [("N0", "#3df0ff"), ("N1", "#ff3cc8"), ("N2", "#39ff14")],
                       high=70, crit=80)
    g.set_values([41.0, 52.0, None])
    assert g._vals == [41.0, 52.0, None]


def test_multi_ring_defensive_lengths(qapp):
    from kokpit.ui.widgets.multi_ring_gauge import MultiRingGauge
    g = MultiRingGauge("T", [("A", "#3df0ff"), ("B", "#ff3cc8"), ("C", "#39ff14")])
    g.set_values([41.0])                      # za krótko → reszta None
    assert g._vals == [41.0, None, None]
    g.set_values([1.0, 2.0, 3.0, 4.0])        # za długo → nadmiar ignorowany
    assert g._vals == [1.0, 2.0, 3.0]


def test_ring_width_adapts():
    from kokpit.ui.widgets.multi_ring_gauge import ring_width
    assert ring_width(128, 2) == 9.0                      # małe N → dzisiejsza grubość Dual
    assert ring_width(128, 3) == 9.0
    assert ring_width(128, 5) == pytest.approx(0.6 * 48 / 5)   # więcej ringów → cieńsze


def test_multi_ring_render_smoke(qapp):
    from PySide6 import QtGui
    from kokpit.ui.widgets.multi_ring_gauge import MultiRingGauge
    g = MultiRingGauge("TEMPS", [("PCI", "#3df0ff"), ("MB", "#39ff14"), ("N0", "#ff3cc8")])
    g.set_values([53.0, None, 44.0])          # ring bez danych — bez crasha
    g.resize(160, 160)
    img = QtGui.QImage(160, 160, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    g.render(img)
    assert img.width() == 160
