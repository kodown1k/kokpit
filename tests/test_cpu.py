import types
from kokpit.sources import cpu as cpu_mod
from kokpit.sources.cpu import CpuSource


def test_cpu_sample_keys(monkeypatch):
    monkeypatch.setattr(cpu_mod.psutil, "cpu_percent", lambda percpu: [10.0, 20.0])
    monkeypatch.setattr(
        cpu_mod.psutil, "cpu_freq",
        lambda percpu: [types.SimpleNamespace(current=3000.0), types.SimpleNamespace(current=3100.0)],
    )
    monkeypatch.setattr(cpu_mod.psutil, "getloadavg", lambda: (1.5, 1.0, 0.5))
    out = CpuSource().sample(now_ms=0, dt_s=1.0)
    assert out["cpu.thread.0.util"] == 10.0
    assert out["cpu.thread.1.util"] == 20.0
    assert out["cpu.thread.0.freq"] == 3000.0
    assert out["cpu.loadavg.1"] == 1.5


def test_cpu_freq_none(monkeypatch):
    monkeypatch.setattr(cpu_mod.psutil, "cpu_percent", lambda percpu: [10.0])
    monkeypatch.setattr(cpu_mod.psutil, "cpu_freq", lambda percpu: None)
    monkeypatch.setattr(cpu_mod.psutil, "getloadavg", lambda: (1.5, 1.0, 0.5))
    out = CpuSource().sample(now_ms=0, dt_s=1.0)
    assert out["cpu.thread.0.util"] == 10.0
    assert not any(k.endswith(".freq") for k in out)
    assert out["cpu.loadavg.1"] == 1.5


def test_cpu_loadavg_unavailable(monkeypatch):
    def _raise():
        raise OSError("loadavg not supported")

    monkeypatch.setattr(cpu_mod.psutil, "cpu_percent", lambda percpu: [10.0])
    monkeypatch.setattr(cpu_mod.psutil, "cpu_freq", lambda percpu: [])
    monkeypatch.setattr(cpu_mod.psutil, "getloadavg", _raise)
    out = CpuSource().sample(now_ms=0, dt_s=1.0)
    assert out == {"cpu.thread.0.util": 10.0}
