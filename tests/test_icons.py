import pytest

from kokpit.ui.theme.icons import ICON_NAMES, ICONS_DIR, neon_pixmap, recolored_svg


def test_recolor_swaps_currentcolor():
    s = recolored_svg("cpu", "#3df0ff")
    assert "#3df0ff" in s
    assert "currentColor" not in s


def test_icon_registry_matches_svg_files():
    # invariant (nie magiczna liczba): rejestr ↔ pliki .svg to bijekcja —
    # łapie i sierotę bez wpisu, i wpis bez pliku; dodanie ikony wymaga obu.
    for n in ICON_NAMES:
        assert recolored_svg(n, "#ffffff")     # każda zarejestrowana ikona ma plik SVG
    assert {p.stem for p in ICONS_DIR.glob("*.svg")} == set(ICON_NAMES)


def test_bad_icon_name_raises():
    with pytest.raises(FileNotFoundError):
        recolored_svg("nope", "#ffffff")


def test_neon_pixmap_renders(qapp):
    pm = neon_pixmap("gpu", "#39ff14", 20)
    assert not pm.isNull()
    assert pm.width() == 20 and pm.height() == 20
