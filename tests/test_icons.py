import pytest

from kokpit.ui.theme.icons import ICON_NAMES, neon_pixmap, recolored_svg


def test_recolor_swaps_currentcolor():
    s = recolored_svg("cpu", "#3df0ff")
    assert "#3df0ff" in s
    assert "currentColor" not in s


def test_all_icon_names_load():
    assert len(ICON_NAMES) >= 11
    for n in ICON_NAMES:
        assert recolored_svg(n, "#ffffff")     # każda zarejestrowana ikona ma plik SVG


def test_bad_icon_name_raises():
    with pytest.raises(FileNotFoundError):
        recolored_svg("nope", "#ffffff")


def test_neon_pixmap_renders(qapp):
    pm = neon_pixmap("gpu", "#39ff14", 20)
    assert not pm.isNull()
    assert pm.width() == 20 and pm.height() == 20
