import os

from kokpit.ui.theme.palette import app_icon_path


def test_app_icon_asset_present():
    assert os.path.exists(app_icon_path())
    assert app_icon_path().endswith("app-icon.png")


def test_app_icon_loads_non_null(qapp):
    from PySide6 import QtGui
    icon = QtGui.QIcon(app_icon_path())
    assert not icon.isNull()
