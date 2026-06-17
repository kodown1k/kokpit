import json
import logging
import os
import socket
import threading

log = logging.getLogger("kokpit.live")


class LiveServer:
    def __init__(self, sock_path) -> None:
        self.sock_path = str(sock_path)
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._srv: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        try:
            os.unlink(self.sock_path)          # usuń stale-socket
        except FileNotFoundError:
            pass
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.sock_path)
        self._srv.listen(8)
        self._srv.settimeout(0.5)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.setblocking(False)
            with self._lock:
                self._clients.append(conn)

    def publish(self, snapshot: dict) -> None:
        line = (json.dumps(snapshot) + "\n").encode()
        with self._lock:
            dead = []
            for c in self._clients:
                try:
                    sent = c.send(line)
                    if sent < len(line):
                        dead.append(c)  # częściowy zapis = uszkodzony strumień NDJSON, rozłączamy
                except BlockingIOError:
                    pass                # 0 bajtów wysłanych (bufor pełny od razu), dropujemy snapshot
                except OSError:
                    dead.append(c)
            for c in dead:
                self._clients.remove(c)
                try:
                    c.close()
                except OSError:
                    pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._srv:
            self._srv.close()
        with self._lock:
            for c in self._clients:
                try:
                    c.close()
                except OSError:
                    pass
            self._clients.clear()
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass
