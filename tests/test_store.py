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
    assert v == SCHEMA_VERSION
    assert SCHEMA_VERSION == 2
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


def test_query_rollup_returns_sorted_buckets_with_aggregates(tmp_path):
    s = Store(tmp_path / "k.db")
    # bucket 0 (ts 1000..3000) i bucket 60000 (ts 61000..62000)
    s.write(1000, {"gpu.0.util": 10.0})
    s.write(2000, {"gpu.0.util": 30.0})
    s.write(3000, {"gpu.0.util": 20.0})   # vlast bucketu 0 (max ts) = 20, != vmax=30
    s.write(61000, {"gpu.0.util": 40.0})
    s.write(62000, {"gpu.0.util": 50.0})  # vlast bucketu 60000 = 50
    s.rollup_1m(now_ms=120_000)
    out = s.query_rollup("gpu.0.util", 0, 60000)
    assert out == [
        (0,     10.0, 30.0, 20.0, 20.0),   # (bucket, vmin, vmax, vavg, vlast)
        (60000, 40.0, 50.0, 45.0, 50.0),
    ]
    s.close()


def test_query_rollup_empty_range_returns_empty(tmp_path):
    s = Store(tmp_path / "k.db")
    s.write(1000, {"gpu.0.util": 10.0})
    s.rollup_1m(now_ms=120_000)
    assert s.query_rollup("gpu.0.util", 1, 59_999) == []   # bucket 0 poza zakresem
    s.close()


def test_query_rollup_filters_by_series(tmp_path):
    s = Store(tmp_path / "k.db")
    s.write(1000, {"gpu.0.util": 10.0, "cpu.thread.0.util": 5.0})
    s.rollup_1m(now_ms=120_000)
    assert s.query_rollup("cpu.thread.0.util", 0, 60000) == [(0, 5.0, 5.0, 5.0, 5.0)]
    s.close()


def test_list_series_returns_all_sorted(tmp_path):
    s = Store(tmp_path / "k.db")
    s.write(1000, {
        "net.eth0.rx_bps": 1.0,
        "net.eth0.tx_bps": 2.0,
        "cpu.thread.0.util": 3.0,
        "gpu.0.util": 4.0,
    })
    assert s.list_series() == [
        "cpu.thread.0.util",
        "gpu.0.util",
        "net.eth0.rx_bps",
        "net.eth0.tx_bps",
    ]
    s.close()


def test_list_series_prefix_filters(tmp_path):
    s = Store(tmp_path / "k.db")
    s.write(1000, {
        "net.eth0.rx_bps": 1.0,
        "net.eth0.tx_bps": 2.0,
        "network.bogus": 9.0,   # NIE pasuje do 'net.' (kropka literalna w LIKE)
        "gpu.0.util": 4.0,
    })
    assert s.list_series("net.") == ["net.eth0.rx_bps", "net.eth0.tx_bps"]
    s.close()


def test_list_series_empty_db_returns_empty(tmp_path):
    s = Store(tmp_path / "k.db")
    assert s.list_series() == []
    s.close()


def test_list_series_prefix_escapes_like_wildcards(tmp_path):
    # `_` i `%` to wildcardy LIKE — w prefiksie muszą być literalne, inaczej
    # 'net.rx_' przematchowałby też 'net.rxXbps' (ARP finding like-wildcard-escape).
    s = Store(tmp_path / "k.db")
    s.write(1000, {
        "net.rx_bps": 1.0,   # literalny underscore
        "net.rxXbps": 2.0,   # NIE powinno pasować do prefiksu 'net.rx_'
        "100pct": 3.0,
        "1X0pct": 4.0,       # NIE powinno pasować do prefiksu '100%'... znaczy '100' z literalnym %
    })
    assert s.list_series("net.rx_") == ["net.rx_bps"]
    assert s.list_series("100%") == []          # '%' literalny: brak serii zaczynającej się od '100%'
    s.close()


def _seed_rollup(s, name, points):
    """points: list[(bucket_ms, vavg)] — wstrzykuje wprost do rollup_1m.
    Testujemy agregację baseline(), nie rollup_1m()."""
    s.write(points[0][0], {name: points[0][1]})          # utwórz serię + commit
    sid = s.conn.execute("SELECT id FROM series_dict WHERE name=?", (name,)).fetchone()[0]
    s.conn.executemany(
        "INSERT OR REPLACE INTO rollup_1m(bucket, series_id, vmin, vmax, vavg, vlast) "
        "VALUES (?,?,?,?,?,?)",
        [(b, sid, v, v, v, v) for b, v in points],
    )
    s.conn.commit()


import os
import time

import pytest


@pytest.fixture()
def use_utc():
    prior = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    yield
    if prior is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = prior
    time.tzset()


DAY = 86_400_000
WEEK = 7 * DAY
BASE = 1_700_000_000_000   # ustalony epoch ms (UTC); now dla wszystkich testów


def test_baseline_circadian_tier(tmp_path, use_utc):
    s = Store(tmp_path / "k.db")
    # 12 bucketów dokładnie 7 dni od siebie → ta sama hour-of-week co BASE
    pts = [(BASE - k * WEEK, 40.0 if k % 2 == 0 else 60.0) for k in range(12)]
    _seed_rollup(s, "cpu.loadavg.1", pts)
    mean, sigma, n, tier = s.baseline("cpu.loadavg.1", BASE)
    assert tier == "circadian"
    assert n == 12
    assert mean == 50.0
    assert abs(sigma - 10.0) < 1e-9
    s.close()


def test_baseline_falls_back_to_hour_tier(tmp_path, use_utc):
    s = Store(tmp_path / "k.db")
    # 3 buckety tej samej hour-of-week (tygodniowe) → circadian=3 (<10)
    weekly = [(BASE - k * WEEK, 50.0) for k in range(3)]
    # 9 bucketów dobowych (NIE wielokrotności 7 dni) → ta sama hour-of-DAY, inny dzień tygodnia
    daily = [(BASE - k * DAY, 50.0) for k in (1, 2, 3, 4, 5, 6, 8, 9, 10)]
    _seed_rollup(s, "cpu.loadavg.1", weekly + daily)
    _, _, n, tier = s.baseline("cpu.loadavg.1", BASE)
    assert tier == "hour"          # circadian=3<10, hour=3+9=12>=10
    assert n == 12
    s.close()


def test_baseline_falls_back_to_global_tier(tmp_path, use_utc):
    s = Store(tmp_path / "k.db")
    # 11 bucketów w obrębie 7d, godzina-doby przesunięta o nieparzyste h → nigdy == BASE hour
    pts = [(BASE - 3_600_000 - k * 7_200_000, 50.0) for k in range(11)]
    _seed_rollup(s, "cpu.loadavg.1", pts)
    _, _, n, tier = s.baseline("cpu.loadavg.1", BASE)
    assert tier == "global"        # circadian=0, hour=0, global=11>=10
    assert n == 11
    s.close()


def test_baseline_none_when_insufficient(tmp_path, use_utc):
    s = Store(tmp_path / "k.db")
    _seed_rollup(s, "cpu.loadavg.1", [(BASE, 50.0), (BASE - WEEK, 51.0)])  # tylko 2
    assert s.baseline("cpu.loadavg.1", BASE) is None
    assert s.baseline("never.seen.series", BASE) is None                   # brak serii
    s.close()


def test_baseline_constant_series_sigma_zero(tmp_path, use_utc):
    s = Store(tmp_path / "k.db")
    _seed_rollup(s, "thermal.coretemp.0.pkg", [(BASE - k * WEEK, 95.0) for k in range(12)])
    mean, sigma, n, tier = s.baseline("thermal.coretemp.0.pkg", BASE)
    assert mean == 95.0
    assert sigma == 0.0            # konsument (glyph) zrobi guard EPS → z=0, proximity ratuje
    assert tier == "circadian"
    s.close()
