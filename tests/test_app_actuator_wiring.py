from kokpit import config
from kokpit.ui.app import MainWindow


class FakeCtl:
    def __init__(self): self.calls = []
    def request(self, verb, args):
        from kokpit.actuator import protocol as p
        self.calls.append((verb, args))
        return p.Response(ok=True, data={"token": "noop-1"})
    def poll_proposals(self): return [{"id": "prop-1", "text": "ok?"}]


def test_cap_requested_maps_to_apply(qapp, monkeypatch):
    # Build MainWindow with stubbed live/model (reuse the harness in tests/test_widgets_smoke.py)
    win = MainWindow.__new__(MainWindow)   # bypass heavy __init__ for a focused unit
    win._ctl = FakeCtl()
    MainWindow._on_cap_requested(win, "GPU temp", 0.0)
    assert win._ctl.calls[-1][0] == "apply"
    assert win._ctl.calls[-1][1]["lever"] in ("gpu_power", "governor")


def test_command_maps_to_intent(qapp):
    win = MainWindow.__new__(MainWindow)
    win._ctl = FakeCtl()
    MainWindow._on_command(win, "cicho na 10 min")
    assert win._ctl.calls[-1] == ("intent", {"text": "cicho na 10 min"})


def test_gpu_power_ceiling_config_constant_exists():
    """GPU_POWER_CEILING_W must be defined in config (replaces magic literal 300)."""
    assert hasattr(config, "GPU_POWER_CEILING_W"), "config.GPU_POWER_CEILING_W is missing"
    assert config.GPU_POWER_CEILING_W == 300


def test_cap_requested_uses_config_ceiling(qapp, monkeypatch):
    """_on_cap_requested must use config.GPU_POWER_CEILING_W, not literal 300."""
    monkeypatch.setattr(config, "GPU_POWER_CEILING_W", 250)
    monkeypatch.setattr(config, "GPU_POWER_FLOOR_W", 50)
    win = MainWindow.__new__(MainWindow)
    win._ctl = FakeCtl()
    # fraction=1.0 → watts should be floor + 1.0*(ceiling-floor) = 50 + 200 = 250
    MainWindow._on_cap_requested(win, "GPU temp", 1.0)
    call_args = win._ctl.calls[-1][1]
    assert call_args["params"]["watts"] == 250, (
        f"Expected watts=250 with ceiling=250, got {call_args['params']['watts']}"
    )
