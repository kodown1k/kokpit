from kokpit.ui.widgets.sysinfo import (
    format_cuda_version,
    format_uptime,
    gather_sysinfo,
    sysinfo_sections,
)


def test_format_uptime_buckets():
    assert format_uptime(90) == "1m"
    assert format_uptime(3661) == "1h 1m"
    assert format_uptime(90061) == "1d 1h 1m"
    assert format_uptime(0) == "0m"


def test_format_cuda_version():
    assert format_cuda_version(12040) == "12.4"
    assert format_cuda_version(11080) == "11.8"


def test_gather_sysinfo_kde_style_fields():
    rows = gather_sysinfo()
    assert rows and all(isinstance(lbl, str) and isinstance(val, str) for lbl, val in rows)
    labels = [lbl for lbl, _ in rows]
    assert "Operating System" in labels
    assert "Kernel Version" in labels
    assert "Memory" in labels
    assert "Qt Version" in labels


def test_sysinfo_sections_have_system_and_cpu_groups():
    # SYSTEM i CPU są zawsze obecne (platform/psutil); MOTHERBOARD (DMI) i GPU (NVML)
    # bywają puste na VM/CI — sekcja jest wtedy pomijana, więc ich nie wymuszamy.
    secs = sysinfo_sections()
    names = [name for name, _rows in secs]
    assert "SYSTEM" in names
    assert "CPU" in names
    for _name, rows in secs:
        assert rows                                                       # pusta sekcja nie trafia na listę
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in rows)


def test_sysinfo_widget_has_scroll_and_rows(qapp):
    from PySide6 import QtWidgets
    from kokpit.ui.widgets.sysinfo import SysInfo
    w = SysInfo()
    w.refresh()
    assert w._rows                                                   # zbudowane wiersze
    assert w.findChild(QtWidgets.QScrollArea) is not None            # scroll zamiast rozpychania
