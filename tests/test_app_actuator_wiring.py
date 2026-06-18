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
