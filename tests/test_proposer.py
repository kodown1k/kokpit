from kokpit.actuator.policy import EnvelopePolicy
from kokpit.actuator.proposer import Proposer
from kokpit.ui.glyph_model import SpokeScore

POL = EnvelopePolicy(axis="GPU temp", z_trigger=2.0,
                     action={"lever": "gpu_power", "target": {"index": 0},
                             "params": {"watts": 100}, "ttl_s": 60})


def base_for(_): return (60.0, 5.0, 50, "circadian")
def hot(): return [SpokeScore("GPU temp", 0.9, 75.0, "circadian")]


def test_proposes_on_breach_with_text_and_action():
    pr = Proposer([POL], now_fn=lambda: 0)
    props = pr.propose(hot(), base_for)
    assert len(props) == 1
    assert "GPU" in props[0].text
    assert props[0].action["lever"] == "gpu_power"


def test_take_pops_pending():
    pr = Proposer([POL], now_fn=lambda: 0)
    p = pr.propose(hot(), base_for)[0]
    assert pr.take(p.id) is not None
    assert pr.take(p.id) is None      # already taken
