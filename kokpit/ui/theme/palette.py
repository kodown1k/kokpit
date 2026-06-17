import os

from PySide6 import QtCore, QtGui, QtWidgets

HIGH_C = 80.0
CRIT_C = 100.0

# --- Cyberpunk neon / NOC trio (styl 1) -------------------------------------
# Spoczynkowe akcenty kafelków; alert eskaluje na amber→czerwony (świeci).
NEON_CYAN = "#3df0ff"      # util, sieć, chrome
NEON_MAGENTA = "#ff3cc8"   # temperatury / nagłówkowe „hot" wartości
NEON_LIME = "#39ff14"      # dysk, OK/zielony
DIM_FG = "#39506a"         # brak danych / wygaszone

_GREEN = "#39ff14"
_AMBER = "#ffb000"
_RED = "#ff2a2a"

# rampa termiczna: zimny granat → gorąca magenta-czerwień (kontrakt z testów)
_COLD = (10, 12, 28)
_HOT = (255, 40, 80)

# rampa util: ciemny spoczynek → cyan → magenta (neon „wypalenie")
_U0 = (12, 22, 34)
_U1 = (61, 240, 255)   # cyan w połowie
_U2 = (255, 60, 220)   # magenta na maxie


def alert_color(value: float, high: float = HIGH_C, crit: float = CRIT_C) -> str:
    if value >= crit:
        return _RED
    if value >= high:
        return _AMBER
    return _GREEN


def value_color(accent: str, value: float | None,
                high: float | None, crit: float | None) -> str:
    """Kolor żywej wartości — 3 stany: w spoczynku świeci neonowym *akcentem*
    kafelka, po przekroczeniu `high` ostrzega amber, po `crit` zapala czerwień
    alertu. Progi opcjonalne: `high=crit=None` → zawsze akcent (np. utylizacja —
    max to norma, nie awaria). None → wygaszony (DIM_FG)."""
    if value is None:
        return DIM_FG
    if crit is not None and value >= crit:
        return _RED
    if high is not None and value >= high:
        return _AMBER
    return accent


def heat_rgb(frac: float) -> tuple[int, int, int]:
    f = 0.0 if frac < 0 else 1.0 if frac > 1 else frac
    return tuple(int(c0 + (c1 - c0) * f) for c0, c1 in zip(_COLD, _HOT))


def util_rgb(frac: float) -> tuple[int, int, int]:
    """Neonowa rampa obciążenia: ciemny→cyan→magenta (dwa odcinki liniowe)."""
    f = 0.0 if frac < 0 else 1.0 if frac > 1 else frac
    if f <= 0.5:
        t = f / 0.5
        a, b = _U0, _U1
    else:
        t = (f - 0.5) / 0.5
        a, b = _U1, _U2
    return tuple(int(c0 + (c1 - c0) * t) for c0, c1 in zip(a, b))


def _qcolor(color) -> QtGui.QColor:
    if isinstance(color, QtGui.QColor):
        return color
    return QtGui.QColor(color) if isinstance(color, str) else QtGui.QColor(*color)


def round_pen(color, width: float) -> QtGui.QPen:
    """QPen z RoundCap. (PySide6 nie przyjmuje `cap=` jako kwarg konstruktora —
    trzeba setCapStyle.) `color`: hex str, (r,g,b) lub QColor."""
    pen = QtGui.QPen(_qcolor(color), float(width))
    pen.setCapStyle(QtCore.Qt.RoundCap)
    return pen


def apply_glow(widget: QtWidgets.QWidget, color, radius: float = 16.0):
    """Fosforowa poświata: zero-offset kolorowy drop-shadow = bloom wokół
    nieprzezroczystych pikseli (tekst/ikona). Statyczne i tanie (spec §4.6) —
    stosować na etykietach/wartościach, NIE na stosach krzywych.

    Zwraca efekt, by widget mógł aktualizować jego kolor (np. alert→czerwień)."""
    eff = QtWidgets.QGraphicsDropShadowEffect(widget)
    eff.setOffset(0.0, 0.0)
    eff.setBlurRadius(radius)
    eff.setColor(_qcolor(color))
    widget.setGraphicsEffect(eff)
    return eff


def qss_path() -> str:
    return os.path.join(os.path.dirname(__file__), "neon.qss")
