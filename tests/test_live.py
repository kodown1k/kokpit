import json
import socket
import time
from kokpit.live import LiveServer


def test_publish_broadcasts_ndjson(tmp_path):
    sock_path = str(tmp_path / "k.sock")
    srv = LiveServer(sock_path)
    srv.start()
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(sock_path)
        time.sleep(0.6)                       # niech accept-loop zarejestruje klienta
        srv.publish({"ts": 1000, "series": {"gpu.0.util": 63.0}, "procs": []})
        client.settimeout(2.0)
        line = client.makefile().readline()
        msg = json.loads(line)
        assert msg["ts"] == 1000
        assert msg["series"]["gpu.0.util"] == 63.0
    finally:
        srv.stop()


def test_start_removes_stale_socket(tmp_path):
    sock_path = tmp_path / "k.sock"
    sock_path.write_text("stale")             # plik istnieje przed startem
    srv = LiveServer(str(sock_path))
    srv.start()                                # nie rzuca EADDRINUSE
    srv.stop()
