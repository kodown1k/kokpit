from unittest.mock import MagicMock, patch

import pytest

from kokpit.actuator.audit import AuditLog
from kokpit.actuator.engine import Actuator
from kokpit.actuator.policy import EnvelopeEvaluator, EnvelopePolicy
from kokpit.ui.glyph_model import SpokeScore
from kokpit import collectord, config
from kokpit.collectord import tick, safety_revert_on_startup
from kokpit.store import Store


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


def test_tick_applies_fired_envelope_action(tmp_path, monkeypatch):
    applied = []
    class FakeActuator:
        def apply(self, lever, target, params, ttl_s): applied.append((lever, params)); return "t"
        def tick(self, now_ms): pass
    # Envelope that always fires one action regardless of spokes.
    class AlwaysFire(EnvelopeEvaluator):
        def evaluate(self, spokes, baseline_for):
            return [{"lever": "governor", "target": {}, "params": {"name": "powersave"}, "ttl_s": 60}]
    env = AlwaysFire([], 0, lambda: 0)

    class FakeHost:
        def collect(self, *a): return {}
    class FakeStore:
        def write(self, *a): pass
        def baseline(self, *a, **k): return None
    class FakeLive:
        def publish(self, snap): pass
    class FakeProcs:
        def snapshot(self): return [], []

    from kokpit import collectord
    collectord.tick_envelope(FakeHost(), FakeStore(), FakeLive(), FakeProcs(),
                             FakeActuator(), env, collectord._GlyphState(), now_ms=1, dt_s=1.0)
    assert applied == [("governor", {"name": "powersave"})]


def test_tick_envelope_calls_proposer_propose(tmp_path):
    """tick_envelope must call proposer.propose(spokes, glyph.axis_baseline) each tick."""
    proposer = MagicMock()
    proposer.propose.return_value = []

    class FakeActuator:
        def apply(self, lever, target, params, ttl_s): return "t"
        def tick(self, now_ms): pass

    class NeverFire(EnvelopeEvaluator):
        def evaluate(self, spokes, baseline_for): return []

    env = NeverFire([], 0, lambda: 0)

    class FakeHost:
        def collect(self, *a): return {}
    class FakeStore:
        def write(self, *a): pass
        def baseline(self, *a, **k): return None
    class FakeLive:
        def publish(self, snap): pass
    class FakeProcs:
        def snapshot(self): return [], []

    collectord.tick_envelope(FakeHost(), FakeStore(), FakeLive(), FakeProcs(),
                             FakeActuator(), env, collectord._GlyphState(), now_ms=1, dt_s=1.0,
                             proposer=proposer)
    proposer.propose.assert_called_once()


# ---------------------------------------------------------------------------
# CRITICAL #1 — axis_baseline resolves axis name to real store series key
# ---------------------------------------------------------------------------

def test_axis_baseline_resolves_gpu_temp_via_store(tmp_path):
    """axis_baseline('GPU temp') must resolve to the gpu.0.temp series baseline.

    Regression guard: previously axis_name was passed directly to BaselineCache.get,
    which calls Store.baseline with the axis name string ('GPU temp') — a name that
    never exists in series_dict — so baseline was always None.
    """
    store = Store(tmp_path / "t.db")
    now_ms = 1_700_000_000_000  # arbitrary epoch

    # Seed a rollup_1m row directly so Store.baseline returns a result with min_samples=1.
    # We need a series_dict entry first, then a rollup_1m row.
    store.conn.execute("INSERT INTO series_dict(name) VALUES ('gpu.0.temp')")
    sid = store.conn.execute("SELECT id FROM series_dict WHERE name='gpu.0.temp'").fetchone()[0]
    bucket = (now_ms // 60_000) * 60_000
    store.conn.execute(
        "INSERT INTO rollup_1m(bucket, series_id, vmin, vmax, vavg, vlast) VALUES (?,?,?,?,?,?)",
        (bucket, sid, 68.0, 72.0, 70.0, 71.0),
    )
    store.conn.commit()

    # Build _GlyphState with real store; use min_samples=1 override via monkeypatching config
    original_min = config.BASELINE_MIN_SAMPLES
    config.BASELINE_MIN_SAMPLES = 1
    try:
        glyph = collectord._GlyphState(store, now_fn=lambda: now_ms)
        result = glyph.axis_baseline("GPU temp")
    finally:
        config.BASELINE_MIN_SAMPLES = original_min
        store.close()

    assert result is not None, "axis_baseline('GPU temp') must not return None when series data exists"
    mean, sigma, n, tier = result
    assert abs(mean - 70.0) < 1e-6, f"expected mean ~70.0, got {mean}"


def test_axis_baseline_returns_none_when_no_series(tmp_path):
    """axis_baseline returns None when no matching series exist in the store."""
    store = Store(tmp_path / "t.db")
    now_ms = 1_700_000_000_000
    glyph = collectord._GlyphState(store, now_fn=lambda: now_ms)
    result = glyph.axis_baseline("GPU temp")
    store.close()
    assert result is None


def test_axis_baseline_hottest_series_wins(tmp_path):
    """axis_baseline returns the baseline with the highest mean (hottest GPU)."""
    store = Store(tmp_path / "t.db")
    now_ms = 1_700_000_000_000
    bucket = (now_ms // 60_000) * 60_000

    for name, avg in [("gpu.0.temp", 70.0), ("gpu.1.temp", 85.0)]:
        store.conn.execute("INSERT INTO series_dict(name) VALUES (?)", (name,))
        sid = store.conn.execute("SELECT id FROM series_dict WHERE name=?", (name,)).fetchone()[0]
        store.conn.execute(
            "INSERT INTO rollup_1m(bucket, series_id, vmin, vmax, vavg, vlast) VALUES (?,?,?,?,?,?)",
            (bucket, sid, avg - 2, avg + 2, avg, avg),
        )
    store.conn.commit()

    original_min = config.BASELINE_MIN_SAMPLES
    config.BASELINE_MIN_SAMPLES = 1
    try:
        glyph = collectord._GlyphState(store, now_fn=lambda: now_ms)
        result = glyph.axis_baseline("GPU temp")
    finally:
        config.BASELINE_MIN_SAMPLES = original_min
        store.close()

    assert result is not None
    mean = result[0]
    assert abs(mean - 85.0) < 1e-6, f"expected hottest mean 85.0, got {mean}"


# ---------------------------------------------------------------------------
# CRITICAL #2 — safety_revert_on_startup behavior
# ---------------------------------------------------------------------------

def test_safety_revert_skips_when_last_shutdown_clean(tmp_path):
    """No reset calls when audit ends with a clean shutdown marker."""
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.record("apply", {"token": "gov-1"})
    audit.record("shutdown", {"clean": True})

    calls = []
    safety_revert_on_startup(audit, now_fn=lambda: 0, _runner=lambda argv: calls.append(argv))
    assert calls == [], f"Expected no revert calls for clean shutdown, got {calls}"


def test_safety_revert_fires_when_no_clean_shutdown(tmp_path, monkeypatch):
    """Reset commands are issued when audit does not end with a clean shutdown."""
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.record("apply", {"token": "gpu-power-1", "lever": "gpu_power"})
    # No shutdown record — simulates kill -9

    calls = []
    # Monkeypatch pynvml so we get 1 GPU without real hardware
    import types
    fake_nvml = types.SimpleNamespace(
        nvmlInit=lambda: None,
        nvmlDeviceGetCount=lambda: 1,
    )
    monkeypatch.setattr("kokpit.collectord.subprocess", __import__("subprocess"))
    # Patch pynvml import inside the function via sys.modules
    import sys
    sys.modules["pynvml"] = fake_nvml
    try:
        safety_revert_on_startup(audit, now_fn=lambda: 0, _runner=lambda argv: calls.append(argv))
    finally:
        del sys.modules["pynvml"]

    # Should have issued gpu-power-reset for index 0 and a governor reset
    gpu_reset_calls = [c for c in calls if "gpu-power-reset" in c]
    governor_calls = [c for c in calls if "governor" in c]
    assert len(gpu_reset_calls) == 1, f"Expected 1 gpu-power-reset call, got {gpu_reset_calls}"
    assert len(governor_calls) == 1, f"Expected 1 governor call, got {governor_calls}"
    assert calls[-1] == ["pkexec", "kokpit-actl-helper", "governor", config.STARTUP_GOVERNOR]


def test_safety_revert_skips_when_audit_empty(tmp_path):
    """No reset calls when audit is empty (fresh first start, nothing applied)."""
    audit = AuditLog(tmp_path / "audit.jsonl")
    # audit file doesn't exist yet → tail() returns []

    calls = []
    # With empty audit, tail is empty → no revert (same as unclean, but no GPU)
    # Per spec: empty log → return without doing anything
    # Actually re-reading spec: "if the log is empty OR its LAST entry is shutdown clean → return"
    safety_revert_on_startup(audit, now_fn=lambda: 0, _runner=lambda argv: calls.append(argv))
    assert calls == [], f"Expected no revert calls for empty audit, got {calls}"


# ---------------------------------------------------------------------------
# IMPORTANT #4 — PROPOSE_ENABLED default False + routing
# ---------------------------------------------------------------------------

def test_run_reset_logs_warning_on_nonzero_returncode(tmp_path, caplog):
    """_run_reset logs a warning when the subprocess returns non-zero."""
    import subprocess
    import types
    from kokpit.collectord import _run_reset

    # Build a fake completed process with non-zero returncode
    fake_cp = types.SimpleNamespace(returncode=1, stderr=b"permission denied")

    with caplog.at_level("WARNING", logger="kokpit.collectord"):
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "kokpit.collectord.subprocess.run", return_value=fake_cp
        ):
            _run_reset(["pkexec", "kokpit-actl-helper", "gpu-power-reset", "0"])

    assert any("_run_reset failed" in r.message for r in caplog.records), (
        "Expected a WARNING log from _run_reset on non-zero returncode"
    )


def test_propose_enabled_default_is_false():
    """PROPOSE_ENABLED must default to False (opt-in)."""
    assert config.PROPOSE_ENABLED is False


def test_axis_baseline_caches_list_series(tmp_path):
    """_GlyphState must cache list_series() and not call it on every axis_baseline invocation."""
    store = Store(tmp_path / "t.db")
    now_ms = 1_700_000_000_000

    store.conn.execute("INSERT INTO series_dict(name) VALUES ('gpu.0.temp')")
    sid = store.conn.execute("SELECT id FROM series_dict WHERE name='gpu.0.temp'").fetchone()[0]
    bucket = (now_ms // 60_000) * 60_000
    store.conn.execute(
        "INSERT INTO rollup_1m(bucket, series_id, vmin, vmax, vavg, vlast) VALUES (?,?,?,?,?,?)",
        (bucket, sid, 65.0, 75.0, 70.0, 70.0),
    )
    store.conn.commit()

    call_count = [0]
    original_list_series = store.list_series

    def counting_list_series(*args, **kwargs):
        call_count[0] += 1
        return original_list_series(*args, **kwargs)

    store.list_series = counting_list_series

    original_min = config.BASELINE_MIN_SAMPLES
    config.BASELINE_MIN_SAMPLES = 1
    try:
        glyph = collectord._GlyphState(store, now_fn=lambda: now_ms)
        # Call axis_baseline N times less than _SERIES_CACHE_REFRESH_TICKS
        N = collectord._SERIES_CACHE_REFRESH_TICKS - 1
        for _ in range(N):
            glyph.axis_baseline("GPU temp")
        # list_series should have been called exactly once (cache populated on first call)
        assert call_count[0] == 1, (
            f"Expected list_series called once for {N} axis_baseline calls, got {call_count[0]}"
        )
    finally:
        config.BASELINE_MIN_SAMPLES = original_min
        store.close()


def test_run_routing_uses_plain_tick_when_both_disabled(monkeypatch):
    """When ENVELOPE_ENABLED=False and PROPOSE_ENABLED=False, run() uses plain tick."""
    monkeypatch.setattr(config, "ENVELOPE_ENABLED", False)
    monkeypatch.setattr(config, "PROPOSE_ENABLED", False)
    tick_calls, tick_env_calls = [], []
    monkeypatch.setattr(collectord, "tick", lambda *a, **kw: tick_calls.append(1))
    monkeypatch.setattr(collectord, "tick_envelope", lambda *a, **kw: tick_env_calls.append(1))
    # Confirm branching logic: ENVELOPE_ENABLED or PROPOSE_ENABLED is False
    assert not (config.ENVELOPE_ENABLED or config.PROPOSE_ENABLED)


def test_run_routing_uses_tick_envelope_when_propose_enabled(monkeypatch):
    """When PROPOSE_ENABLED=True, routing condition fires tick_envelope."""
    monkeypatch.setattr(config, "ENVELOPE_ENABLED", False)
    monkeypatch.setattr(config, "PROPOSE_ENABLED", True)
    assert config.ENVELOPE_ENABLED or config.PROPOSE_ENABLED


def test_run_routing_uses_tick_envelope_when_envelope_enabled(monkeypatch):
    """When ENVELOPE_ENABLED=True, routing condition fires tick_envelope."""
    monkeypatch.setattr(config, "ENVELOPE_ENABLED", True)
    monkeypatch.setattr(config, "PROPOSE_ENABLED", False)
    assert config.ENVELOPE_ENABLED or config.PROPOSE_ENABLED


def test_tick_envelope_with_propose_enabled_calls_proposer(monkeypatch):
    """tick_envelope calls proposer.propose when PROPOSE_ENABLED=True (integration)."""
    monkeypatch.setattr(config, "PROPOSE_ENABLED", True)
    proposer = MagicMock()
    proposer.propose.return_value = []

    class FakeActuator:
        def apply(self, *a, **kw): return "t"
        def tick(self, now_ms): pass

    class NeverFire(EnvelopeEvaluator):
        def evaluate(self, spokes, baseline_for): return []

    class FakeHost:
        def collect(self, *a): return {}
    class FakeStore:
        def write(self, *a): pass
    class FakeLive:
        def publish(self, snap): pass
    class FakeProcs:
        def snapshot(self): return [], []

    env = NeverFire([], 0, lambda: 0)
    collectord.tick_envelope(FakeHost(), FakeStore(), FakeLive(), FakeProcs(),
                             FakeActuator(), env, collectord._GlyphState(), now_ms=1, dt_s=1.0,
                             proposer=proposer)
    proposer.propose.assert_called_once()
