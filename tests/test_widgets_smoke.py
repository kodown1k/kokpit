def test_make_plots_smoke(qapp):
    from kokpit.ui.plot import make_live_plot, make_history_plot, configured_curve
    lp = make_live_plot()
    c = configured_curve(lp, color=(0, 255, 200))
    c.setData([0, 1, 2], [1, 2, 3])
    hp = make_history_plot()
    assert lp is not None and hp is not None


def test_gauge_set_value(qapp):
    from kokpit.ui.widgets.gauge import Gauge
    g = Gauge("CPU PKG", "°C")
    g.set_value(95)            # amber
    g.set_value(None)          # brak danych — bez crasha
    assert g._value_label.text() == "--"


def test_sparkline_push(qapp):
    from kokpit.ui.widgets.sparkline import Sparkline
    s = Sparkline("GPU", window_s=5, y_range=(0, 100))
    for v in [10, 20, None, 30]:
        s.push(v)
    assert len(s._ys) == 3     # None pominięte
