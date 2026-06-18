import pytest
from kokpit.actuator import levers as L


class FakeExec:
    def __init__(self):
        self.calls = []
    def __call__(self, argv):
        self.calls.append(argv)
        return ""


def test_renice_apply_and_revert(monkeypatch):
    fx = FakeExec()
    # capture "prior nice" deterministically
    monkeypatch.setattr(L, "_current_nice", lambda pid: 0)
    lever = L.ReniceLever(executor=fx)
    token = lever.apply({"pid": 1234}, {"value": 15})
    assert ["renice", "-n", "15", "-p", "1234"] in fx.calls
    assert token["prior_nice"] == 0
    lever.revert(token)
    assert ["renice", "-n", "0", "-p", "1234"] in fx.calls


def test_ionice_apply(monkeypatch):
    fx = FakeExec()
    lever = L.IoniceLever(executor=fx)
    lever.apply({"pid": 99}, {"value": 7})
    assert ["ionice", "-c", "2", "-n", "7", "-p", "99"] in fx.calls


def test_lever_error_on_nonzero():
    def boom(argv):
        raise L.LeverError("nope")
    lever = L.ReniceLever(executor=boom)
    with pytest.raises(L.LeverError):
        lever.apply({"pid": 1}, {"value": 1})


def test_registry_has_user_levers():
    assert {"renice", "ionice"} <= set(L.LEVERS)
    assert L.LEVERS["renice"].requires_privilege is False
