from kokpit.sources.base import RateCounter


def test_first_sample_returns_none():
    rc = RateCounter()
    assert rc.update(1000.0, 1.0) is None


def test_steady_rate():
    rc = RateCounter()
    rc.update(1000.0, 1.0)
    assert rc.update(1100.0, 1.0) == 100.0     # 100 jednostek / 1s


def test_uses_measured_dt():
    rc = RateCounter()
    rc.update(0.0, 1.0)
    assert rc.update(100.0, 2.0) == 50.0       # dzieli przez zmierzony dt


def test_counter_reset_clamped_to_zero():
    rc = RateCounter()
    rc.update(5000.0, 1.0)
    assert rc.update(10.0, 1.0) == 0.0         # delta < 0 -> clamp


def test_zero_dt_returns_none():
    rc = RateCounter()
    rc.update(1.0, 1.0)
    assert rc.update(2.0, 0.0) is None
