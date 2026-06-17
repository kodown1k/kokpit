from PySide6 import QtCore, QtGui, QtWidgets

from kokpit.ui.theme.palette import NEON_CYAN, apply_glow, value_color


class Gauge(QtWidgets.QWidget):
    def __init__(self, title: str, unit: str = "", high: float | None = None,
                 crit: float | None = None, accent: str = NEON_CYAN) -> None:
        super().__init__()
        self._unit = unit
        self._high = high          # próg ostrzeżenia (amber); None → bez amber
        self._crit = crit          # próg alertu (czerwień); None → kafelek nigdy nie alarmuje
        self._accent = accent
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)
        self._title = QtWidgets.QLabel(title)
        self._title.setObjectName("tileTitle")
        self._value_label = QtWidgets.QLabel("--")
        self._value_label.setObjectName("gaugeValue")
        f = self._value_label.font()
        f.setPointSize(26)
        f.setBold(True)
        self._value_label.setFont(f)
        self._value_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        # fosforowy bloom wokół cyfr — kolor śledzi stan (akcent → amber → czerwień)
        self._glow = apply_glow(self._value_label, accent, radius=22.0)
        lay.addWidget(self._title)
        lay.addWidget(self._value_label)

    def set_value(self, value: float | None) -> None:
        if value is None:
            self._value_label.setText("--")
            self._value_label.setStyleSheet("color:#39506a;")
            self._glow.setEnabled(False)        # brak danych → bez poświaty
            return
        color = value_color(self._accent, value, self._high, self._crit)
        self._value_label.setText(f"{value:.0f}{self._unit}")
        self._value_label.setStyleSheet(f"color:{color};")
        self._glow.setColor(QtGui.QColor(color))
        self._glow.setEnabled(True)
