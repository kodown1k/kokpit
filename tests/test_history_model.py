from kokpit.ui.history_model import HistoryModel, RAW_WINDOW_MAX_S


class FakeStore:
    """Duck-typed kontrakt store; zapisuje co zawołano."""
    def __init__(self):
        self.calls = []

    def query(self, name, since_ms, until_ms):
        self.calls.append(("query", name, since_ms, until_ms))
        return [(since_ms, 1.0), (until_ms, 2.0)]

    def query_rollup(self, name, since_ms, until_ms):
        self.calls.append(("query_rollup", name, since_ms, until_ms))
        return [(since_ms, 0.0, 9.0, 4.5, 5.0), (until_ms, 1.0, 8.0, 4.0, 3.0)]

    def list_series(self, prefix=None):
        self.calls.append(("list_series", prefix))
        return ["net.eth0.rx_bps", "net.eth0.tx_bps", "gpu.0.util"]


def test_window_1h_uses_raw_seconds():
    st = FakeStore()
    res = HistoryModel(st).window("cpu.loadavg.1", 3600, now_ms=3_600_000)
    assert res.is_rollup is False
    assert st.calls[0][0] == "query"
    # czas w sekundach (ms/1000)
    assert res.line[0] == (0.0, 1.0)
    assert res.line[1] == (3600.0, 2.0)
    assert res.band is None


def test_window_24h_uses_rollup_with_band():
    st = FakeStore()
    res = HistoryModel(st).window("gpu.0.util", 86_400, now_ms=86_400_000)
    assert res.is_rollup is True
    assert st.calls[0][0] == "query_rollup"
    assert res.line[0] == (0.0, 4.5)          # vavg
    assert res.band[0] == (0.0, 0.0, 9.0)     # (t, vmin, vmax)


def test_threshold_boundary_is_raw_at_max():
    st = FakeStore()
    HistoryModel(st).window("x", RAW_WINDOW_MAX_S, now_ms=10_000_000)
    assert st.calls[0][0] == "query"


def test_available_series_delegates():
    st = FakeStore()
    assert HistoryModel(st).available_series("net.") == [
        "net.eth0.rx_bps", "net.eth0.tx_bps", "gpu.0.util",
    ]
    assert st.calls[-1] == ("list_series", "net.")
