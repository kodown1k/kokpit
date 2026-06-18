from kokpit.actuator.audit import AuditLog
from kokpit.actuator.engine import Actuator
from kokpit import collectord
from kokpit.collectord import tick


class FakeHost:
    def collect(self, now_ms, dt_s):
        return {"cpu.thread.0.util": 12.0}


class FakeStore:
    def __init__(self):
        self.written = []
    def write(self, ts_ms, samples):
        self.written.append((ts_ms, samples))


class FakeLive:
    def __init__(self):
        self.published = []
    def publish(self, snapshot):
        self.published.append(snapshot)


class FakeProcs:
    def snapshot(self):
        return (
            [{"pid": 1, "name": "x", "cpu": 1.0, "rss": 1.0, "vram": 0.0}],
            [{"pid": 1, "name": "x", "vram": 2048.0, "gpus": [0], "type": "C",
              "sm": 50.0, "enc": 0.0, "dec": 0.0}],
        )


def test_tick_writes_and_publishes(tmp_path):
    store, live = FakeStore(), FakeLive()
    act = Actuator({}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: 0)
    tick(FakeHost(), store, live, FakeProcs(), act, now_ms=5000, dt_s=1.0)
    assert store.written == [(5000, {"cpu.thread.0.util": 12.0})]
    snap = live.published[0]
    assert snap["ts"] == 5000
    assert snap["series"] == {"cpu.thread.0.util": 12.0}
    assert snap["procs"][0]["pid"] == 1
    assert snap["gpu_procs"][0]["vram"] == 2048.0


def test_tick_runs_actuator_auto_revert(tmp_path):
    # Actuator with a spy lever that records reverts; deadline already passed.
    reverts = []
    class L:
        id = "x"
        def apply(self, t, p): return {}
        def revert(self, s): reverts.append(s)
    act = Actuator({"x": L()}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: 0)
    act.apply("x", {}, {}, ttl_s=1)   # deadline 1000ms

    class FakeHost:
        def collect(self, now_ms, dt_s): return {}
    class FakeStore:
        def write(self, *a): pass
    class FakeLive:
        def publish(self, snap): pass
    class FakeProcs:
        def snapshot(self): return [], []

    collectord.tick(FakeHost(), FakeStore(), FakeLive(), FakeProcs(), act, now_ms=2000, dt_s=1.0)
    assert len(reverts) == 1   # auto-reverted because 2000 >= 1000
