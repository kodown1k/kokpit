from kokpit.actuator import levers as L


class FakeExec:
    def __init__(self): self.calls = []
    def __call__(self, argv):
        self.calls.append(argv)
        return "performance\n"


def test_gpu_power_lever_uses_pkexec_helper():
    fx = FakeExec()
    lever = L.GpuPowerLever(executor=fx)
    tok = lever.apply({"index": 0}, {"watts": 200})
    assert fx.calls[-1] == ["pkexec", "kokpit-actl-helper", "gpu-power", "0", "200"]
    lever.revert(tok)
    assert fx.calls[-1] == ["pkexec", "kokpit-actl-helper", "gpu-power-reset", "0"]


def test_governor_lever_captures_and_restores(monkeypatch):
    fx = FakeExec()
    monkeypatch.setattr(L, "_current_governor", lambda: "performance")
    lever = L.GovernorLever(executor=fx)
    tok = lever.apply({}, {"name": "powersave"})
    assert ["pkexec", "kokpit-actl-helper", "governor", "powersave"] in fx.calls
    assert tok["prior"] == "performance"
    lever.revert(tok)
    assert fx.calls[-1] == ["pkexec", "kokpit-actl-helper", "governor", "performance"]


def test_priv_levers_registered():
    assert L.LEVERS["gpu_power"].requires_privilege is True
    assert L.LEVERS["governor"].requires_privilege is True
