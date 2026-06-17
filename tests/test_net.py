import types
from kokpit.sources import net as net_mod
from kokpit.sources.net import NetSource


def _counters(rx, tx):
    return {
        "lo": types.SimpleNamespace(bytes_recv=999, bytes_sent=999),     # ma być odfiltrowane
        "enp5s0": types.SimpleNamespace(bytes_recv=rx, bytes_sent=tx),
    }


def test_net_first_tick_omits_bps_and_filters_lo(monkeypatch):
    monkeypatch.setattr(net_mod.psutil, "net_io_counters", lambda pernic: _counters(1000, 2000))
    out = NetSource().sample(now_ms=0, dt_s=0.0)
    assert out == {}                       # pierwszy tick: brak bps


def test_net_second_tick_rate(monkeypatch):
    src = NetSource()
    monkeypatch.setattr(net_mod.psutil, "net_io_counters", lambda pernic: _counters(1000, 2000))
    src.sample(now_ms=0, dt_s=0.0)
    monkeypatch.setattr(net_mod.psutil, "net_io_counters", lambda pernic: _counters(1500, 2500))
    out = src.sample(now_ms=1000, dt_s=1.0)
    assert out == {"net.enp5s0.rx_bps": 500.0, "net.enp5s0.tx_bps": 500.0}
    assert "net.lo.rx_bps" not in out
