from PySide6 import QtWidgets

from kokpit.ui.theme.palette import alert_color


class Gauge(QtWidgets.QWidget):
    def __init__(self, title: str, unit: str = "", high: float = 80, crit: float = 100) -> None:
        super().__init__()
        self._unit = unit
        self._high = high
        self._crit = crit
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        self._title = QtWidgets.QLabel(title)
        self._title.setObjectName("tileTitle")
        self._value_label = QtWidgets.QLabel("--")
        f = self._value_label.font()
        f.setPointSize(20)
        f.setBold(True)
        self._value_label.setFont(f)
        lay.addWidget(self._title)
        lay.addWidget(self._value_label)

    def set_value(self, value: float | None) -> None:
        if value is None:
            self._value_label.setText("--")
            self._value_label.setStyleSheet("color:#445;")
            return
        self._value_label.setText(f"{value:.0f}{self._unit}")
        self._value_label.setStyleSheet(f"color:{alert_color(value, self._high, self._crit)};")
