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


def test_nvml_failure_returns_exit_1(monkeypatch):
    """Translated NVML error (OSError) in a seam must yield exit 1, not a traceback."""
    monkeypatch.setattr(helper, "_nvml_power_bounds_mw", lambda idx: (_ for _ in ()).throw(OSError("boom")))
    assert helper.main(["gpu-power", "0", "200"]) == 1


def test_gpu_power_reset(monkeypatch):
    """gpu-power-reset reads default limit and calls _nvml_set_power with it."""
    calls = []
    monkeypatch.setattr(helper, "_nvml_default_power_mw", lambda idx: 250_000)
    monkeypatch.setattr(helper, "_nvml_set_power", lambda idx, mw: calls.append((idx, mw)))
    assert helper.main(["gpu-power-reset", "0"]) == 0
    assert calls == [(0, 250_000)]
