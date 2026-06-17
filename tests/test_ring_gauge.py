from kokpit.ui.widgets.ring_gauge import ring_fraction, arc_span


def test_ring_fraction_clamps():
    assert ring_fraction(50) == 0.5
    assert ring_fraction(0) == 0.0
    assert ring_fraction(150) == 1.0          # clamp góra
    assert ring_fraction(-5) == 0.0           # clamp dół
    assert ring_fraction(None) == 0.0         # brak danych → pusty łuk
    assert ring_fraction(6144, 8192) == 0.75  # własny vmax


def test_arc_span_proportional():
    assert arc_span(0.0) == 0.0
    assert arc_span(1.0) == -270.0            # pełny sweep (270°, przerwa u dołu)
    assert arc_span(0.5) == -135.0
    assert arc_span(2.0) == -270.0            # clamp
    assert arc_span(0.5, sweep_deg=300) == -150.0


def test_ring_gauge_set_value(qapp):
    from kokpit.ui.widgets.ring_gauge import RingGauge
    g = RingGauge("CPU", "#3df0ff")
    g.set_value(63)
    assert g._target == 63
    g.set_value(None)                          # brak danych
    assert g._value is None
