from kokpit.ui.widgets.sysinfo import format_uptime, gather_sysinfo


def test_format_uptime_buckets():
    assert format_uptime(90) == "1m"
    assert format_uptime(3661) == "1h 1m"
    assert format_uptime(90061) == "1d 1h 1m"
    assert format_uptime(0) == "0m"


def test_gather_sysinfo_kde_style_fields():
    rows = gather_sysinfo()
    assert rows and all(isinstance(lbl, str) and isinstance(val, str) for lbl, val in rows)
    labels = [lbl for lbl, _ in rows]
    # pola jak na ekranie KDE „About this System" (te zawsze dostępne)
    assert "Operating System" in labels
    assert "Kernel Version" in labels
    assert "Memory" in labels
    assert "Qt Version" in labels


def test_sysinfo_widget_smoke(qapp):
    from kokpit.ui.widgets.sysinfo import SysInfo
    w = SysInfo()
    w.refresh()                      # odświeżenie uptime bez crasha
    assert w._rows                   # zbudowane wiersze
