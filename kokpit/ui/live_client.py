import json
import socket
import threading
import time

from PySide6 import QtCore


def iter_ndjson(buf: bytes) -> tuple[list[dict], bytes]:
    """Wytnij kompletne linie JSON z bufora; zwróć (obiekty, niedokończony ogon)."""
    objs: list[dict] = []
    while True:
        nl = buf.find(b"\n")
        if nl == -1:
            return objs, buf
        line, buf = buf[:nl], buf[nl + 1:]
        line = line.strip()
        if line:
            objs.append(json.loads(line.decode()))


class LiveClient(QtCore.QObject):
    snapshot = QtCore.Signal(dict)
    state = QtCore.Signal(str)

    def __init__(self, sock_path: str, stale_after_s: float = 3.0) -> None:
        super().__init__()
        self._sock_path = sock_path
        self._stale_after = stale_after_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)

    def _run(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                sock.connect(self._sock_path)
            except OSError:
                self.state.emit("disconnected")
                if self._stop.wait(backoff):
                    return
                backoff = min(backoff * 2, 5.0)
                continue
            backoff = 0.5
            self.state.emit("connected")
            buf = b""
            last = time.monotonic()
            try:
                while not self._stop.is_set():
                    try:
                        chunk = sock.recv(65536)
                    except socket.timeout:
                        if time.monotonic() - last > self._stale_after:
                            self.state.emit("stale")
                        continue
                    if not chunk:
                        break  # serwer zamknął — reconnect
                    buf += chunk
                    objs, buf = iter_ndjson(buf)
                    for obj in objs:
                        last = time.monotonic()
                        self.snapshot.emit(obj)
            finally:
                sock.close()
            if not self._stop.is_set():
                self.state.emit("disconnected")
