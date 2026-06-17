# tests/test_config.py
from kokpit import config


def test_paths_and_constants():
    assert config.SAMPLE_HZ == 1.0
    assert config.db_path().name == "kokpit.db"
    assert config.socket_path().name == "kokpit.sock"


def test_iface_disk_filters():
    assert config.IFACE_DENY.match("lo")
    assert config.IFACE_DENY.match("veth123")
    assert config.IFACE_DENY.match("docker0")
    assert config.IFACE_DENY.search("CloudflareWARP")
    assert not config.IFACE_DENY.match("enp5s0")
    assert config.DISK_DENY.match("loop0")
    assert not config.DISK_DENY.match("nvme0n1")
