# tests/test_config.py
from pathlib import Path
from kokpit import config


def test_paths_and_constants(monkeypatch):
    assert config.SAMPLE_HZ == 1.0

    # Test data_dir with XDG_DATA_HOME set
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg_data")
    assert config.data_dir() == Path("/tmp/xdg_data") / "kokpit"
    assert config.db_path().name == "kokpit.db"
    monkeypatch.delenv("XDG_DATA_HOME")

    # Test data_dir fallback
    assert config.data_dir() == Path.home() / ".local" / "share" / "kokpit"

    # Test socket_path with XDG_RUNTIME_DIR set
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/tmp/xdg_runtime")
    assert config.socket_path().name == "kokpit.sock"
    monkeypatch.delenv("XDG_RUNTIME_DIR")

    # Test socket_path fallback
    assert config.socket_path() == Path("/tmp") / "kokpit.sock"


def test_iface_disk_filters():
    assert config.IFACE_DENY.match("lo")
    assert config.IFACE_DENY.match("veth123")
    assert config.IFACE_DENY.match("docker0")
    assert config.IFACE_DENY.search("CloudflareWARP")
    assert not config.IFACE_DENY.match("enp5s0")
    assert config.DISK_DENY.match("loop0")
    assert not config.DISK_DENY.match("nvme0n1")


def test_glyph_constants_present_and_sane():
    from kokpit import config
    assert config.BASELINE_MIN_SAMPLES == 10
    assert config.FALLBACK_GLOBAL_DAYS == 7
    assert config.BASELINE_REFRESH_S == 60
    assert config.Z_FULL == 3.0
    assert 0 < config.EPS_SIGMA < 1e-6
    assert config.LIVE_EWMA_S == 45.0
