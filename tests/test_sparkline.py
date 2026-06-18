def test_sparkline_scales_pushed_value(qapp):
    from kokpit.ui.widgets.sparkline import Sparkline
    s = Sparkline("NET rx", scale=1.0 / 1024)
    s.push(2048)                      # 2048 B/s → 2.0 KB/s
    assert s._ys[-1] == 2.0


def test_sparkline_default_scale_is_identity(qapp):
    from kokpit.ui.widgets.sparkline import Sparkline
    s = Sparkline("X")
    s.push(7.0)
    assert s._ys[-1] == 7.0
