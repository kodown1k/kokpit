from kokpit.actuator.audit import AuditLog
from kokpit.actuator.engine import Actuator
from kokpit.actuator.levers import Lever


class SpyLever(Lever):
    id = "spy"
    def __init__(self):
        super().__init__()
        self.applied = []
        self.reverted = []
    def apply(self, target, params):
        self.applied.append((target, params))
        return {"t": target, "p": params}
    def revert(self, token_state):
        self.reverted.append(token_state)


def make(tmp_path, now=[0]):
    spy = SpyLever()
    act = Actuator({"spy": spy}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: now[0])
    return act, spy, now


def test_apply_returns_token_and_lists(tmp_path):
    act, spy, _ = make(tmp_path)
    tok = act.apply("spy", {"pid": 1}, {"value": 5}, ttl_s=30)
    assert tok.startswith("spy-")
    assert len(spy.applied) == 1
    active = act.list_active()
    assert active[0]["token"] == tok and active[0]["deadline_ms"] == 30000


def test_explicit_revert_idempotent(tmp_path):
    act, spy, _ = make(tmp_path)
    tok = act.apply("spy", {"pid": 1}, {}, ttl_s=None)
    act.revert(tok)
    act.revert(tok)  # second is a no-op
    assert len(spy.reverted) == 1
    assert act.list_active() == []


def test_ttl_auto_revert(tmp_path):
    now = [0]
    act, spy, _ = make(tmp_path, now)
    act.apply("spy", {"pid": 1}, {}, ttl_s=10)   # deadline 10000ms
    act.tick(now_ms=5000)
    assert spy.reverted == []                    # not yet
    act.tick(now_ms=10000)
    assert len(spy.reverted) == 1                # auto-reverted
    assert act.list_active() == []


def test_revert_all(tmp_path):
    act, spy, _ = make(tmp_path)
    act.apply("spy", {"pid": 1}, {}, ttl_s=None)
    act.apply("spy", {"pid": 2}, {}, ttl_s=None)
    assert act.revert_all() == 2
    assert len(spy.reverted) == 2
