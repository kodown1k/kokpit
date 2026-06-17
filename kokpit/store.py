import sqlite3
from pathlib import Path

from kokpit import config

SCHEMA_VERSION = 2


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.commit()
        self._series_cache: dict[str, int] = {}
        self._migrate()

    def _migrate(self) -> None:
        v = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if v < 1:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS series_dict (
                    id   INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS sample (
                    ts        INTEGER NOT NULL,
                    series_id INTEGER NOT NULL REFERENCES series_dict(id),
                    value     REAL    NOT NULL,
                    PRIMARY KEY (series_id, ts)
                ) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS rollup_1m (
                    bucket    INTEGER NOT NULL,
                    series_id INTEGER NOT NULL REFERENCES series_dict(id),
                    vmin REAL, vmax REAL, vavg REAL, vlast REAL,
                    PRIMARY KEY (series_id, bucket)
                ) WITHOUT ROWID;
                """
            )
            v = 1
        if v < 2:
            # idx na samym ts: rollup_1m/prune filtrują po ts, a PK (series_id, ts)
            # nie da się użyć dla samego ts -> bez tego full table scan co minutę
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_ts ON sample(ts)")
            v = 2
        self.conn.execute(f"PRAGMA user_version={v}")
        self.conn.commit()

    def series_id(self, name: str) -> int:
        cached = self._series_cache.get(name)
        if cached is not None:
            return cached
        self.conn.execute("INSERT OR IGNORE INTO series_dict(name) VALUES (?)", (name,))
        sid = self.conn.execute("SELECT id FROM series_dict WHERE name=?", (name,)).fetchone()[0]
        return sid   # do NOT cache here: caching before the caller commits would leave a stale id on rollback

    def write(self, ts_ms: int, samples: dict[str, float]) -> None:
        if not samples:
            return
        ids: dict[str, int] = {}
        with self.conn:  # one transaction per tick: dict inserts + sample inserts commit together
            for name in samples:
                ids[name] = self.series_id(name)
            self.conn.executemany(
                "INSERT OR REPLACE INTO sample(ts, series_id, value) VALUES (?,?,?)",
                [(ts_ms, ids[name], float(value)) for name, value in samples.items()],
            )
        self._series_cache.update(ids)  # cache only after the tick commits -> no stale ids on rollback

    def query(self, series: str, since_ms: int, until_ms: int) -> list:
        rows = self.conn.execute(
            "SELECT s.ts, s.value FROM sample s "
            "JOIN series_dict d ON d.id = s.series_id "
            "WHERE d.name=? AND s.ts>=? AND s.ts<=? ORDER BY s.ts",
            (series, since_ms, until_ms),
        ).fetchall()
        return [(int(ts), float(v)) for ts, v in rows]

    def query_rollup(self, series: str, since_ms: int, until_ms: int) -> list:
        """Punkty z rollup_1m dla danej serii, rosnąco po bucket.

        Zwraca [(bucket_ms, vmin, vmax, vavg, vlast)] — pełna piątka agregatów
        w jednym zapytaniu, by UI rysowało linię (vavg) i pasmo min–max bez
        drugiego round-tripu. Symetryczne do query() (raw [(ts, value)]).
        """
        rows = self.conn.execute(
            "SELECT r.bucket, r.vmin, r.vmax, r.vavg, r.vlast FROM rollup_1m r "
            "JOIN series_dict d ON d.id = r.series_id "
            "WHERE d.name=? AND r.bucket>=? AND r.bucket<=? ORDER BY r.bucket",
            (series, since_ms, until_ms),
        ).fetchall()
        return [(int(b), float(vmin), float(vmax), float(vavg), float(vlast))
                for b, vmin, vmax, vavg, vlast in rows]

    def list_series(self, prefix: str | None = None) -> list[str]:
        """Nazwy serii znane bazie (z series_dict), rosnąco.

        prefix (np. 'net.' albo 'thermal.core.') filtruje przez LIKE prefix%.
        UI używa tego, gdy demon nie żyje i nie ma live-snapshotu do odkrycia
        dynamicznych serii (interfejsy sieci, dyski, rdzenie temp).
        """
        if prefix is None:
            rows = self.conn.execute(
                "SELECT name FROM series_dict ORDER BY name"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT name FROM series_dict WHERE name LIKE ?||'%' ORDER BY name",
                (prefix,),
            ).fetchall()
        return [name for (name,) in rows]

    # --- dopisz w klasie Store, pod query() ---

    def rollup_1m(self, now_ms: int) -> None:
        since = now_ms - config.ROLLUP_LOOKBACK_MS  # przelicz buckety z ostatniej godziny
        b = config.ROLLUP_BUCKET_MS                 # int z configu -> bezpieczny w f-stringu SQL
        aggs = self.conn.execute(
            f"SELECT (ts/{b})*{b} AS bucket, series_id, MIN(value), MAX(value), AVG(value) "
            "FROM sample WHERE ts >= ? GROUP BY bucket, series_id",
            (since,),
        ).fetchall()
        # vlast = value przy MAX(ts) w buckecie. SQLite "bare column": gdy w
        # zapytaniu jest DOKŁADNIE jeden max(), nagie kolumny (value) pochodzą
        # z tego samego wiersza co maksimum. Zastępuje skorelowane podzapytanie
        # (które było O(N^2) — skan tabeli per wiersz).
        last_rows = self.conn.execute(
            f"SELECT (ts/{b})*{b} AS bucket, series_id, value, MAX(ts) "
            "FROM sample WHERE ts >= ? GROUP BY bucket, series_id",
            (since,),
        ).fetchall()
        last = {(b, sid): v for b, sid, v, _ in last_rows}
        rows = [
            (b, sid, vmin, vmax, vavg, last.get((b, sid), vavg))
            for b, sid, vmin, vmax, vavg in aggs
        ]
        if rows:
            self.conn.executemany(
                "INSERT OR REPLACE INTO rollup_1m(bucket, series_id, vmin, vmax, vavg, vlast) "
                "VALUES (?,?,?,?,?,?)",
                rows,
            )

    def prune(self, now_ms: int) -> None:
        self.conn.execute("DELETE FROM sample WHERE ts < ?", (now_ms - config.RAW_RETENTION_S * 1000,))
        self.conn.execute("DELETE FROM rollup_1m WHERE bucket < ?", (now_ms - config.ROLLUP_RETENTION_S * 1000,))

    def checkpoint(self) -> None:
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def close(self) -> None:
        self.conn.close()
