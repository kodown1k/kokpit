def test_make_plots_smoke(qapp):
    from kokpit.ui.plot import make_live_plot, make_history_plot, configured_curve
    lp = make_live_plot()
    c = configured_curve(lp, color=(0, 255, 200))
    c.setData([0, 1, 2], [1, 2, 3])
    hp = make_history_plot()
    assert lp is not None and hp is not None


def test_plots_y_autorange_x_manual(qapp):
    # Regresja: make_*_plot MUSI mieć Y-autorange ON (X OFF — sterowany setXRange).
    # Stare disableAutoRange() (oba OFF) zostawiało dane (loadavg ~20, bps ~1e6, mem
    # ~1e10) poza domyślnym widokiem (0,1) -> puste wykresy historii i sparkline NET/DISK.
    from kokpit.ui.plot import make_live_plot, make_history_plot
    for mk in (make_live_plot, make_history_plot):
        _x_auto, y_auto = mk().getViewBox().state["autoRange"]
        assert y_auto is True       # Y dopasowuje się do danych (X nadpisywany ręcznie setXRange)


def test_gauge_set_value(qapp):
    from kokpit.ui.widgets.gauge import Gauge
    g = Gauge("CPU PKG", "°C")
    g.set_value(95)            # amber
    g.set_value(None)          # brak danych — bez crasha
    assert g._value_label.text() == "--"


def test_sparkline_push(qapp):
    from kokpit.ui.widgets.sparkline import Sparkline
    s = Sparkline("GPU", window_s=5, y_range=(0, 100))
    for v in [10, 20, None, 30]:
        s.push(v)
    assert len(s._ys) == 3     # None pominięte


def test_mainwindow_builds_and_updates(qapp):
    from kokpit.ui.app import MainWindow
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.live_client import LiveClient

    class FakeStore:
        def query(self, n, a, b): return [(a, 1.0), (b, 2.0)]
        def query_rollup(self, n, a, b): return [(a, 0.0, 9.0, 4.5, 5.0)]
        def list_series(self, prefix=None): return []

    live = LiveClient("/nonexistent.sock")           # nie startujemy wątku w teście
    win = MainWindow(live, HistoryModel(FakeStore()), gpu_indices=[0])
    win._on_state("connected")
    assert win._status.text() == "connected"
    win._on_snapshot({
        "ts": 1000,
        "series": {**{f"cpu.thread.{i}.util": 10 for i in range(32)},
                   "gpu.0.util": 50.0, "mem.used": 1e9, "mem.total": 8e9},
        "procs": [{"pid": 1, "name": "x", "cpu": 5.0, "rss": 1048576, "vram": 0.0}],
    })
    assert win._hero._ram._target == 12.5            # 1e9/8e9*100 → hero RAM ring
    assert win._hero._cpu._target == 10              # średnia 32 thread util @10
    win._on_snapshot({"ts": 2000, "series": {}, "procs": []})   # puste — bez crasha
    assert win._hero._cpu._value is None             # brak danych → ring „--"


def test_first_metric_key():
    from kokpit.ui.app import first_metric_key
    # Normal case — picks the .rx_bps key
    assert first_metric_key(
        ["net.enp3s0.tx_bps", "net.enp3s0.rx_bps"], ".rx_bps"
    ) == "net.enp3s0.rx_bps"
    # Empty list → None
    assert first_metric_key([], ".rx_bps") is None
    # No matching suffix → None
    assert first_metric_key(["net.enp3s0.tx_bps"], ".rx_bps") is None
    # Multiple matching — returns alphabetically first
    assert first_metric_key(
        ["net.zzz.rx_bps", "net.aaa.rx_bps"], ".rx_bps"
    ) == "net.aaa.rx_bps"


def test_mainwindow_dynamic_net_disk_keys(qapp):
    from kokpit.ui.app import MainWindow
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.live_client import LiveClient

    class FakeStore:
        def query(self, n, a, b): return [(a, 1.0), (b, 2.0)]
        def query_rollup(self, n, a, b): return [(a, 0.0, 9.0, 4.5, 5.0)]
        def list_series(self, prefix=None):
            if prefix == "net.":
                return ["net.enp3s0.rx_bps", "net.enp3s0.tx_bps"]
            if prefix == "disk.":
                return ["disk.sda.read_bps", "disk.sda.write_bps"]
            return []

    live = LiveClient("/nonexistent.sock")
    win = MainWindow(live, HistoryModel(FakeStore()), gpu_indices=[0])
    assert win._net_key == "net.enp3s0.rx_bps"
    # Snapshot with the real interface name — net sparkline should update without crash
    win._on_snapshot({
        "ts": 1000,
        "series": {"net.enp3s0.rx_bps": 1e6},
        "procs": [],
    })
    assert len(win._net._ys) == 1


def test_desktop_file_valid():
    import configparser, os
    path = os.path.join(os.path.dirname(__file__), "..", "packaging", "kokpit.desktop")
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path)
    assert cp["Desktop Entry"]["Exec"] == "kokpit"
    assert cp["Desktop Entry"]["Type"] == "Application"


def _mw(gpu_indices=(0,)):
    """Build a MainWindow against a minimal fake store (live thread not started)."""
    from kokpit.ui.app import MainWindow
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.live_client import LiveClient

    class FakeStore:
        def query(self, n, a, b): return [(a, 1.0), (b, 2.0)]
        def query_rollup(self, n, a, b): return [(a, 0.0, 9.0, 4.5, 5.0)]
        def list_series(self, prefix=None): return []

    return MainWindow(LiveClient("/nonexistent.sock"), HistoryModel(FakeStore()), list(gpu_indices))


def test_window_switcher_changes_window(qapp):
    from kokpit.ui.widgets.history_strip import window_mode
    win = _mw()
    assert win._cur_window_s == 3600              # default 1h after __init__
    assert win._win_buttons[3600].isChecked()
    win._set_window(86400)                         # 24h → rollup/poll
    assert win._cur_window_s == 86400
    assert win._win_buttons[86400].isChecked()
    assert not win._win_buttons[3600].isChecked()
    assert window_mode(win._cur_window_s) == "poll"


def test_refresh_history_polls_only_for_rollup_windows(qapp):
    win = _mw()
    calls = []
    win._hist.set_window = lambda ws, now: calls.append(ws)
    win._cur_window_s = 3600                        # raw → live tail keeps it current
    win._refresh_history()
    assert calls == []                             # no reseed for the raw window
    win._cur_window_s = 86400                       # poll → re-query DB
    win._refresh_history()
    assert calls == [86400]


def test_jump_to_now_reenables_follow(qapp):
    win = _mw()
    win._hist.set_follow(False)                     # simulate user panned into the past
    assert win._hist._follow is False
    win._jump_to_now()
    assert win._hist._follow is True


def test_primary_net_key_prefers_wired():
    from kokpit.ui.app import primary_net_key
    # wired (eth0) preferred even though a wifi iface (ath0) sorts alphabetically first
    assert primary_net_key(["net.ath0.rx_bps", "net.eth0.rx_bps"]) == "net.eth0.rx_bps"
    assert primary_net_key(["net.wlp2s0.rx_bps", "net.enp3s0.rx_bps"]) == "net.enp3s0.rx_bps"
    # no wired iface → alphabetically first
    assert primary_net_key(["net.wlan0.rx_bps", "net.ath0.rx_bps"]) == "net.ath0.rx_bps"
    # none / no rx_bps → None
    assert primary_net_key([]) is None
    assert primary_net_key(["net.eth0.tx_bps"]) is None


def test_set_window_reengages_follow_but_refresh_does_not(qapp):
    win = _mw()
    win._hist.set_follow(False)                     # user panned into the past
    win._set_window(21600)                          # explicit window switch → re-engage follow
    assert win._hist._follow is True
    # timer-driven refresh must NOT yank a panned-away view back to following
    win._hist.set_follow(False)
    win._cur_window_s = 21600                        # poll window
    win._refresh_history()
    assert win._hist._follow is False


def test_mainwindow_feeds_thread_star(qapp):
    from kokpit.ui.app import MainWindow
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.live_client import LiveClient

    class FakeStore:
        def query(self, n, a, b): return [(a, 1.0), (b, 2.0)]
        def query_rollup(self, n, a, b): return [(a, 0.0, 9.0, 4.5, 5.0)]
        def list_series(self, prefix=None): return []

    win = MainWindow(LiveClient("/nonexistent.sock"), HistoryModel(FakeStore()), gpu_indices=[0])
    win._on_snapshot({
        "ts": 1000,
        "series": {f"cpu.thread.{i}.util": 40 for i in range(16)},
        "procs": [],
    })
    assert len(win._thread_star._target) == 16
    assert all(abs(t - 0.4) < 1e-9 for t in win._thread_star._target)
