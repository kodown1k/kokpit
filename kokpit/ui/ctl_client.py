import socket

from PySide6 import QtCore

from kokpit.actuator import protocol as p


class ControlClient(QtCore.QObject):
    error = QtCore.Signal(str)

    def __init__(self, sock_path: str) -> None:
        super().__init__()
        self._path = sock_path

    def request(self, verb: str, args: dict) -> p.Response:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect(self._path)
            s.sendall(p.encode_request(p.Request(verb, args)))
            with s.makefile("rb") as f:
                line = f.readline()
            s.close()
            return p.decode_response(line)
        except OSError as e:
            self.error.emit(str(e))
            return p.Response(ok=False, error=str(e))

    def poll_proposals(self) -> list[dict]:
        r = self.request("propose", {})
        return r.data.get("proposals", []) if r.ok else []
