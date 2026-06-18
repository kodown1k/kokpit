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
