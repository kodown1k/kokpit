from kokpit.actuator import protocol as p
from kokpit.actuator.audit import AuditLog
from kokpit.actuator.control_server import ControlServer, build_dispatch
from kokpit.actuator.engine import Actuator
from kokpit.actuator.levers import Lever
from kokpit.ui.ctl_client import ControlClient


class NoopLever(Lever):
    id = "noop"
    def apply(self, t, params): return {}
    def revert(self, s): pass


def test_request_roundtrip_via_real_server(tmp_path, qtbot=None):
    act = Actuator({"noop": NoopLever()}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: 0)
    srv = ControlServer(tmp_path / "ctl.sock", build_dispatch(act))
    srv.start()
    try:
        c = ControlClient(str(tmp_path / "ctl.sock"))
        resp = c.request("apply", {"lever": "noop", "target": {}, "params": {}, "ttl_s": None})
        assert resp.ok and resp.data["token"].startswith("noop-")
    finally:
        srv.stop()


def test_request_on_dead_socket_returns_error(tmp_path):
    c = ControlClient(str(tmp_path / "nope.sock"))
    resp = c.request("list", {})
    assert resp.ok is False and resp.error


def test_request_returns_error_on_garbage_response(tmp_path):
    """ControlClient.request must return ok=False (not raise) when server replies garbage."""
    import socket
    import threading

    sock_path = str(tmp_path / "garbage.sock")
    ready = threading.Event()

    def bad_server():
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)
        ready.set()
        conn, _ = srv.accept()
        conn.sendall(b"this is not json at all\n")
        conn.close()
        srv.close()

    t = threading.Thread(target=bad_server, daemon=True)
    t.start()
    ready.wait(timeout=2.0)

    c = ControlClient(sock_path)
    resp = c.request("list", {})
    t.join(timeout=2.0)

    assert resp.ok is False, "Expected ok=False for garbage response"
    assert resp.error is not None, "Expected error message for garbage response"


def test_request_returns_error_on_empty_response(tmp_path):
    """ControlClient.request must return ok=False (not raise) when server replies empty line."""
    import socket
    import threading

    sock_path = str(tmp_path / "empty.sock")
    ready = threading.Event()

    def empty_server():
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)
        ready.set()
        conn, _ = srv.accept()
        conn.sendall(b"\n")   # empty line
        conn.close()
        srv.close()

    t = threading.Thread(target=empty_server, daemon=True)
    t.start()
    ready.wait(timeout=2.0)

    c = ControlClient(sock_path)
    resp = c.request("list", {})
    t.join(timeout=2.0)

    assert resp.ok is False, "Expected ok=False for empty response"
