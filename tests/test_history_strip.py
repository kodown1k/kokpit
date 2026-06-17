from kokpit.ui.widgets.history_strip import follow_active, window_mode, TAIL_CAP_S


def test_follow_active_near_now():
    assert follow_active(view_x_max=1000.0, last_ts_s=1001.0) is True   # w tolerancji
    assert follow_active(view_x_max=900.0, last_ts_s=1001.0) is False   # odjechał w przeszłość


def test_window_mode_split():
    assert window_mode(3600) == "raw"
    assert window_mode(3601) == "poll"
    assert window_mode(86_400) == "poll"


def test_tail_cap_is_one_hour():
    assert TAIL_CAP_S == 3600


def test_history_strip_smoke(qapp):
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.widgets.history_strip import HistoryStrip

    class FakeStore:
        def query(self, name, since_ms, until_ms):
            return [(since_ms, 1.0), (until_ms, 2.0)]
        def query_rollup(self, name, since_ms, until_ms):
            return [(since_ms, 0.0, 9.0, 4.5, 5.0)]
        def list_series(self, prefix=None):
            return []

    strip = HistoryStrip(HistoryModel(FakeStore()), ["cpu.loadavg.1"])
    strip.set_window(3600, now_ms=3_600_000)            # raw
    assert len(strip._tail["cpu.loadavg.1"]) == 2       # seeded from query (2 points)
    strip.on_snapshot({"ts": 3_600_500, "series": {"cpu.loadavg.1": 3.0}})
    # raw+follow: (3600.5, 3.0) appended; oldest (0.0, 1.0) pruned (cutoff=0.5)
    assert strip._tail["cpu.loadavg.1"][-1] == (3600.5, 3.0)   # proves append fired
    strip.set_window(86_400, now_ms=90_000_000)         # poll — on_snapshot nie dokleja
    assert len(strip._tail["cpu.loadavg.1"]) == 1       # reseeded from query_rollup (1 point)
    strip.on_snapshot({"ts": 90_000_500, "series": {"cpu.loadavg.1": 4.0}})
    # poll mode: early-return, tail must still end at rollup-seeded point (ts=3600.0, vavg=4.5)
    assert strip._tail["cpu.loadavg.1"][-1][0] == 3600.0        # unchanged; no append fired
