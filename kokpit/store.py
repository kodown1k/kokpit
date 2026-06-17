import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1


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
            self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self.conn.commit()

    def series_id(self, name: str) -> int:
        cached = self._series_cache.get(name)
        if cached is not None:
            return cached
        self.conn.execute("INSERT OR IGNORE INTO series_dict(name) VALUES (?)", (name,))
        sid = self.conn.execute("SELECT id FROM series_dict WHERE name=?", (name,)).fetchone()[0]
        self._series_cache[name] = sid   # caller's write() owns the transaction — no commit here
        return sid

    def write(self, ts_ms: int, samples: dict) -> None:
        if not samples:
            return
        with self.conn:  # one transaction per tick: dict inserts + sample inserts commit together
            rows = [(ts_ms, self.series_id(name), float(value)) for name, value in samples.items()]
            self.conn.executemany(
                "INSERT OR REPLACE INTO sample(ts, series_id, value) VALUES (?,?,?)", rows
            )

    def query(self, series: str, since_ms: int, until_ms: int) -> list:
        rows = self.conn.execute(
            "SELECT s.ts, s.value FROM sample s "
            "JOIN series_dict d ON d.id = s.series_id "
            "WHERE d.name=? AND s.ts>=? AND s.ts<=? ORDER BY s.ts",
            (series, since_ms, until_ms),
        ).fetchall()
        return [(int(ts), float(v)) for ts, v in rows]

    def close(self) -> None:
        self.conn.close()
