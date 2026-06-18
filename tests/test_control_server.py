import socket

from kokpit.actuator import protocol as p
from kokpit.actuator.audit import AuditLog
from kokpit.actuator.control_server import ControlServer, build_dispatch
from kokpit.actuator.engine import Actuator
from kokpit.actuator.levers import Lever
from kokpit.actuator.proposer import Proposal, Proposer


class NoopLever(Lever):
    id = "noop"
    def apply(self, target, params): return {}
    def revert(self, token_state): pass


def _rpc(path, req: p.Request) -> p.Response:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(str(path))
    s.sendall(p.encode_request(req))
    line = s.makefile("rb").readline()
    s.close()
    return p.decode_response(line)


def test_apply_list_revert_over_socket(tmp_path):
    act = Actuator({"noop": NoopLever()}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: 0)
    srv = ControlServer(tmp_path / "ctl.sock", build_dispatch(act))
    srv.start()
    try:
        r = _rpc(tmp_path / "ctl.sock", p.Request("apply",
                 {"lever": "noop", "target": {"pid": 1}, "params": {}, "ttl_s": None}))
        assert r.ok and r.data["token"].startswith("noop-")
        tok = r.data["token"]
        r2 = _rpc(tmp_path / "ctl.sock", p.Request("list", {}))
        assert any(a["token"] == tok for a in r2.data["active"])
        r3 = _rpc(tmp_path / "ctl.sock", p.Request("revert", {"token": tok}))
        assert r3.ok
    finally:
        srv.stop()


def test_unknown_lever_returns_error(tmp_path):
    act = Actuator({}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: 0)
    srv = ControlServer(tmp_path / "ctl.sock", build_dispatch(act))
    srv.start()
    try:
        r = _rpc(tmp_path / "ctl.sock", p.Request("apply",
                 {"lever": "ghost", "target": {}, "params": {}, "ttl_s": None}))
        assert r.ok is False and r.error
    finally:
        srv.stop()


class _FakeProposer:
    def __init__(self):
        self._pool = {"prop-1": Proposal("prop-1", "ok?", {"lever": "noop", "target": {}, "params": {}, "ttl_s": None})}
    def pending(self): return list(self._pool.values())
    def take(self, pid): return self._pool.pop(pid, None)


def test_intent_quiet_applies(tmp_path):
    lv = NoopLever(); lv.id = "governor"
    act = Actuator({"governor": lv}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: 0)
    srv = ControlServer(tmp_path / "ctl.sock", build_dispatch(act, _FakeProposer()))
    srv.start()
    try:
        r = _rpc(tmp_path / "ctl.sock", p.Request("intent", {"text": "cicho na 5 min"}))
        assert r.ok and r.data["token"].startswith("governor-")
    finally:
        srv.stop()


def test_confirm_applies_proposal(tmp_path):
    lv = NoopLever()
    act = Actuator({"noop": lv}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: 0)
    srv = ControlServer(tmp_path / "ctl.sock", build_dispatch(act, _FakeProposer()))
    srv.start()
    try:
        r = _rpc(tmp_path / "ctl.sock", p.Request("confirm", {"id": "prop-1"}))
        assert r.ok and r.data["token"].startswith("noop-")
        r2 = _rpc(tmp_path / "ctl.sock", p.Request("confirm", {"id": "prop-1"}))
        assert r2.ok is False   # already taken
    finally:
        srv.stop()
