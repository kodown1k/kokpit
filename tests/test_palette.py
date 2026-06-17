from kokpit.ui.theme.palette import (
    DIM_FG,
    NEON_CYAN,
    alert_color,
    heat_rgb,
    qss_path,
    util_rgb,
    value_color,
)
import os


def test_alert_color_bands():
    assert alert_color(50) == "#39ff14"     # zielony < high
    assert alert_color(80) == "#ffb000"     # amber na progu high
    assert alert_color(99) == "#ffb000"
    assert alert_color(100) == "#ff2a2a"    # czerwony na crit
    assert alert_color(120) == "#ff2a2a"


def test_value_color_accent_then_amber_then_red():
    # 3 stany: spoczynek = neon accent, high → amber, crit → czerwień
    assert value_color(NEON_CYAN, 50, 80, 100) == NEON_CYAN   # spoczynek = akcent
    assert value_color(NEON_CYAN, 80, 80, 100) == "#ffb000"   # high → amber
    assert value_color(NEON_CYAN, 99, 80, 100) == "#ffb000"
    assert value_color(NEON_CYAN, 100, 80, 100) == "#ff2a2a"  # crit → czerwony alert
    assert value_color(NEON_CYAN, None, 80, 100) == DIM_FG    # brak danych → wygaszony


def test_value_color_none_thresholds_never_alert():
    # util: high=crit=None → zawsze akcent (max obciążenia to norma, nie awaria)
    assert value_color(NEON_CYAN, 99, None, None) == NEON_CYAN
    assert value_color(NEON_CYAN, 100, None, None) == NEON_CYAN


def test_util_rgb_neon_ramp_endpoints_and_clamp():
    # ciemny spoczynek → cyan → magenta (duch ghostty-vitals, „wypalenie")
    lo = util_rgb(0.0)
    hi = util_rgb(1.0)
    assert lo == util_rgb(-3)                # clamp dół
    assert hi == util_rgb(5)                 # clamp góra
    assert hi[0] > 200 and hi[2] > 150       # gorące = jasna magenta (R i B wysokie)
    assert sum(lo) < sum(util_rgb(0.5))      # rośnie jasność z obciążeniem


def test_heat_rgb_endpoints_and_clamp():
    assert heat_rgb(0.0) == (10, 12, 28)
    assert heat_rgb(1.0) == (255, 40, 80)
    assert heat_rgb(-5) == (10, 12, 28)     # clamp dół
    assert heat_rgb(9) == (255, 40, 80)     # clamp góra
    mid = heat_rgb(0.5)
    assert mid == (132, 26, 54)             # liniowa interpolacja


def test_qss_exists():
    assert os.path.isfile(qss_path())
