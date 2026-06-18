from kokpit.ui.widgets.disk_usage import disk_usages, format_gib


def test_format_gib():
    assert format_gib(2 ** 30) == "1.0"
    assert format_gib(0) == "0.0"


def test_disk_usages_returns_mount_used_total():
    rows = disk_usages()
    assert isinstance(rows, list)
    for mount, used, total in rows:
        assert isinstance(mount, str)
        assert 0 <= used <= total
        assert total > 0


def test_disk_usage_widget_smoke(qapp):
    from kokpit.ui.widgets.disk_usage import DiskUsage
    w = DiskUsage()
    w.refresh()
    from PySide6 import QtGui
    img = QtGui.QImage(220, 160, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    w.resize(220, 160)
    w.render(img)            # paintEvent bez crasha (też przy 0 dyskach)
    assert img.width() == 220
