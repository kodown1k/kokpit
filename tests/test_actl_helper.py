import pytest
from kokpit.actuator import helper


def test_rejects_unknown_verb():
    assert helper.main(["frobnicate"]) == 2


def test_governor_rejects_unknown_name(monkeypatch):
    monkeypatch.setattr(helper, "_available_governors", lambda: ["performance", "powersave"])
    assert helper.main(["governor", "rm -rf"]) == 2


def test_governor_accepts_known(monkeypatch):
    written = []
    monkeypatch.setattr(helper, "_available_governors", lambda: ["performance", "powersave"])
    monkeypatch.setattr(helper, "_governor_paths", lambda: ["/x/cpu0"])
    monkeypatch.setattr(helper, "_write", lambda path, val: written.append((path, val)))
    assert helper.main(["governor", "powersave"]) == 0
    assert written == [("/x/cpu0", "powersave")]


def test_gpu_power_clamps_and_calls_nvml(monkeypatch):
    calls = []
    monkeypatch.setattr(helper, "_nvml_set_power", lambda idx, mw: calls.append((idx, mw)))
    monkeypatch.setattr(helper, "_nvml_power_bounds_mw", lambda idx: (100_000, 350_000))
    assert helper.main(["gpu-power", "0", "50"]) == 0   # 50W -> 50000mW -> clamped up to 100000
    assert calls == [(0, 100_000)]
