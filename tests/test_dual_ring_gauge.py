def test_dual_ring_stores_outer_and_inner(qapp):
    from kokpit.ui.widgets.dual_ring_gauge import DualRingGauge
    g = DualRingGauge("TEMPS", "PCI", "MB", "#3df0ff", "#ff3cc8", high=75, crit=90)
    g.set_outer(53.0)
    g.set_inner(85.0)
    assert g._outer_val == 53.0
    assert g._inner_val == 85.0
    g.set_outer(None)
    assert g._outer_val is None          # brak danych → „--"


def test_dual_ring_render_smoke(qapp):
    from PySide6 import QtGui
    from kokpit.ui.widgets.dual_ring_gauge import DualRingGauge
    g = DualRingGauge("TEMPS", "PCI", "SSD", "#3df0ff", "#39ff14")
    g.set_outer(53.0)
    g.set_inner(None)                    # jeden ring bez danych — bez crasha
    g.resize(160, 160)
    img = QtGui.QImage(160, 160, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    g.render(img)
    assert img.width() == 160
