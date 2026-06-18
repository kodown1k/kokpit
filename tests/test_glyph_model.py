import math
from kokpit import config
from kokpit.ui import glyph_model as gm


def test_z_norm_positive_deviation():
    # mean=50, sigma=10 → value_sm=80 to +3σ = pełne ramię (Z_FULL=3)
    assert gm.z_norm(80.0, (50.0, 10.0, 12, "circadian")) == 1.0
    assert abs(gm.z_norm(65.0, (50.0, 10.0, 12, "circadian")) - 0.5) < 1e-9  # +1.5σ → 0.5


def test_z_norm_negative_deviation_clamped_to_zero():
    assert gm.z_norm(20.0, (50.0, 10.0, 12, "circadian")) == 0.0   # poniżej baseline = spokój


def test_z_norm_sigma_zero_is_calm():
    assert gm.z_norm(95.0, (95.0, 0.0, 12, "circadian")) == 0.0    # seria stała → brak zaskoczenia


def test_z_norm_none_baseline_is_zero():
    assert gm.z_norm(999.0, None) == 0.0


def test_spike_score_takes_max_of_z_and_proximity():
    # σ≈0 (z=0) ale proximity 0.95 → kolec z proximity (maszyna zawsze gorąca)
    assert gm.spike_score(95.0, (95.0, 0.0, 12, "circadian"), 0.95) == 0.95
    # z duże, proximity małe → z wygrywa
    assert gm.spike_score(80.0, (50.0, 10.0, 12, "circadian"), 0.1) == 1.0
    # proximity None (oś bez limitu) → sam z
    assert gm.spike_score(65.0, (50.0, 10.0, 12, "circadian"), None) == 0.5


def test_proximity_clamped():
    assert gm.spike_score(0.0, None, 1.5) == 1.0   # proximity > 1 → 1


def test_ewma_smooths_between_prev_and_new():
    a = gm.ewma_alpha()
    assert 0.0 < a < 1.0
    assert gm.ewma(None, 10.0, a) == 10.0          # brak stanu → wartość wprost
    sm = gm.ewma(10.0, 20.0, a)
    assert 10.0 < sm < 20.0                          # między starym a nowym
    assert abs(sm - (10.0 + a * 10.0)) < 1e-9
