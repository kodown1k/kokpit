from kokpit.actuator.policy import EnvelopeEvaluator, EnvelopePolicy
from kokpit.ui.glyph_model import SpokeScore

POL = EnvelopePolicy(axis="GPU temp", z_trigger=2.0,
                     action={"lever": "gpu_power", "target": {"index": 0},
                             "params": {"watts": 100}, "ttl_s": 60})


def base_for(_name):
    return (60.0, 5.0, 50, "circadian")  # mean 60, sigma 5


def hot():  return [SpokeScore("GPU temp", 0.9, 75.0, "circadian")]   # z=3
def cool(): return [SpokeScore("GPU temp", 0.1, 62.0, "circadian")]   # z<2


def test_fires_only_after_debounce():
    now = [0]
    ev = EnvelopeEvaluator([POL], debounce_s=10, now_fn=lambda: now[0])
    assert ev.evaluate(hot(), base_for) == []     # t=0 breach starts
    now[0] = 5000
    assert ev.evaluate(hot(), base_for) == []     # 5s < 10s
    now[0] = 10000
    fired = ev.evaluate(hot(), base_for)
    assert len(fired) == 1 and fired[0]["lever"] == "gpu_power"


def test_one_shot_until_clear():
    now = [0]
    ev = EnvelopeEvaluator([POL], debounce_s=0, now_fn=lambda: now[0])
    assert len(ev.evaluate(hot(), base_for)) == 1   # fires
    assert ev.evaluate(hot(), base_for) == []       # still hot -> suppressed
    assert ev.evaluate(cool(), base_for) == []      # clears
    assert len(ev.evaluate(hot(), base_for)) == 1   # re-arms, fires again
