# kokpit — Kolektor Backend — Implementation Plan (Plan 1/2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Headless demon (`kokpit-collectord`) próbkuje co 1 s metryki tej maszyny (CPU, GPU, RAM, dyski, sieć, procesy, temperatury), zapisuje je do SQLite (raw + rollup_1m) i publikuje żywy snapshot przez Unix socket — wszystko testowalne bez UI.

**Architecture:** Źródła (`sources/*`) implementują wspólny kontrakt `sample(now_ms, dt_s) -> dict[str,float]`; `LocalHost.collect()` scala je z izolacją błędów per-source; `Store` zapisuje cały tick w jednej transakcji do SQLite WAL; `LiveServer` broadcastuje NDJSON do klientów; `collectord` spina to w pętlę 1 Hz z okresowym rollupem/prune/checkpoint.

**Tech Stack:** Python 3.12, `psutil`, `nvidia-ml-py` (import `pynvml`), `sensors -j` (subprocess), SQLite (stdlib `sqlite3`), `pytest`.

## Global Constraints

- Python **>= 3.12**. Pakiet `kokpit/` w repo `~/Code/kokpit`. Wzorzec jak `ghostty-vitals` (pyproject + `.venv` + `tests/` + pytest).
- Zależność GPU: **`nvidia-ml-py`** (NIE `pynvml` — deprecated); w kodzie import dalej `import pynvml`.
- Temperatury: subprocess **`sensors -j`** (nie hwmon w MVP).
- Demon **bez roota**; tylko lokalny Unix socket (brak nasłuchu sieciowego).
- Kontrakt źródła float: `Source.sample(now_ms: int, dt_s: float) -> dict[str, float]`. `now_ms` = epoch ms (`int(time.time()*1000)`). `dt_s` = **zmierzony** monotoniczny odstęp ticków (sekundy); pierwszy tick `dt_s == 0.0`.
- Serie prędkości (bps) liczone z delty liczników kumulatywnych: pierwszy tick **pomija** serię; reset/wrap licznika → clamp `max(0, Δ)/dt`.
- Snapshot live: `{"ts": int, "series": dict[str,float], "procs": list[dict]}`, serializowany jako **newline-delimited JSON** (jedna linia/snapshot).
- SQLite: WAL, `synchronous=NORMAL`, `PRAGMA user_version` + migracje stepwise; **jedna transakcja na tick**; checkpoint **tylko** w demonie.
- Buckety rollupu: arytmetyka na epoch ms `(ts // 60000) * 60000` (DST-safe).
- Commity: częste, jeden na zadanie (lub mniej). Repo inicjalizowane w Task 1.

---

## File Structure

```
~/Code/kokpit/
  pyproject.toml                  # T1
  .gitignore                      # T1
  kokpit/
    __init__.py                   # T1
    config.py                     # T1  — ścieżki, retencje, filtry iface/disk
    store.py                      # T2,T3 — Store: schema/migracje/write/query/rollup/prune/checkpoint
    sources/
      __init__.py                 # T1
      base.py                     # T4  — Source protocol, RateCounter
      cpu.py                      # T5  — CpuSource
      memory.py                   # T5  — MemorySource
      net.py                      # T6  — NetSource (stateful delta)
      disk.py                     # T6  — DiskSource (stateful delta + usage)
      thermal.py                  # T7  — ThermalSource (sensors -j)
      gpu.py                      # T8  — GpuSource (nvidia-ml-py, 0/multi-GPU)
    proc.py                       # T9  — ProcCollector (top-N + VRAM per PID)
    host.py                       # T10 — LocalHost.collect()
    live.py                       # T11 — LiveServer (NDJSON broadcast)
    collectord.py                 # T12 — daemon loop + main()
  packaging/
    kokpit-collectord.service     # T13
  tests/
    test_store.py                 # T2,T3
    test_rate.py                  # T4
    test_cpu.py  test_memory.py   # T5
    test_net.py  test_disk.py     # T6
    test_thermal.py               # T7
    test_gpu.py                   # T8
    test_proc.py                  # T9
    test_host.py                  # T10
    test_live.py                  # T11
    test_collectord.py            # T12
```

---

### Task 1: Scaffold projektu + config

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `kokpit/__init__.py`, `kokpit/sources/__init__.py`, `kokpit/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `kokpit.config.SAMPLE_HZ: float`, `RAW_RETENTION_S: int`, `ROLLUP_RETENTION_S: int`, `data_dir() -> Path`, `db_path() -> Path`, `socket_path() -> Path`, `IFACE_DENY: re.Pattern`, `DISK_DENY: re.Pattern`.

- [ ] **Step 1: Inicjalizuj repo i wirtualne środowisko**

```bash
cd ~/Code/kokpit
git init
python3.12 -m venv .venv
.venv/bin/pip install -U pip
```

- [ ] **Step 2: Napisz `pyproject.toml`**

```toml
[project]
name = "kokpit"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["psutil>=6.0", "nvidia-ml-py>=12.560"]

[project.optional-dependencies]
ui = ["PySide6>=6.7", "pyqtgraph>=0.13"]
dev = ["pytest>=8.0"]

[project.scripts]
kokpit-collectord = "kokpit.collectord:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["kokpit*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Napisz `.gitignore`**

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
*.db
*.db-wal
*.db-shm
.superpowers/
```

- [ ] **Step 4: Utwórz puste pakiety**

```bash
touch kokpit/__init__.py kokpit/sources/__init__.py
```

- [ ] **Step 5: Napisz `kokpit/config.py`**

```python
import os
import re
from pathlib import Path

SAMPLE_HZ = 1.0
RAW_RETENTION_S = 48 * 3600           # 48h surowych próbek
ROLLUP_RETENTION_S = 30 * 24 * 3600   # 30 dni rollupu 1-minutowego


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "kokpit"


def db_path() -> Path:
    return data_dir() / "kokpit.db"


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path("/tmp")
    return base / "kokpit.sock"


# Interfejsy/urządzenia wirtualne pomijane w metrykach sieci/dysków
IFACE_DENY = re.compile(r"^(lo|veth|br-|docker|tailscale|virbr|vmnet)|warp", re.IGNORECASE)
DISK_DENY = re.compile(r"^(loop|ram|dm-|sr|fd)\d*$", re.IGNORECASE)
```

- [ ] **Step 6: Napisz test config**

```python
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
```

- [ ] **Step 7: Zainstaluj i uruchom testy**

Run: `.venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -q`
Expected: PASS (2 passed)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "chore: scaffold kokpit package + config"
```

---

### Task 2: Store — schema, migracje, write, query

**Files:**
- Create: `kokpit/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: nic.
- Produces: `kokpit.store.Store(path)` z `series_id(name) -> int`, `write(ts_ms: int, samples: dict[str,float]) -> None`, `query(series: str, since_ms: int, until_ms: int) -> list[tuple[int,float]]`, `close() -> None`, atrybut `conn` (sqlite3.Connection), stała `SCHEMA_VERSION: int`.

- [ ] **Step 1: Napisz failing test**

```python
# tests/test_store.py
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
```

- [ ] **Step 2: Uruchom test — ma się wywalić**

Run: `.venv/bin/pytest tests/test_store.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'kokpit.store'`)

- [ ] **Step 3: Zaimplementuj `kokpit/store.py`**

```python
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
        self.conn.commit()
        self._series_cache[name] = sid
        return sid

    def write(self, ts_ms: int, samples: dict) -> None:
        rows = [(ts_ms, self.series_id(name), float(value)) for name, value in samples.items()]
        if not rows:
            return
        self.conn.executemany(
            "INSERT OR REPLACE INTO sample(ts, series_id, value) VALUES (?,?,?)", rows
        )
        self.conn.commit()

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
```

- [ ] **Step 4: Uruchom testy — mają przejść**

Run: `.venv/bin/pytest tests/test_store.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/store.py tests/test_store.py
git commit -m "feat(store): SQLite schema, migrations, write/query"
```

---

### Task 3: Store — rollup_1m, prune, checkpoint

**Files:**
- Modify: `kokpit/store.py`
- Test: `tests/test_store.py` (dopisz)

**Interfaces:**
- Consumes: `Store` z Task 2.
- Produces: `Store.rollup_1m(now_ms: int) -> None`, `Store.prune(now_ms: int) -> None`, `Store.checkpoint() -> None`.

- [ ] **Step 1: Dopisz failing testy**

```python
# tests/test_store.py  (dopisz na końcu)
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
```

- [ ] **Step 2: Uruchom — failują**

Run: `.venv/bin/pytest tests/test_store.py -q`
Expected: FAIL (`AttributeError: 'Store' object has no attribute 'rollup_1m'`)

- [ ] **Step 3: Dopisz metody do `kokpit/store.py`**

```python
    # --- dopisz w klasie Store, pod query() ---

    def rollup_1m(self, now_ms: int) -> None:
        since = now_ms - 3600_000  # przelicz buckety z ostatniej godziny
        aggs = self.conn.execute(
            "SELECT (ts/60000)*60000 AS bucket, series_id, MIN(value), MAX(value), AVG(value) "
            "FROM sample WHERE ts >= ? GROUP BY bucket, series_id",
            (since,),
        ).fetchall()
        last_rows = self.conn.execute(
            "SELECT (ts/60000)*60000 AS bucket, series_id, value FROM sample s "
            "WHERE ts >= ? AND ts = ("
            "  SELECT MAX(ts) FROM sample s2 WHERE s2.series_id = s.series_id "
            "  AND (s2.ts/60000)*60000 = (s.ts/60000)*60000)",
            (since,),
        ).fetchall()
        last = {(b, sid): v for b, sid, v in last_rows}
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
            self.conn.commit()

    def prune(self, now_ms: int) -> None:
        from kokpit import config
        self.conn.execute("DELETE FROM sample WHERE ts < ?", (now_ms - config.RAW_RETENTION_S * 1000,))
        self.conn.execute("DELETE FROM rollup_1m WHERE bucket < ?", (now_ms - config.ROLLUP_RETENTION_S * 1000,))
        self.conn.commit()

    def checkpoint(self) -> None:
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
```

- [ ] **Step 4: Uruchom — przechodzą**

Run: `.venv/bin/pytest tests/test_store.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/store.py tests/test_store.py
git commit -m "feat(store): rollup_1m, prune, checkpoint"
```

---

### Task 4: Source protocol + RateCounter

**Files:**
- Create: `kokpit/sources/base.py`
- Test: `tests/test_rate.py`

**Interfaces:**
- Produces: `kokpit.sources.base.Source` (Protocol z `name: str` i `sample(now_ms: int, dt_s: float) -> dict[str,float]`), `Sample = dict[str,float]`, `RateCounter()` z `update(value: float, dt_s: float) -> float | None`.

- [ ] **Step 1: Napisz failing test**

```python
# tests/test_rate.py
from kokpit.sources.base import RateCounter


def test_first_sample_returns_none():
    rc = RateCounter()
    assert rc.update(1000.0, 1.0) is None


def test_steady_rate():
    rc = RateCounter()
    rc.update(1000.0, 1.0)
    assert rc.update(1100.0, 1.0) == 100.0     # 100 jednostek / 1s


def test_uses_measured_dt():
    rc = RateCounter()
    rc.update(0.0, 1.0)
    assert rc.update(100.0, 2.0) == 50.0       # dzieli przez zmierzony dt


def test_counter_reset_clamped_to_zero():
    rc = RateCounter()
    rc.update(5000.0, 1.0)
    assert rc.update(10.0, 1.0) == 0.0         # delta < 0 -> clamp


def test_zero_dt_returns_none():
    rc = RateCounter()
    rc.update(1.0, 1.0)
    assert rc.update(2.0, 0.0) is None
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_rate.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'kokpit.sources.base'`)

- [ ] **Step 3: Zaimplementuj `kokpit/sources/base.py`**

```python
from typing import Protocol

Sample = dict[str, float]


class Source(Protocol):
    name: str

    def sample(self, now_ms: int, dt_s: float) -> Sample: ...


class RateCounter:
    """Zamienia licznik kumulatywny na prędkość/s. Pierwszy odczyt -> None."""

    def __init__(self) -> None:
        self._last: float | None = None

    def update(self, value: float, dt_s: float) -> float | None:
        prev, self._last = self._last, value
        if prev is None or dt_s <= 0:
            return None
        return max(0.0, value - prev) / dt_s
```

- [ ] **Step 4: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_rate.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/sources/base.py tests/test_rate.py
git commit -m "feat(sources): Source protocol + RateCounter"
```

---

### Task 5: CpuSource + MemorySource

**Files:**
- Create: `kokpit/sources/cpu.py`, `kokpit/sources/memory.py`
- Test: `tests/test_cpu.py`, `tests/test_memory.py`

**Interfaces:**
- Consumes: `Source` z Task 4.
- Produces: `CpuSource()` (`name="cpu"`), `MemorySource()` (`name="memory"`), oba z `sample(now_ms, dt_s) -> dict[str,float]`.
- Klucze CPU: `cpu.thread.{i}.util`, `cpu.thread.{i}.freq`, `cpu.loadavg.1`. Klucze mem: `mem.used`, `mem.total`, `swap.used`.

- [ ] **Step 1: Napisz failing testy**

```python
# tests/test_cpu.py
import types
from kokpit.sources import cpu as cpu_mod
from kokpit.sources.cpu import CpuSource


def test_cpu_sample_keys(monkeypatch):
    monkeypatch.setattr(cpu_mod.psutil, "cpu_percent", lambda percpu: [10.0, 20.0])
    monkeypatch.setattr(
        cpu_mod.psutil, "cpu_freq",
        lambda percpu: [types.SimpleNamespace(current=3000.0), types.SimpleNamespace(current=3100.0)],
    )
    monkeypatch.setattr(cpu_mod.psutil, "getloadavg", lambda: (1.5, 1.0, 0.5))
    out = CpuSource().sample(now_ms=0, dt_s=1.0)
    assert out["cpu.thread.0.util"] == 10.0
    assert out["cpu.thread.1.util"] == 20.0
    assert out["cpu.thread.0.freq"] == 3000.0
    assert out["cpu.loadavg.1"] == 1.5
```

```python
# tests/test_memory.py
import types
from kokpit.sources import memory as mem_mod
from kokpit.sources.memory import MemorySource


def test_memory_sample(monkeypatch):
    monkeypatch.setattr(mem_mod.psutil, "virtual_memory",
                        lambda: types.SimpleNamespace(used=100.0, total=200.0))
    monkeypatch.setattr(mem_mod.psutil, "swap_memory",
                        lambda: types.SimpleNamespace(used=5.0))
    out = MemorySource().sample(now_ms=0, dt_s=1.0)
    assert out == {"mem.used": 100.0, "mem.total": 200.0, "swap.used": 5.0}
```

- [ ] **Step 2: Uruchom — failują**

Run: `.venv/bin/pytest tests/test_cpu.py tests/test_memory.py -q`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Zaimplementuj `kokpit/sources/cpu.py`**

```python
import psutil
from kokpit.sources.base import Sample


class CpuSource:
    name = "cpu"

    def sample(self, now_ms: int, dt_s: float) -> Sample:
        out: Sample = {}
        for i, pct in enumerate(psutil.cpu_percent(percpu=True)):
            out[f"cpu.thread.{i}.util"] = float(pct)
        freqs = psutil.cpu_freq(percpu=True) or []
        for i, f in enumerate(freqs):
            out[f"cpu.thread.{i}.freq"] = float(f.current)
        try:
            la1 = psutil.getloadavg()[0]
            out["cpu.loadavg.1"] = float(la1)
        except (OSError, AttributeError):
            pass
        return out
```

- [ ] **Step 4: Zaimplementuj `kokpit/sources/memory.py`**

```python
import psutil
from kokpit.sources.base import Sample


class MemorySource:
    name = "memory"

    def sample(self, now_ms: int, dt_s: float) -> Sample:
        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        return {
            "mem.used": float(vm.used),
            "mem.total": float(vm.total),
            "swap.used": float(sm.used),
        }
```

- [ ] **Step 5: Uruchom — przechodzą**

Run: `.venv/bin/pytest tests/test_cpu.py tests/test_memory.py -q`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add kokpit/sources/cpu.py kokpit/sources/memory.py tests/test_cpu.py tests/test_memory.py
git commit -m "feat(sources): cpu + memory"
```

---

### Task 6: NetSource + DiskSource (stateful delta)

**Files:**
- Create: `kokpit/sources/net.py`, `kokpit/sources/disk.py`
- Test: `tests/test_net.py`, `tests/test_disk.py`

**Interfaces:**
- Consumes: `RateCounter` (Task 4), `config.IFACE_DENY`/`DISK_DENY` (Task 1).
- Produces: `NetSource()` (`name="net"`), `DiskSource()` (`name="disk"`). Klucze: `net.{iface}.rx_bps`/`tx_bps`; `disk.{dev}.read_bps`/`write_bps`; `disk.{mount}.used_pct`.

- [ ] **Step 1: Napisz failing testy**

```python
# tests/test_net.py
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
```

```python
# tests/test_disk.py
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
```

- [ ] **Step 2: Uruchom — failują**

Run: `.venv/bin/pytest tests/test_net.py tests/test_disk.py -q`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Zaimplementuj `kokpit/sources/net.py`**

```python
import psutil
from kokpit.config import IFACE_DENY
from kokpit.sources.base import RateCounter, Sample


class NetSource:
    name = "net"

    def __init__(self) -> None:
        self._rx: dict[str, RateCounter] = {}
        self._tx: dict[str, RateCounter] = {}

    def sample(self, now_ms: int, dt_s: float) -> Sample:
        out: Sample = {}
        for iface, c in psutil.net_io_counters(pernic=True).items():
            if IFACE_DENY.search(iface):
                continue
            rx = self._rx.setdefault(iface, RateCounter()).update(c.bytes_recv, dt_s)
            tx = self._tx.setdefault(iface, RateCounter()).update(c.bytes_sent, dt_s)
            if rx is not None:
                out[f"net.{iface}.rx_bps"] = rx
            if tx is not None:
                out[f"net.{iface}.tx_bps"] = tx
        return out
```

- [ ] **Step 4: Zaimplementuj `kokpit/sources/disk.py`**

```python
import psutil
from kokpit.config import DISK_DENY
from kokpit.sources.base import RateCounter, Sample


class DiskSource:
    name = "disk"

    def __init__(self) -> None:
        self._r: dict[str, RateCounter] = {}
        self._w: dict[str, RateCounter] = {}

    def sample(self, now_ms: int, dt_s: float) -> Sample:
        out: Sample = {}
        for dev, c in (psutil.disk_io_counters(perdisk=True) or {}).items():
            if DISK_DENY.match(dev):
                continue
            r = self._r.setdefault(dev, RateCounter()).update(c.read_bytes, dt_s)
            w = self._w.setdefault(dev, RateCounter()).update(c.write_bytes, dt_s)
            if r is not None:
                out[f"disk.{dev}.read_bps"] = r
            if w is not None:
                out[f"disk.{dev}.write_bps"] = w
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            out[f"disk.{part.mountpoint}.used_pct"] = float(usage.percent)
        return out
```

- [ ] **Step 5: Uruchom — przechodzą**

Run: `.venv/bin/pytest tests/test_net.py tests/test_disk.py -q`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add kokpit/sources/net.py kokpit/sources/disk.py tests/test_net.py tests/test_disk.py
git commit -m "feat(sources): net + disk with stateful rate deltas"
```

---

### Task 7: ThermalSource (`sensors -j`)

**Files:**
- Create: `kokpit/sources/thermal.py`
- Test: `tests/test_thermal.py`

**Interfaces:**
- Produces: `ThermalSource(runner=None)` (`name="thermal"`); `runner` to opcjonalna funkcja `() -> str` zwracająca JSON (do testów). Klucze: `thermal.pkg`, `thermal.core.{N}` (N = numer „Core N" z sensors), `thermal.nvme.{idx}`, `thermal.wifi`.

- [ ] **Step 1: Napisz failing test**

```python
# tests/test_thermal.py
import json
from kokpit.sources.thermal import ThermalSource

FIXTURE = json.dumps({
    "coretemp-isa-0000": {
        "Adapter": "ISA adapter",
        "Package id 0": {"temp1_input": 97.0, "temp1_crit": 100.0},
        "Core 0": {"temp2_input": 91.0},
        "Core 4": {"temp3_input": 90.0},
    },
    "nvme-pci-e200": {"Composite": {"temp1_input": 53.9}},
    "iwlwifi_1-virtual-0": {"temp1": {"temp1_input": 55.0}},
})


def test_thermal_parses_sensors_json():
    out = ThermalSource(runner=lambda: FIXTURE).sample(now_ms=0, dt_s=1.0)
    assert out["thermal.pkg"] == 97.0
    assert out["thermal.core.0"] == 91.0
    assert out["thermal.core.4"] == 90.0
    assert out["thermal.nvme.0"] == 53.9
    assert out["thermal.wifi"] == 55.0


def test_thermal_bad_output_returns_empty():
    assert ThermalSource(runner=lambda: "not json").sample(now_ms=0, dt_s=1.0) == {}
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_thermal.py -q`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Zaimplementuj `kokpit/sources/thermal.py`**

```python
import json
import subprocess
from kokpit.sources.base import Sample


def _first_input(vals) -> float | None:
    if not isinstance(vals, dict):
        return None
    for k, v in vals.items():
        if k.endswith("_input"):
            return float(v)
    return None


class ThermalSource:
    name = "thermal"

    def __init__(self, runner=None) -> None:
        self._runner = runner or self._run_sensors

    @staticmethod
    def _run_sensors() -> str:
        return subprocess.run(
            ["sensors", "-j"], capture_output=True, text=True, timeout=5
        ).stdout

    def sample(self, now_ms: int, dt_s: float) -> Sample:
        try:
            data = json.loads(self._runner() or "{}")
        except (json.JSONDecodeError, subprocess.SubprocessError, FileNotFoundError, OSError):
            return {}
        out: Sample = {}
        nvme_idx = 0
        for chip, feats in data.items():
            if not isinstance(feats, dict):
                continue
            if chip.startswith("coretemp"):
                for feat, vals in feats.items():
                    if feat.startswith("Package id"):
                        t = _first_input(vals)
                        if t is not None:
                            out["thermal.pkg"] = t
                    elif feat.startswith("Core "):
                        t = _first_input(vals)
                        if t is not None:
                            out[f"thermal.core.{feat.split()[1]}"] = t
            elif chip.startswith("nvme"):
                t = _first_input(feats.get("Composite"))
                if t is not None:
                    out[f"thermal.nvme.{nvme_idx}"] = t
                    nvme_idx += 1
            elif "iwlwifi" in chip or "wifi" in chip:
                for vals in feats.values():
                    t = _first_input(vals)
                    if t is not None:
                        out["thermal.wifi"] = t
                        break
        return out
```

- [ ] **Step 4: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_thermal.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/sources/thermal.py tests/test_thermal.py
git commit -m "feat(sources): thermal via sensors -j"
```

---

### Task 8: GpuSource (`nvidia-ml-py`, 0/multi-GPU)

**Files:**
- Create: `kokpit/sources/gpu.py`
- Test: `tests/test_gpu.py`

**Interfaces:**
- Produces: `GpuSource(nvml=None)` (`name="gpu"`); `nvml` to wstrzykiwalny moduł NVML (do testów); gdy `None`, próbuje `import pynvml` i `nvmlInit()` (cisza przy braku GPU → `sample` zwraca `{}`). Klucze: `gpu.{i}.util`, `.vram_used`, `.vram_total`, `.temp`, `.power` (W), `.clock_sm`, `.fan`.

- [ ] **Step 1: Napisz failing test**

```python
# tests/test_gpu.py
import types
from kokpit.sources.gpu import GpuSource


def _fake_nvml():
    n = types.SimpleNamespace()
    n.NVML_TEMPERATURE_GPU = 0
    n.NVML_CLOCK_SM = 1
    n.nvmlDeviceGetCount = lambda: 1
    n.nvmlDeviceGetHandleByIndex = lambda i: f"h{i}"
    n.nvmlDeviceGetUtilizationRates = lambda h: types.SimpleNamespace(gpu=63)
    n.nvmlDeviceGetMemoryInfo = lambda h: types.SimpleNamespace(used=11.2e9, total=16e9)
    n.nvmlDeviceGetTemperature = lambda h, kind: 71
    n.nvmlDeviceGetPowerUsage = lambda h: 120000      # mW -> 120 W
    n.nvmlDeviceGetClockInfo = lambda h, kind: 2400
    n.nvmlDeviceGetFanSpeed = lambda h: 45
    return n


def test_gpu_sample():
    out = GpuSource(nvml=_fake_nvml()).sample(now_ms=0, dt_s=1.0)
    assert out["gpu.0.util"] == 63.0
    assert out["gpu.0.vram_used"] == 11.2e9
    assert out["gpu.0.temp"] == 71.0
    assert out["gpu.0.power"] == 120.0
    assert out["gpu.0.clock_sm"] == 2400.0
    assert out["gpu.0.fan"] == 45.0


def test_gpu_zero_devices_returns_empty():
    n = _fake_nvml()
    n.nvmlDeviceGetCount = lambda: 0
    assert GpuSource(nvml=n).sample(now_ms=0, dt_s=1.0) == {}


def test_gpu_no_nvml_returns_empty():
    src = GpuSource.__new__(GpuSource)   # pomiń __init__/import
    src._nvml = None
    assert src.sample(now_ms=0, dt_s=1.0) == {}
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_gpu.py -q`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Zaimplementuj `kokpit/sources/gpu.py`**

```python
import logging
from kokpit.sources.base import Sample

log = logging.getLogger("kokpit.gpu")


class GpuSource:
    name = "gpu"

    def __init__(self, nvml=None) -> None:
        if nvml is not None:
            self._nvml = nvml
            return
        try:
            import pynvml  # pakiet: nvidia-ml-py
            pynvml.nvmlInit()
            self._nvml = pynvml
        except Exception:
            log.warning("NVML niedostępne — GPU pominięte")
            self._nvml = None

    def sample(self, now_ms: int, dt_s: float) -> Sample:
        n = self._nvml
        if n is None:
            return {}
        out: Sample = {}
        try:
            count = n.nvmlDeviceGetCount()
        except Exception:
            return {}
        for i in range(count):
            try:
                h = n.nvmlDeviceGetHandleByIndex(i)
                util = n.nvmlDeviceGetUtilizationRates(h)
                mem = n.nvmlDeviceGetMemoryInfo(h)
                out[f"gpu.{i}.util"] = float(util.gpu)
                out[f"gpu.{i}.vram_used"] = float(mem.used)
                out[f"gpu.{i}.vram_total"] = float(mem.total)
                out[f"gpu.{i}.temp"] = float(n.nvmlDeviceGetTemperature(h, n.NVML_TEMPERATURE_GPU))
                out[f"gpu.{i}.power"] = float(n.nvmlDeviceGetPowerUsage(h)) / 1000.0
                out[f"gpu.{i}.clock_sm"] = float(n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_SM))
                try:
                    out[f"gpu.{i}.fan"] = float(n.nvmlDeviceGetFanSpeed(h))
                except Exception:
                    pass
            except Exception:
                log.exception("Odczyt GPU %d nieudany", i)
                continue
        return out
```

- [ ] **Step 4: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_gpu.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/sources/gpu.py tests/test_gpu.py
git commit -m "feat(sources): gpu via nvidia-ml-py (0/multi-GPU safe)"
```

---

### Task 9: ProcCollector (top-N + VRAM per PID)

**Files:**
- Create: `kokpit/proc.py`
- Test: `tests/test_proc.py`

**Interfaces:**
- Produces: `kokpit.proc.ProcCollector(top_n=8, nvml=None)` z `top() -> list[dict]`; każdy dict: `{"pid": int, "name": str, "cpu": float, "rss": float, "vram": float}`, posortowane malejąco po `cpu`, max `top_n`.

- [ ] **Step 1: Napisz failing test**

```python
# tests/test_proc.py
import types
from kokpit.proc import ProcCollector
from kokpit import proc as proc_mod


def test_top_sorts_and_merges_vram(monkeypatch):
    procs = [
        types.SimpleNamespace(info={"pid": 1, "name": "a", "cpu_percent": 5.0,
                                    "memory_info": types.SimpleNamespace(rss=100)}),
        types.SimpleNamespace(info={"pid": 2, "name": "b", "cpu_percent": 50.0,
                                    "memory_info": types.SimpleNamespace(rss=200)}),
    ]
    monkeypatch.setattr(proc_mod.psutil, "process_iter", lambda attrs: procs)
    n = types.SimpleNamespace()
    n.nvmlDeviceGetCount = lambda: 1
    n.nvmlDeviceGetHandleByIndex = lambda i: "h"
    n.nvmlDeviceGetComputeRunningProcesses = lambda h: [types.SimpleNamespace(pid=2, usedGpuMemory=4096)]
    n.nvmlDeviceGetGraphicsRunningProcesses = lambda h: []
    out = ProcCollector(top_n=2, nvml=n).top()
    assert [p["pid"] for p in out] == [2, 1]      # sort po cpu malejąco
    assert out[0]["vram"] == 4096.0               # zmergowane po PID
    assert out[1]["vram"] == 0.0
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_proc.py -q`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Zaimplementuj `kokpit/proc.py`**

```python
import logging
import psutil

log = logging.getLogger("kokpit.proc")


class ProcCollector:
    def __init__(self, top_n: int = 8, nvml=None) -> None:
        self.top_n = top_n
        self._nvml = nvml

    def _vram_by_pid(self) -> dict[int, float]:
        n = self._nvml
        if n is None:
            return {}
        out: dict[int, float] = {}
        try:
            for i in range(n.nvmlDeviceGetCount()):
                h = n.nvmlDeviceGetHandleByIndex(i)
                for fn in (n.nvmlDeviceGetComputeRunningProcesses,
                           n.nvmlDeviceGetGraphicsRunningProcesses):
                    try:
                        for p in fn(h):
                            used = getattr(p, "usedGpuMemory", None)
                            if used:
                                out[p.pid] = out.get(p.pid, 0.0) + float(used)
                    except Exception:
                        continue
        except Exception:
            return {}
        return out

    def top(self) -> list[dict]:
        vram = self._vram_by_pid()
        rows: list[dict] = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            info = p.info
            mi = info.get("memory_info")
            rows.append({
                "pid": info["pid"],
                "name": info.get("name") or "",
                "cpu": float(info.get("cpu_percent") or 0.0),
                "rss": float(mi.rss if mi else 0.0),
                "vram": float(vram.get(info["pid"], 0.0)),
            })
        rows.sort(key=lambda d: d["cpu"], reverse=True)
        return rows[: self.top_n]
```

- [ ] **Step 4: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_proc.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/proc.py tests/test_proc.py
git commit -m "feat(proc): top-N processes with NVML VRAM merge"
```

---

### Task 10: LocalHost.collect() (izolacja błędów per-source)

**Files:**
- Create: `kokpit/host.py`
- Test: `tests/test_host.py`

**Interfaces:**
- Consumes: `Source` (Task 4).
- Produces: `kokpit.host.LocalHost(sources: list[Source])` z `collect(now_ms: int, dt_s: float) -> dict[str,float]` — scala wszystkie źródła; wyjątek w jednym źródle jest logowany i pomijany (nie przerywa zbioru).

- [ ] **Step 1: Napisz failing test**

```python
# tests/test_host.py
from kokpit.host import LocalHost


class GoodSource:
    name = "good"
    def sample(self, now_ms, dt_s):
        return {"good.x": 1.0}


class BoomSource:
    name = "boom"
    def sample(self, now_ms, dt_s):
        raise RuntimeError("nope")


def test_collect_merges_and_isolates_errors():
    host = LocalHost([GoodSource(), BoomSource()])
    out = host.collect(now_ms=0, dt_s=1.0)
    assert out == {"good.x": 1.0}     # błąd BoomSource nie wywala zbioru
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_host.py -q`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Zaimplementuj `kokpit/host.py`**

```python
import logging

log = logging.getLogger("kokpit.host")


class LocalHost:
    def __init__(self, sources: list) -> None:
        self.sources = sources

    def collect(self, now_ms: int, dt_s: float) -> dict:
        merged: dict = {}
        for s in self.sources:
            try:
                merged.update(s.sample(now_ms, dt_s))
            except Exception:
                log.exception("źródło %s nieudane", getattr(s, "name", s))
        return merged
```

- [ ] **Step 4: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_host.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/host.py tests/test_host.py
git commit -m "feat(host): LocalHost.collect with per-source error isolation"
```

---

### Task 11: LiveServer (NDJSON broadcast po Unix socket)

**Files:**
- Create: `kokpit/live.py`
- Test: `tests/test_live.py`

**Interfaces:**
- Produces: `kokpit.live.LiveServer(sock_path)` z `start() -> None`, `publish(snapshot: dict) -> None`, `stop() -> None`. `publish` wysyła `json.dumps(snapshot)+"\n"` do każdego klienta; martwy klient usuwany, wolny (BlockingIOError) → pominięcie tego snapshotu. `start()` usuwa stale-socket przed `bind`.

- [ ] **Step 1: Napisz failing test**

```python
# tests/test_live.py
import json
import socket
import time
from kokpit.live import LiveServer


def test_publish_broadcasts_ndjson(tmp_path):
    sock_path = str(tmp_path / "k.sock")
    srv = LiveServer(sock_path)
    srv.start()
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(sock_path)
        time.sleep(0.6)                       # niech accept-loop zarejestruje klienta
        srv.publish({"ts": 1000, "series": {"gpu.0.util": 63.0}, "procs": []})
        client.settimeout(2.0)
        line = client.makefile().readline()
        msg = json.loads(line)
        assert msg["ts"] == 1000
        assert msg["series"]["gpu.0.util"] == 63.0
    finally:
        srv.stop()


def test_start_removes_stale_socket(tmp_path):
    sock_path = tmp_path / "k.sock"
    sock_path.write_text("stale")             # plik istnieje przed startem
    srv = LiveServer(str(sock_path))
    srv.start()                                # nie rzuca EADDRINUSE
    srv.stop()
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_live.py -q`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Zaimplementuj `kokpit/live.py`**

```python
import json
import logging
import os
import socket
import threading

log = logging.getLogger("kokpit.live")


class LiveServer:
    def __init__(self, sock_path) -> None:
        self.sock_path = str(sock_path)
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._srv: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        try:
            os.unlink(self.sock_path)          # usuń stale-socket
        except FileNotFoundError:
            pass
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.sock_path)
        self._srv.listen(8)
        self._srv.settimeout(0.5)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.setblocking(False)
            with self._lock:
                self._clients.append(conn)

    def publish(self, snapshot: dict) -> None:
        line = (json.dumps(snapshot) + "\n").encode()
        with self._lock:
            dead = []
            for c in self._clients:
                try:
                    c.sendall(line)
                except BlockingIOError:
                    pass                        # wolny klient: drop tego snapshotu
                except OSError:
                    dead.append(c)
            for c in dead:
                self._clients.remove(c)
                try:
                    c.close()
                except OSError:
                    pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._srv:
            self._srv.close()
        with self._lock:
            for c in self._clients:
                try:
                    c.close()
                except OSError:
                    pass
            self._clients.clear()
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass
```

- [ ] **Step 4: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_live.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/live.py tests/test_live.py
git commit -m "feat(live): NDJSON broadcast over Unix socket"
```

---

### Task 12: collectord — pętla demona + entrypoint

**Files:**
- Create: `kokpit/collectord.py`
- Test: `tests/test_collectord.py`

**Interfaces:**
- Consumes: `Store`, `LocalHost`, `LiveServer`, `ProcCollector`, wszystkie źródła.
- Produces: `kokpit.collectord.build_host() -> LocalHost`, `tick(host, store, live, procs, now_ms, dt_s) -> None`, `run() -> None`, `main() -> None`.
- `tick`: `series = host.collect(...)`; `store.write(now_ms, series)`; `live.publish({"ts": now_ms, "series": series, "procs": procs.top()})`.

- [ ] **Step 1: Napisz failing test (izolowany `tick`)**

```python
# tests/test_collectord.py
from kokpit.collectord import tick


class FakeHost:
    def collect(self, now_ms, dt_s):
        return {"cpu.thread.0.util": 12.0}


class FakeStore:
    def __init__(self):
        self.written = []
    def write(self, ts_ms, samples):
        self.written.append((ts_ms, samples))


class FakeLive:
    def __init__(self):
        self.published = []
    def publish(self, snapshot):
        self.published.append(snapshot)


class FakeProcs:
    def top(self):
        return [{"pid": 1, "name": "x", "cpu": 1.0, "rss": 1.0, "vram": 0.0}]


def test_tick_writes_and_publishes():
    store, live = FakeStore(), FakeLive()
    tick(FakeHost(), store, live, FakeProcs(), now_ms=5000, dt_s=1.0)
    assert store.written == [(5000, {"cpu.thread.0.util": 12.0})]
    snap = live.published[0]
    assert snap["ts"] == 5000
    assert snap["series"] == {"cpu.thread.0.util": 12.0}
    assert snap["procs"][0]["pid"] == 1
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_collectord.py -q`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Zaimplementuj `kokpit/collectord.py`**

```python
import logging
import time

from kokpit import config
from kokpit.host import LocalHost
from kokpit.live import LiveServer
from kokpit.proc import ProcCollector
from kokpit.sources.cpu import CpuSource
from kokpit.sources.disk import DiskSource
from kokpit.sources.gpu import GpuSource
from kokpit.sources.memory import MemorySource
from kokpit.sources.net import NetSource
from kokpit.sources.thermal import ThermalSource
from kokpit.store import Store

log = logging.getLogger("kokpit.collectord")


def build_host() -> LocalHost:
    return LocalHost([
        CpuSource(), MemorySource(), NetSource(),
        DiskSource(), ThermalSource(), GpuSource(),
    ])


def tick(host, store, live, procs, now_ms: int, dt_s: float) -> None:
    series = host.collect(now_ms, dt_s)
    store.write(now_ms, series)
    live.publish({"ts": now_ms, "series": series, "procs": procs.top()})


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    store = Store(config.db_path())
    live = LiveServer(config.socket_path())
    live.start()
    host = build_host()
    procs = ProcCollector()
    period = 1.0 / config.SAMPLE_HZ
    last_mono: float | None = None
    last_rollup = 0.0
    log.info("kokpit-collectord wystartował (db=%s sock=%s)", config.db_path(), config.socket_path())
    try:
        while True:
            start = time.monotonic()
            now_ms = int(time.time() * 1000)
            dt_s = (start - last_mono) if last_mono is not None else 0.0
            last_mono = start
            try:
                tick(host, store, live, procs, now_ms, dt_s)
            except Exception:
                log.exception("tick nieudany")
            if start - last_rollup >= 60.0:
                try:
                    store.rollup_1m(now_ms)
                    store.prune(now_ms)
                    store.checkpoint()
                except Exception:
                    log.exception("rollup/prune/checkpoint nieudany")
                last_rollup = start
            time.sleep(max(0.0, period - (time.monotonic() - start)))
    except KeyboardInterrupt:
        log.info("zatrzymywanie")
    finally:
        live.stop()
        store.close()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Uruchom testy (cały zestaw)**

Run: `.venv/bin/pytest -q`
Expected: PASS (wszystkie testy zielone)

- [ ] **Step 5: Smoke test demona ręcznie (3 sekundy)**

Run:
```bash
timeout 3 .venv/bin/kokpit-collectord ; \
.venv/bin/python -c "import sqlite3,os; from kokpit import config; \
c=sqlite3.connect(str(config.db_path())); \
print('rows:', c.execute('SELECT COUNT(*) FROM sample').fetchone()[0])"
```
Expected: log startu + `rows: N` gdzie N > 0 (próbki zapisane).

- [ ] **Step 6: Commit**

```bash
git add kokpit/collectord.py tests/test_collectord.py
git commit -m "feat(collectord): 1Hz daemon loop, rollup/prune/checkpoint, entrypoint"
```

---

### Task 13: Pakowanie — systemd --user unit + instrukcja

**Files:**
- Create: `packaging/kokpit-collectord.service`, `README.md`

**Interfaces:**
- Produces: unit `systemd --user` uruchamiający `kokpit-collectord` z `.venv`; instrukcja instalacji + `enable-linger`.

- [ ] **Step 1: Napisz `packaging/kokpit-collectord.service`**

```ini
[Unit]
Description=kokpit telemetry collector
After=graphical-session.target

[Service]
Type=simple
ExecStart=%h/Code/kokpit/.venv/bin/kokpit-collectord
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Napisz `README.md` (sekcja uruchomienia)**

````markdown
# kokpit — kolektor telemetrii (backend)

Demon `kokpit-collectord` zbiera CPU/GPU/RAM/dyski/sieć/procesy/temperatury co 1 s
do SQLite (`~/.local/share/kokpit/kokpit.db`) i publikuje żywy snapshot przez
Unix socket (`$XDG_RUNTIME_DIR/kokpit.sock`, NDJSON).

## Instalacja

```bash
cd ~/Code/kokpit
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```

## Autostart (systemd --user)

```bash
mkdir -p ~/.config/systemd/user
cp packaging/kokpit-collectord.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kokpit-collectord
# żeby historia żyła także po wylogowaniu ("co działo się w nocy"):
loginctl enable-linger "$USER"
journalctl --user -u kokpit-collectord -f
```

## Podgląd live (smoke, bez UI)

```bash
.venv/bin/python -c "import socket; s=socket.socket(socket.AF_UNIX); \
s.connect('$XDG_RUNTIME_DIR/kokpit.sock'); \
print(s.makefile().readline())"
```
````

- [ ] **Step 3: Zweryfikuj składnię unitu**

Run: `systemd-analyze --user verify packaging/kokpit-collectord.service ; echo "exit=$?"`
Expected: brak błędów krytycznych (`exit=0`; ostrzeżenie o ścieżce `%h` jest OK).

- [ ] **Step 4: Commit**

```bash
git add packaging/kokpit-collectord.service README.md
git commit -m "chore(packaging): systemd --user unit + README"
```

---

## Self-Review

**1. Spec coverage (Plan 1 = backend; UI = Plan 2):**
- Sources CPU/GPU/RAM/dyski/sieć/procesy/temp → T5–T9 ✓
- Stateful delty bps (K1) → T4 (RateCounter) + T6 (net/disk), testy first-tick/reset/dt ✓
- SQLite long + series_id + 1 tx/tick + WAL/synchronous (K2, S3) → T2 ✓
- Migracje `user_version` (S1) → T2 ✓
- Rollup_1m bucket epoch (S2) + prune + checkpoint-tylko-writer (K2) → T3 ✓
- NDJSON + broadcast + drop wolnego + unlink stale-socket (S4, S5) → T11 ✓
- Izolacja błędów per-source (§7) → T10 ✓
- 0/multi-GPU + n/a (D4, W4) → T8; VRAM per-PID przez NVML (W4) → T9 ✓
- Filtr iface/disk (D3) → T1+T6 ✓
- `nvidia-ml-py` nie `pynvml` (W1) → T1 (dep) + T8 (import) ✓
- `sensors -j` jako podstawa (D2) → T7 ✓
- systemd --user + linger (S6) → T13 ✓
- **Świadomie poza Plan 1:** UI/pyqtgraph (W2 spike, render fps), heatmapa util32/temp24, oś X sliding window, placeholder pustej historii → **Plan 2 (UI)**. `query()` na rollup dla okien historii dołoży Plan 2 (T2 daje `query` na raw; rozszerzenie o rollup w Planie 2).

**2. Placeholder scan:** brak „TBD/TODO/handle edge cases"; każdy krok kodu ma pełny kod i komendę. ✓

**3. Type consistency:** `sample(now_ms, dt_s)` jednolite we wszystkich źródłach i w `host.collect`/`tick`; `Store.write(ts_ms, samples)`, `query(series, since_ms, until_ms)`; snapshot `{"ts","series","procs"}` spójny T11↔T12; `RateCounter.update(value, dt_s)` spójny T4↔T6. ✓

---

## Execution Handoff

(Uzupełnione przy przekazaniu do wykonania.)
