import json
import time

from kokpit.ui.live_client import iter_ndjson, LiveClient


def test_iter_ndjson_two_complete_lines():
    buf = b'{"a":1}\n{"b":2}\n'
    objs, rest = iter_ndjson(buf)
    assert objs == [{"a": 1}, {"b": 2}]
    assert rest == b""


def test_iter_ndjson_keeps_partial_tail():
    objs, rest = iter_ndjson(b'{"a":1}\n{"b":')
    assert objs == [{"a": 1}]
    assert rest == b'{"b":'
    # dosklejenie reszty w kolejnym czytaniu
    objs2, rest2 = iter_ndjson(rest + b'2}\n')
    assert objs2 == [{"b": 2}]
    assert rest2 == b""


def test_iter_ndjson_empty():
    assert iter_ndjson(b"") == ([], b"")


def test_live_client_emits_snapshot(qapp, tmp_path):
    from kokpit.live import LiveServer
    from PySide6 import QtCore

    sock = str(tmp_path / "k.sock")
    srv = LiveServer(sock)
    srv.start()
    received = []
    states = []
    client = LiveClient(sock)
    client.snapshot.connect(lambda d: received.append(d))
    client.state.connect(lambda s: states.append(s))
    client.start()
    try:
        deadline = time.time() + 3.0
        while time.time() < deadline and "connected" not in states:
            qapp.processEvents()
            time.sleep(0.02)
        srv.publish({"ts": 1000, "series": {"gpu.0.util": 63.0}, "procs": []})
        deadline = time.time() + 3.0
        while time.time() < deadline and not received:
            qapp.processEvents()
            time.sleep(0.02)
    finally:
        client.stop()
        srv.stop()

    assert received and received[0]["series"]["gpu.0.util"] == 63.0
    assert "connected" in states
