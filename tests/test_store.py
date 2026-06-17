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


def test_series_id_does_not_commit_without_write(tmp_path):
    import sqlite3
    db = tmp_path / "k.db"
    s = Store(db)
    s.series_id("orphan")                       # resolve id but never write a sample
    other = sqlite3.connect(str(db))
    seen = other.execute("SELECT COUNT(*) FROM series_dict WHERE name='orphan'").fetchone()[0]
    other.close()
    assert seen == 0                            # not durably committed -> no orphan rows on crash
    s.close()


def test_write_persists_new_series_atomically(tmp_path):
    import sqlite3
    db = tmp_path / "k.db"
    s = Store(db)
    s.write(1000, {"new.series": 5.0})
    other = sqlite3.connect(str(db))
    rows = other.execute(
        "SELECT COUNT(*) FROM series_dict d JOIN sample x ON x.series_id=d.id "
        "WHERE d.name='new.series'"
    ).fetchone()[0]
    other.close()
    assert rows == 1                            # dict + sample committed together
    s.close()


def test_rolled_back_write_does_not_poison_cache(tmp_path):
    import pytest
    s = Store(tmp_path / "k.db")
    # A write that fails mid-transaction (bad value) for a brand-new series must roll back fully
    with pytest.raises(ValueError):
        s.write(1000, {"flaky.series": "not_a_number"})
    # The cache must not retain the rolled-back series id; a later valid write must be queryable
    s.write(2000, {"flaky.series": 7.0})
    assert s.query("flaky.series", 0, 5000) == [(2000, 7.0)]
    s.close()


def test_rollup_1m_aggregates_buckets(tmp_path):
    s = Store(tmp_path / "k.db")
    # trzy próbki w tym samym 1-min buckecie (bucket 0): 60000 ms
    s.write(1000, {"gpu.0.util": 10.0})
    s.write(2000, {"gpu.0.util": 30.0})
    s.write(3000, {"gpu.0.util": 20.0})
    s.rollup_1m(now_ms=120_000)
    row = s.conn.execute(
        "SELECT bucket, vmin, vmax, vavg, vlast FROM rollup_1m r "
        "JOIN series_dict d ON d.id=r.series_id WHERE d.name='gpu.0.util'"
    ).fetchone()
    assert row[0] == 0          # bucket = floor(ts/60000)*60000
    assert row[1] == 10.0       # vmin
    assert row[2] == 30.0       # vmax
    assert row[3] == 20.0       # vavg
    assert row[4] == 20.0       # vlast (value przy max ts = 3000)
    s.close()


def test_prune_drops_old_rows(tmp_path):
    from kokpit import config
    s = Store(tmp_path / "k.db")
    old = 1000
    fresh = 10 * config.RAW_RETENTION_S * 1000
    s.write(old, {"x": 1.0})
    s.write(fresh, {"x": 2.0})
    s.prune(now_ms=fresh)
    assert s.query("x", 0, fresh + 1) == [(fresh, 2.0)]
    s.close()


def test_checkpoint_runs(tmp_path):
    s = Store(tmp_path / "k.db")
    s.write(1000, {"x": 1.0})
    s.checkpoint()  # nie rzuca
    s.close()
