from kokpit.store import Store, SCHEMA_VERSION


def test_write_and_query_roundtrip(tmp_path):
    s = Store(tmp_path / "k.db")
    s.write(1000, {"gpu.0.util": 50.0, "cpu.thread.0.util": 10.0})
    s.write(2000, {"gpu.0.util": 70.0})
    assert s.query("gpu.0.util", 0, 5000) == [(1000, 50.0), (2000, 70.0)]
    assert s.query("cpu.thread.0.util", 0, 5000) == [(1000, 10.0)]
    s.close()


def test_user_version_set(tmp_path):
    s = Store(tmp_path / "k.db")
    v = s.conn.execute("PRAGMA user_version").fetchone()[0]
    assert v == SCHEMA_VERSION == 1
    s.close()


def test_series_id_is_stable(tmp_path):
    s = Store(tmp_path / "k.db")
    a = s.series_id("net.eth0.rx_bps")
    b = s.series_id("net.eth0.rx_bps")
    assert a == b
    s.close()
