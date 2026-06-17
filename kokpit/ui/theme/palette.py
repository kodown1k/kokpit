import os

HIGH_C = 80.0
CRIT_C = 100.0

_GREEN = "#39ff14"
_AMBER = "#ffb000"
_RED = "#ff2a2a"

_COLD = (10, 12, 28)
_HOT = (255, 40, 80)


def alert_color(value: float, high: float = HIGH_C, crit: float = CRIT_C) -> str:
    if value >= crit:
        return _RED
    if value >= high:
        return _AMBER
    return _GREEN


def heat_rgb(frac: float) -> tuple[int, int, int]:
    f = 0.0 if frac < 0 else 1.0 if frac > 1 else frac
    return tuple(int(c0 + (c1 - c0) * f) for c0, c1 in zip(_COLD, _HOT))


def qss_path() -> str:
    return os.path.join(os.path.dirname(__file__), "neon.qss")
