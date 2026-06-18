from kokpit.actuator.policy import EnvelopePolicy, breach
from kokpit.ui.glyph_model import SpokeScore


def _spoke(value):
    return SpokeScore(name="GPU temp", score=0.9, value=value, tier="circadian")


def test_breach_true_above_trigger():
    pol = EnvelopePolicy(axis="GPU temp", z_trigger=2.0, action={})
    # baseline mean=60, sigma=5 -> value 75 = z=3.0 >= 2.0
    assert breach(pol, _spoke(75.0), baseline=(60.0, 5.0, 50, "circadian")) is True


def test_no_breach_below_trigger():
    pol = EnvelopePolicy(axis="GPU temp", z_trigger=2.0, action={})
    assert breach(pol, _spoke(65.0), baseline=(60.0, 5.0, 50, "circadian")) is False


def test_no_baseline_no_breach():
    pol = EnvelopePolicy(axis="GPU temp", z_trigger=2.0, action={})
    assert breach(pol, _spoke(99.0), baseline=None) is False


def test_zero_sigma_no_breach():
    pol = EnvelopePolicy(axis="GPU temp", z_trigger=2.0, action={})
    assert breach(pol, _spoke(99.0), baseline=(60.0, 0.0, 50, "circadian")) is False
