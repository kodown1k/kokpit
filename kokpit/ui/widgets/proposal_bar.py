from PySide6 import QtCore, QtWidgets


class ProposalBar(QtWidgets.QWidget):
    confirmed = QtCore.Signal(str)
    denied = QtCore.Signal(str)
    commandEntered = QtCore.Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._pid: str | None = None
        row = QtWidgets.QVBoxLayout(self)

        self._prop_row = QtWidgets.QWidget()
        pr = QtWidgets.QHBoxLayout(self._prop_row)
        self._label = QtWidgets.QLabel("")
        self._confirm_btn = QtWidgets.QPushButton("Zatwierdź")
        self._deny_btn = QtWidgets.QPushButton("Odrzuć")
        pr.addWidget(self._label, 1)
        pr.addWidget(self._confirm_btn)
        pr.addWidget(self._deny_btn)
        self._prop_row.hide()

        self._cmd = QtWidgets.QLineEdit()
        self._cmd.setPlaceholderText('polecenie… (np. „cicho na 30 min”, „zwolnij wszystko”)')

        row.addWidget(self._prop_row)
        row.addWidget(self._cmd)

        self._confirm_btn.clicked.connect(self._on_confirm)
        self._deny_btn.clicked.connect(self._on_deny)
        self._cmd.returnPressed.connect(self._on_cmd)

    def show_proposal(self, pid: str, text: str) -> None:
        self._pid = pid
        self._label.setText(text)
        self._prop_row.show()

    def clear(self) -> None:
        self._pid = None
        self._prop_row.hide()

    def _on_confirm(self) -> None:
        if self._pid:
            self.confirmed.emit(self._pid)
            self.clear()

    def _on_deny(self) -> None:
        if self._pid:
            self.denied.emit(self._pid)
            self.clear()

    def _on_cmd(self) -> None:
        text = self._cmd.text().strip()
        if text:
            self.commandEntered.emit(text)
            self._cmd.clear()
