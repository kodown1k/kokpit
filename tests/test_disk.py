import types
from kokpit.sources import disk as disk_mod
from kokpit.sources.disk import DiskSource


def test_disk_rate_and_usage(monkeypatch):
    def io(perdisk):
        return {
            "loop0": types.SimpleNamespace(read_bytes=10, write_bytes=10),  # odfiltrowane
            "nvme0n1": types.SimpleNamespace(read_bytes=monkeypatch_state["r"], write_bytes=monkeypatch_state["w"]),
        }
    monkeypatch_state = {"r": 1000, "w": 2000}
    monkeypatch.setattr(disk_mod.psutil, "disk_io_counters", io)
    monkeypatch.setattr(disk_mod.psutil, "disk_partitions",
                        lambda all: [types.SimpleNamespace(mountpoint="/")])
    monkeypatch.setattr(disk_mod.psutil, "disk_usage",
                        lambda mp: types.SimpleNamespace(percent=42.0))
    src = DiskSource()
    src.sample(now_ms=0, dt_s=0.0)
    monkeypatch_state["r"], monkeypatch_state["w"] = 3000, 4000
    out = src.sample(now_ms=1000, dt_s=1.0)
    assert out["disk.nvme0n1.read_bps"] == 2000.0
    assert out["disk.nvme0n1.write_bps"] == 2000.0
    assert out["disk./.used_pct"] == 42.0
    assert "disk.loop0.read_bps" not in out
