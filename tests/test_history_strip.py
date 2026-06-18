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


def test_last_ts_s_updated_by_set_window_and_snapshot(qapp):
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.widgets.history_strip import HistoryStrip

    class FakeStore:
        def query(self, name, since_ms, until_ms):
            return []
        def query_rollup(self, name, since_ms, until_ms):
            return []
        def list_series(self, prefix=None):
            return []

    strip = HistoryStrip(HistoryModel(FakeStore()), ["cpu.loadavg.1"])
    strip.set_window(3600, now_ms=5_000_000)
    assert strip._last_ts_s == 5000.0
    strip.on_snapshot({"ts": 5_001_000, "series": {"cpu.loadavg.1": 1.0}})
    assert strip._last_ts_s == 5001.0


def test_on_user_pan_disables_and_reenables_follow(qapp):
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.widgets.history_strip import HistoryStrip, follow_active

    class FakeStore:
        def query(self, name, since_ms, until_ms):
            return []
        def query_rollup(self, name, since_ms, until_ms):
            return []
        def list_series(self, prefix=None):
            return []

    strip = HistoryStrip(HistoryModel(FakeStore()), ["cpu.loadavg.1"])
    strip._last_ts_s = 1000.0
    # Pan far into the past — follow should become False
    assert not follow_active(500.0, strip._last_ts_s)
    strip._follow = follow_active(500.0, strip._last_ts_s)
    assert strip._follow is False
    # Pan back to near-now — follow should become True
    assert follow_active(999.5, strip._last_ts_s)
    strip._follow = follow_active(999.5, strip._last_ts_s)
    assert strip._follow is True


def test_x_link_set_on_secondary_plots(qapp):
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.widgets.history_strip import HistoryStrip

    class FakeStore:
        def query(self, name, since_ms, until_ms):
            return []
        def query_rollup(self, name, since_ms, until_ms):
            return []
        def list_series(self, prefix=None):
            return []

    series = ["cpu.loadavg.1", "gpu.0.util", "mem.used"]
    strip = HistoryStrip(HistoryModel(FakeStore()), series)
    first_plot = strip._plots[series[0]]
    for s in series[1:]:
        linked = strip._plots[s].getViewBox().linkedView(0)
        assert linked is first_plot.getViewBox(), f"Plot for {s} not X-linked to first plot"


class _XRangeFakeStore:
    def query(self, n, a, b): return [(a, 1.0), (b, 2.0)]
    def query_rollup(self, n, a, b): return [(a, 0.0, 9.0, 4.5, 5.0)]
    def list_series(self, prefix=None): return []


def test_set_window_frames_x_range(qapp):
    import pytest
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.widgets.history_strip import HistoryStrip

    strip = HistoryStrip(HistoryModel(_XRangeFakeStore()), ["cpu.loadavg.1"])
    strip.set_window(3600, now_ms=10_000_000)        # now_s = 10000.0
    lo, hi = strip._master_vb.viewRange()[0]
    assert hi == pytest.approx(10000.0, abs=1.0)      # right edge at "now"
    assert (hi - lo) == pytest.approx(3600, abs=2.0)  # span = window


def test_follow_advances_x_range(qapp):
    import pytest
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.widgets.history_strip import HistoryStrip

    strip = HistoryStrip(HistoryModel(_XRangeFakeStore()), ["cpu.loadavg.1"])
    strip.set_window(3600, now_ms=10_000_000)
    strip.on_snapshot({"ts": 10_000_500, "series": {"cpu.loadavg.1": 3.0}})  # t_s = 10000.5
    lo, hi = strip._master_vb.viewRange()[0]
    assert hi == pytest.approx(10000.5, abs=1.0)      # view slid so "now" stays at right edge
    assert (hi - lo) == pytest.approx(3600, abs=2.0)


def test_set_window_y_fits_data(qapp):
    # Regresja: po set_window oś Y musi objąć dane (np. loadavg ~15..28), nie
    # domyślne (0,1). disableAutoRange() wyłączał Y -> dane nad widokiem -> pusto.
    import pytest
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.widgets.history_strip import HistoryStrip

    now_ms = 1_700_000_000_000

    class FakeStore:
        def query(self, name, since_ms, until_ms):
            return [(now_ms - 2000, 15.0), (now_ms - 1000, 20.0), (now_ms, 28.0)]
        def query_rollup(self, name, since_ms, until_ms):
            return []
        def list_series(self, prefix=None):
            return []

    strip = HistoryStrip(HistoryModel(FakeStore()), ["cpu.loadavg.1"])
    strip.set_window(3600, now_ms)
    qapp.processEvents()
    ymin, ymax = strip._plots["cpu.loadavg.1"].getViewBox().viewRange()[1]
    assert ymax >= 28 - 1      # góra danych (~28) widoczna
    assert ymin <= 15 + 1      # dół (~15) widoczny


def test_panned_away_accumulates_tail_without_sliding(qapp):
    import pytest
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.widgets.history_strip import HistoryStrip

    strip = HistoryStrip(HistoryModel(_XRangeFakeStore()), ["cpu.loadavg.1"])
    strip.set_window(3600, now_ms=10_000_000)         # view framed at [6400, 10000]
    strip.set_follow(False)                            # user panned into the past
    strip.on_snapshot({"ts": 10_000_500, "series": {"cpu.loadavg.1": 3.0}})
    # data still accumulates (no gap on return) ...
    assert strip._tail["cpu.loadavg.1"][-1] == (10000.5, 3.0)
    # ... but the view did NOT slide (right edge stays at the framed 'now', not 10000.5)
    _lo, hi = strip._master_vb.viewRange()[0]
    assert hi == pytest.approx(10000.0, abs=1.0)


def test_history_strip_scales_and_labels(qapp):
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.widgets.history_strip import HistoryStrip

    class FakeStore:
        def query(self, n, a, b): return [(a, 4e9), (b, 8e9)]
        def query_rollup(self, n, a, b): return []
        def list_series(self, prefix=None): return []

    strip = HistoryStrip(HistoryModel(FakeStore()), ["mem.used"],
                         formats={"mem.used": ("MEM used (GB)", 1e-9)})
    strip.set_window(3600, now_ms=3_600_000)
    assert strip._tail["mem.used"][0][1] == 4.0          # 4e9 B → 4.0 GB
    strip.on_snapshot({"ts": 3_600_500, "series": {"mem.used": 6e9}})
    assert strip._tail["mem.used"][-1][1] == 6.0          # skala zastosowana też w live
    assert "GB" in strip._labels["mem.used"].text()       # czytelna etykieta jednostki
