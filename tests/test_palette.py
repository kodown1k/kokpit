from kokpit.ui.theme.palette import alert_color, heat_rgb, qss_path
import os


def test_alert_color_bands():
    assert alert_color(50) == "#39ff14"     # zielony < high
    assert alert_color(80) == "#ffb000"     # amber na progu high
    assert alert_color(99) == "#ffb000"
    assert alert_color(100) == "#ff2a2a"    # czerwony na crit
    assert alert_color(120) == "#ff2a2a"


def test_heat_rgb_endpoints_and_clamp():
    assert heat_rgb(0.0) == (10, 12, 28)
    assert heat_rgb(1.0) == (255, 40, 80)
    assert heat_rgb(-5) == (10, 12, 28)     # clamp dół
    assert heat_rgb(9) == (255, 40, 80)     # clamp góra
    mid = heat_rgb(0.5)
    assert mid == (132, 26, 54)             # liniowa interpolacja


def test_qss_exists():
    assert os.path.isfile(qss_path())
