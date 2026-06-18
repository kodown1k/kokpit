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


def test_repeated_breach_same_axis_yields_only_one_proposal():
    """Two propose() calls during the same breach for the same axis → only ONE pending proposal."""
    pr = Proposer([POL], now_fn=lambda: 0)
    spokes = hot()
    first = pr.propose(spokes, base_for)
    second = pr.propose(spokes, base_for)
    assert len(first) == 1, "First call must create a proposal"
    assert len(second) == 0, "Second call must not create a duplicate for the same axis"
    assert len(pr.pending()) == 1, "_pending must contain exactly one proposal"


def test_after_take_new_proposal_can_be_created():
    """After take() clears the axis slot, a new proposal can be created on renewed breach."""
    pr = Proposer([POL], now_fn=lambda: 0)
    spokes = hot()
    first = pr.propose(spokes, base_for)
    assert len(first) == 1
    pr.take(first[0].id)
    # Now axis slot is free — a new breach should create a fresh proposal
    second = pr.propose(spokes, base_for)
    assert len(second) == 1, "After take(), a renewed breach must generate a new proposal"
    assert second[0].id != first[0].id, "New proposal must have a different id"
