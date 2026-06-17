# Vital-Signs Glyph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hero-widget PySide6 rysujący wielokąt anomalii, gdzie długość ramienia = zaskoczenie metryki względem baseline tej maszyny o tej porze tygodnia (z-score z `rollup_1m`), a dla metryk z twardym limitem `max(z-score, proximity)`.

**Architecture:** Trzy izolowane warstwy. (1) `Store.baseline()` — czysto-SQL agregat z drabiną fallbacku circadian→hour→global. (2) `kokpit/ui/glyph_model.py` — czysty Python (zero Qt): definicje 9 osi, EWMA live, score `max(z,prox)`, worst-of po rodzinie, discovery suffix-match. (3) `kokpit/ui/widgets/vital_glyph.py` — QWidget z `paintEvent` (QPainter) renderujący wielokąt. Wpięcie w `app.py` przez baseline-cache provider.

**Tech Stack:** Python 3.12, PySide6 (Qt6), SQLite (WAL), pytest. Brak nowych zależności.

## Global Constraints

- TDD: test first (RED → GREEN), pełny `.venv/bin/pytest -q` zielony przed każdym commitem (CLAUDE.md §Testy).
- `Store.baseline()` to **czysty dopisek** w klasie `Store`, pod `list_series()` — bez zmian w schemacie, `write()`, `rollup_1m()`, `prune()` (kontrakt store-history-api).
- `glyph_model.py` **nie importuje PySide6** — logika testowalna bez `QApplication`.
- Discovery rodzin serii to **suffix-match**, nie prefix (`disk.` łapie `used_pct`); Disk IO bierze **tylko całe dyski**, bez partycji (spec §2).
- z-score liczony z **EWMA live** (`value_sm`), proximity z **surowej** live (spec §3).
- `BASELINE_MIN_SAMPLES` w `config.py` jest jedynym źródłem prawdy; `Store.baseline(min_samples=None)` go czyta.
- Snapshot jest zagnieżdżony: `{"ts", "series", "procs"}` — glyph_model dostaje `snap["series"]` i `snap["ts"]` osobno (spec §4.2).
- Testy Qt: fixture `qapp` (sesyjny, `QT_QPA_PLATFORM=offscreen`) z `tests/conftest.py`.

---

### Task 1: Stałe konfiguracyjne glifu

**Files:**
- Modify: `kokpit/config.py` (dopisz na końcu)
- Test: `tests/test_config.py` (dopisz)

**Interfaces:**
- Produces: `config.BASELINE_MIN_SAMPLES: int`, `config.FALLBACK_GLOBAL_DAYS: int`, `config.BASELINE_REFRESH_S: float`, `config.Z_FULL: float`, `config.EPS_SIGMA: float`, `config.LIVE_EWMA_S: float`.

- [ ] **Step 1: Write the failing test**

W `tests/test_config.py` dopisz:

```python
def test_glyph_constants_present_and_sane():
    from kokpit import config
    assert config.BASELINE_MIN_SAMPLES == 10
    assert config.FALLBACK_GLOBAL_DAYS == 7
    assert config.BASELINE_REFRESH_S == 60
    assert config.Z_FULL == 3.0
    assert 0 < config.EPS_SIGMA < 1e-6
    assert config.LIVE_EWMA_S == 45.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py::test_glyph_constants_present_and_sane -q`
Expected: FAIL (`AttributeError: module 'kokpit.config' has no attribute 'BASELINE_MIN_SAMPLES'`).

- [ ] **Step 3: Add the constants**

W `kokpit/config.py` dopisz na końcu pliku:

```python
# --- Vital-Signs Glyph (spec 2026-06-18) ---
BASELINE_MIN_SAMPLES = 10      # min bucketów w tierze, by uznać baseline za użyteczny
FALLBACK_GLOBAL_DAYS = 7       # okno tieru 'global'
BASELINE_REFRESH_S = 60.0      # UI recompute baseline nie częściej niż co tyle
Z_FULL = 3.0                   # z-score dający ramię pełnej długości
EPS_SIGMA = 1e-9               # σ poniżej → seria stała, z=0 (guard dzielenia)
LIVE_EWMA_S = 45.0             # okno wygładzania live (licznik z-score, §3)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kokpit/config.py tests/test_config.py
git commit -m "feat(glyph): stałe konfiguracyjne baseline + score"
```

---

### Task 2: `Store.baseline()` — drabina fallbacku circadian→hour→global

**Files:**
- Modify: `kokpit/store.py` (nowa metoda pod `list_series()`, ok. linia 117)
- Test: `tests/test_store.py` (dopisz)

**Interfaces:**
- Consumes: `config.BASELINE_MIN_SAMPLES`, `config.FALLBACK_GLOBAL_DAYS`.
- Produces: `Store.baseline(series: str, now_ms: int, min_samples: int | None = None) -> tuple[float, float, int, str] | None` zwracające `(mean, sigma, n, tier)` gdzie `tier ∈ {"circadian","hour","global"}`, lub `None` gdy żaden tier nie ma `min_samples` bucketów.

- [ ] **Step 1: Write the failing tests**

W `tests/test_store.py` dopisz (na końcu). Helper + 5 testów. UTC wymuszone, by offsety dobowe/tygodniowe deterministycznie zachowywały hour-of-week (bez DST):

```python
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


def _use_utc():
    import os, time
    os.environ["TZ"] = "UTC"
    time.tzset()


DAY = 86_400_000
WEEK = 7 * DAY
BASE = 1_700_000_000_000   # ustalony epoch ms (UTC); now dla wszystkich testów


def test_baseline_circadian_tier(tmp_path):
    _use_utc()
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


def test_baseline_falls_back_to_hour_tier(tmp_path):
    _use_utc()
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


def test_baseline_falls_back_to_global_tier(tmp_path):
    _use_utc()
    s = Store(tmp_path / "k.db")
    # 11 bucketów w obrębie 7d, godzina-doby przesunięta o nieparzyste h → nigdy == BASE hour
    pts = [(BASE - 3_600_000 - k * 7_200_000, 50.0) for k in range(11)]
    _seed_rollup(s, "cpu.loadavg.1", pts)
    _, _, n, tier = s.baseline("cpu.loadavg.1", BASE)
    assert tier == "global"        # circadian=0, hour=0, global=11>=10
    assert n == 11
    s.close()


def test_baseline_none_when_insufficient(tmp_path):
    _use_utc()
    s = Store(tmp_path / "k.db")
    _seed_rollup(s, "cpu.loadavg.1", [(BASE, 50.0), (BASE - WEEK, 51.0)])  # tylko 2
    assert s.baseline("cpu.loadavg.1", BASE) is None
    assert s.baseline("never.seen.series", BASE) is None                   # brak serii
    s.close()


def test_baseline_constant_series_sigma_zero(tmp_path):
    _use_utc()
    s = Store(tmp_path / "k.db")
    _seed_rollup(s, "thermal.coretemp.0.pkg", [(BASE - k * WEEK, 95.0) for k in range(12)])
    mean, sigma, n, tier = s.baseline("thermal.coretemp.0.pkg", BASE)
    assert mean == 95.0
    assert sigma == 0.0            # konsument (glyph) zrobi guard EPS → z=0, proximity ratuje
    assert tier == "circadian"
    s.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_store.py -k baseline -q`
Expected: FAIL (`AttributeError: 'Store' object has no attribute 'baseline'`).

- [ ] **Step 3: Implement `Store.baseline()`**

W `kokpit/store.py` dodaj `import` configu (już jest: `from kokpit import config`) i wstaw metodę **pod** `list_series()` (po linii 117), przed `# --- dopisz w klasie Store, pod query() ---`:

```python
    def baseline(self, series: str, now_ms: int, min_samples: int | None = None):
        """(mean, sigma, n, tier) baseline serii z rollup_1m, albo None.

        Drabina fallbacku — pierwszy tier z n >= min_samples wygrywa:
          'circadian' — buckety o tej samej godzinie-tygodnia co now_ms (cały rollup),
          'hour'      — ta sama godzina doby, dowolny dzień,
          'global'    — dowolna pora, ostatnie FALLBACK_GLOBAL_DAYS dni.
        sigma między-minutowa (z vavg) — konsument dopasowuje granularność (spec §3).
        strftime 'localtime' → strefa hosta (known-limitation: DST, spec §4.1).
        """
        if min_samples is None:
            min_samples = config.BASELINE_MIN_SAMPLES
        row = self.conn.execute("SELECT id FROM series_dict WHERE name=?", (series,)).fetchone()
        if row is None:
            return None
        sid = row[0]
        how = ("(CAST(strftime('%w', bucket/1000,'unixepoch','localtime') AS INT)*24"
               " + CAST(strftime('%H', bucket/1000,'unixepoch','localtime') AS INT))")
        how_now = ("(CAST(strftime('%w', ?/1000,'unixepoch','localtime') AS INT)*24"
                   " + CAST(strftime('%H', ?/1000,'unixepoch','localtime') AS INT))")
        hod = "CAST(strftime('%H', bucket/1000,'unixepoch','localtime') AS INT)"
        hod_now = "CAST(strftime('%H', ?/1000,'unixepoch','localtime') AS INT)"
        global_since = now_ms - config.FALLBACK_GLOBAL_DAYS * 86_400_000
        tiers = (
            ("circadian", f"series_id=? AND {how} = {how_now}", (sid, now_ms, now_ms)),
            ("hour",      f"series_id=? AND {hod} = {hod_now}", (sid, now_ms, now_ms)),
            ("global",    "series_id=? AND bucket >= ?",         (sid, global_since)),
        )
        for tier, where, params in tiers:
            n, mean, e2 = self.conn.execute(
                f"SELECT COUNT(*), AVG(vavg), AVG(vavg*vavg) FROM rollup_1m WHERE {where}",
                params,
            ).fetchone()
            if n >= min_samples:
                var = max(0.0, e2 - mean * mean)
                return (float(mean), var ** 0.5, int(n), tier)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_store.py -q`
Expected: PASS (wszystkie, w tym istniejące).

- [ ] **Step 5: Commit**

```bash
git add kokpit/store.py tests/test_store.py
git commit -m "feat(store): baseline() z drabiną fallbacku circadian/hour/global"
```

---

### Task 3: `glyph_model` — score `max(z,prox)`, guard σ≈0, EWMA

**Files:**
- Create: `kokpit/ui/glyph_model.py`
- Test: `tests/test_glyph_model.py`

**Interfaces:**
- Consumes: `config.Z_FULL`, `config.EPS_SIGMA`, `config.LIVE_EWMA_S`; baseline jako krotka `(mean, sigma, n, tier) | None`.
- Produces:
  - `clamp01(x: float) -> float`
  - `z_norm(value_sm: float, baseline: tuple | None) -> float` (ujemne z → 0; σ<EPS → 0; baseline None → 0)
  - `spike_score(value_sm: float, baseline: tuple | None, proximity: float | None) -> float` = `max(z_norm, clamp01(proximity))`
  - `ewma_alpha() -> float` i `ewma(prev: float | None, x: float, alpha: float) -> float`

- [ ] **Step 1: Write the failing tests**

Utwórz `tests/test_glyph_model.py`:

```python
import math
from kokpit import config
from kokpit.ui import glyph_model as gm


def test_z_norm_positive_deviation():
    # mean=50, sigma=10 → value_sm=80 to +3σ = pełne ramię (Z_FULL=3)
    assert gm.z_norm(80.0, (50.0, 10.0, 12, "circadian")) == 1.0
    assert abs(gm.z_norm(65.0, (50.0, 10.0, 12, "circadian")) - 0.5) < 1e-9  # +1.5σ → 0.5


def test_z_norm_negative_deviation_clamped_to_zero():
    assert gm.z_norm(20.0, (50.0, 10.0, 12, "circadian")) == 0.0   # poniżej baseline = spokój


def test_z_norm_sigma_zero_is_calm():
    assert gm.z_norm(95.0, (95.0, 0.0, 12, "circadian")) == 0.0    # seria stała → brak zaskoczenia


def test_z_norm_none_baseline_is_zero():
    assert gm.z_norm(999.0, None) == 0.0


def test_spike_score_takes_max_of_z_and_proximity():
    # σ≈0 (z=0) ale proximity 0.95 → kolec z proximity (maszyna zawsze gorąca)
    assert gm.spike_score(95.0, (95.0, 0.0, 12, "circadian"), 0.95) == 0.95
    # z duże, proximity małe → z wygrywa
    assert gm.spike_score(80.0, (50.0, 10.0, 12, "circadian"), 0.1) == 1.0
    # proximity None (oś bez limitu) → sam z
    assert gm.spike_score(65.0, (50.0, 10.0, 12, "circadian"), None) == 0.5


def test_proximity_clamped():
    assert gm.spike_score(0.0, None, 1.5) == 1.0   # proximity > 1 → 1


def test_ewma_smooths_between_prev_and_new():
    a = gm.ewma_alpha()
    assert 0.0 < a < 1.0
    assert gm.ewma(None, 10.0, a) == 10.0          # brak stanu → wartość wprost
    sm = gm.ewma(10.0, 20.0, a)
    assert 10.0 < sm < 20.0                          # między starym a nowym
    assert abs(sm - (10.0 + a * 10.0)) < 1e-9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_glyph_model.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'kokpit.ui.glyph_model'`).

- [ ] **Step 3: Implement the pure score core**

Utwórz `kokpit/ui/glyph_model.py`:

```python
"""Czysta logika Vital-Signs Glyph — BEZ importu Qt (testowalne bez QApplication).

z-score liczony z wygładzonej (EWMA) live, proximity z surowej. Score osi =
max(worst-of z-score po członkach rodziny, proximity). Spec 2026-06-18.
"""
import math

from kokpit import config


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def z_norm(value_sm: float, baseline) -> float:
    """Znormalizowany z-score (0..1). Tylko odchylenia w GÓRĘ (ujemne → 0).
    baseline = (mean, sigma, n, tier) lub None. σ<EPS → 0 (seria stała)."""
    if baseline is None:
        return 0.0
    mean, sigma, _n, _tier = baseline
    if sigma < config.EPS_SIGMA:
        return 0.0
    return clamp01((value_sm - mean) / sigma / config.Z_FULL)


def spike_score(value_sm: float, baseline, proximity) -> float:
    """Długość ramienia 0..1 = max(z-score, proximity). proximity None/0 dla osi
    bez twardego limitu."""
    pp = 0.0 if proximity is None else clamp01(proximity)
    return max(z_norm(value_sm, baseline), pp)


def ewma_alpha() -> float:
    """α dla EWMA przy próbkowaniu 1 Hz i oknie LIVE_EWMA_S (half-life ≈ okno)."""
    return 1.0 - math.exp(-1.0 / config.LIVE_EWMA_S)


def ewma(prev, x: float, alpha: float) -> float:
    return x if prev is None else prev + alpha * (x - prev)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_glyph_model.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/glyph_model.py tests/test_glyph_model.py
git commit -m "feat(glyph): pure score core (z-score, proximity, EWMA)"
```

---

### Task 4: `glyph_model` — discovery rodzin (suffix-match, bez partycji)

**Files:**
- Modify: `kokpit/ui/glyph_model.py`
- Test: `tests/test_glyph_model.py` (dopisz)

**Interfaces:**
- Produces:
  - `disk_io_members(keys: list[str]) -> list[str]` — serie `disk.<dev>.{read,write}_bps` tylko dla CAŁYCH dysków (bez partycji, bez `used_pct`).
  - `gpu_vram_ratio(series: dict) -> float | None` — max `vram_used/vram_total` po GPU.
  - `max_temp_ratio(series: dict, pred, limit: float) -> float | None` — max `value/limit` po seriach spełniających `pred`.
  - `ratio(series: dict, num_key: str, den_key: str) -> float | None`.

- [ ] **Step 1: Write the failing tests**

W `tests/test_glyph_model.py` dopisz:

```python
def test_disk_io_members_excludes_used_pct_and_partitions():
    keys = [
        "disk.nvme0n1.read_bps", "disk.nvme0n1.write_bps",   # cały dysk → IN
        "disk.nvme0n1p1.read_bps", "disk.nvme0n1p2.write_bps",  # partycje → OUT
        "disk.sda.read_bps", "disk.sda1.read_bps",           # sda IN, sda1 OUT
        "disk.root.used_pct", "disk.home.used_pct",          # used_pct → OUT
    ]
    assert sorted(gm.disk_io_members(keys)) == [
        "disk.nvme0n1.read_bps", "disk.nvme0n1.write_bps", "disk.sda.read_bps",
    ]


def test_ratio_handles_missing_and_zero():
    assert gm.ratio({"mem.used": 50.0, "mem.total": 200.0}, "mem.used", "mem.total") == 0.25
    assert gm.ratio({"mem.used": 50.0}, "mem.used", "mem.total") is None   # brak total
    assert gm.ratio({"mem.used": 50.0, "mem.total": 0.0}, "mem.used", "mem.total") is None


def test_gpu_vram_ratio_takes_worst_gpu():
    s = {"gpu.0.vram_used": 4.0, "gpu.0.vram_total": 8.0,
         "gpu.1.vram_used": 7.0, "gpu.1.vram_total": 8.0}
    assert gm.gpu_vram_ratio(s) == 0.875        # gpu.1 = 7/8
    assert gm.gpu_vram_ratio({"gpu.0.vram_used": 1.0}) is None   # brak total


def test_max_temp_ratio():
    s = {"thermal.coretemp.0.pkg": 76.0, "thermal.coretemp.1.pkg": 95.0,
         "cpu.thread.0.util": 10.0}
    pred = lambda k: k.startswith("thermal.coretemp.") and k.endswith(".pkg")
    assert gm.max_temp_ratio(s, pred, 95.0) == 1.0     # 95/95
    assert gm.max_temp_ratio({"x": 1.0}, pred, 95.0) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_glyph_model.py -k "disk_io or ratio or vram or temp" -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'disk_io_members'`).

- [ ] **Step 3: Implement discovery helpers**

W `kokpit/ui/glyph_model.py` dodaj na górze `import re` (obok `import math`) i dopisz:

```python
# Partycja: nvme0n1p3 / mmcblk0p2 / sda1 / vdb2. Cały dysk (nvme0n1, sda) → NIE.
_PARTITION_RE = re.compile(r"(nvme\d+n\d+p\d+|mmcblk\d+p\d+|(sd|vd|hd)[a-z]+\d+)$")
_DISK_IO_SUFFIXES = (".read_bps", ".write_bps")


def disk_io_members(keys) -> list:
    out = []
    for k in keys:
        if not k.startswith("disk.") or not k.endswith(_DISK_IO_SUFFIXES):
            continue
        dev = k.split(".", 1)[1].rsplit(".", 1)[0]   # "disk.<dev>.read_bps" → "<dev>"
        if _PARTITION_RE.search(dev):
            continue
        out.append(k)
    return out


def ratio(series: dict, num_key: str, den_key: str):
    num, den = series.get(num_key), series.get(den_key)
    if num is None or not den:        # brak licznika / mianownik None lub 0
        return None
    return num / den


def gpu_vram_ratio(series: dict):
    used = {k[:-len("_used")]: v for k, v in series.items() if k.endswith(".vram_used")}
    best = None
    for base, u in used.items():
        total = series.get(base + "_total")
        if total:
            r = u / total
            best = r if best is None else max(best, r)
    return best


def max_temp_ratio(series: dict, pred, limit: float):
    vals = [v / limit for k, v in series.items() if pred(k) and v is not None]
    return max(vals) if vals else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_glyph_model.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/glyph_model.py tests/test_glyph_model.py
git commit -m "feat(glyph): discovery rodzin (suffix-match, bez partycji/used_pct)"
```

---

### Task 5: `glyph_model` — definicje 9 osi + `GlyphModel.update()`

**Files:**
- Modify: `kokpit/ui/glyph_model.py`
- Test: `tests/test_glyph_model.py` (dopisz)

**Interfaces:**
- Consumes: helpery z Task 3/4, baseline-provider `Callable[[str], tuple | None]`.
- Produces:
  - `SpokeScore` (dataclass): `name: str`, `score: float`, `value: float | None`, `tier: str | None`.
  - `SPOKE_NAMES: list[str]` — 9 nazw w kolejności rysowania.
  - `GlyphModel` z metodą `update(series: dict, now_ms: int, provider) -> list[SpokeScore]` (kolejność = `SPOKE_NAMES`) i property `calibrating: bool` (True gdy żadna oś nie miała baseline).

- [ ] **Step 1: Write the failing tests**

W `tests/test_glyph_model.py` dopisz:

```python
def _const_provider(table):
    return lambda series: table.get(series)


def test_update_returns_nine_spokes_in_order():
    m = gm.GlyphModel()
    spokes = m.update({}, 1_700_000_000_000, _const_provider({}))
    assert [s.name for s in spokes] == gm.SPOKE_NAMES
    assert len(spokes) == 9


def test_update_cpu_uses_zscore_from_loadavg():
    m = gm.GlyphModel()
    prov = _const_provider({"cpu.loadavg.1": (2.0, 1.0, 12, "circadian")})
    # EWMA: pierwsza próbka = wartość wprost, więc value_sm=5.0 → z=(5-2)/1/3=1.0
    spokes = {s.name: s for s in m.update({"cpu.loadavg.1": 5.0}, 1_700_000_000_000, prov)}
    assert spokes["CPU"].score == 1.0
    assert spokes["CPU"].tier == "circadian"


def test_update_ram_proximity_without_baseline():
    m = gm.GlyphModel()
    series = {"mem.used": 95.0, "mem.total": 100.0}      # 95% pełne
    spokes = {s.name: s for s in m.update(series, 1_700_000_000_000, _const_provider({}))}
    assert spokes["RAM"].score == 0.95                    # proximity ratuje brak baseline
    assert spokes["RAM"].tier is None


def test_update_disk_worst_of_family():
    m = gm.GlyphModel()
    prov = _const_provider({
        "disk.nvme0n1.read_bps": (100.0, 10.0, 12, "circadian"),   # spokojny
        "disk.sda.read_bps":     (10.0, 5.0, 12, "circadian"),     # value 40 → z=(40-10)/5/3=2 → 1.0
    })
    series = {"disk.nvme0n1.read_bps": 100.0, "disk.sda.read_bps": 40.0,
              "disk.root.used_pct": 80.0}                  # used_pct NIE w rodzinie IO
    spokes = {s.name: s for s in m.update(series, 1_700_000_000_000, prov)}
    assert spokes["Disk IO"].score == 1.0                  # worst-of = sda


def test_update_cold_start_calibrating_flag():
    m = gm.GlyphModel()
    m.update({"cpu.loadavg.1": 1.0}, 1_700_000_000_000, _const_provider({}))  # provider zawsze None
    assert m.calibrating is True


def test_update_not_calibrating_when_any_baseline():
    m = gm.GlyphModel()
    prov = _const_provider({"cpu.loadavg.1": (2.0, 1.0, 12, "global")})
    m.update({"cpu.loadavg.1": 5.0}, 1_700_000_000_000, prov)
    assert m.calibrating is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_glyph_model.py -k update -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'GlyphModel'`).

- [ ] **Step 3: Implement spoke table + GlyphModel**

W `kokpit/ui/glyph_model.py` dopisz na górze `from dataclasses import dataclass` i `from typing import Callable, Optional`, dodaj limity oraz na końcu pliku tabelę i klasę:

```python
CPU_TEMP_LIMIT = 95.0
GPU_TEMP_LIMIT = 90.0


@dataclass
class SpokeScore:
    name: str
    score: float
    value: Optional[float]
    tier: Optional[str]


def _members_suffix(prefix: str, suffix: str):
    return lambda keys: [k for k in keys if k.startswith(prefix) and k.endswith(suffix)]


def _coretemp_pkg(k: str) -> bool:
    return k.startswith("thermal.coretemp.") and k.endswith(".pkg")


def _gpu_temp(k: str) -> bool:
    return k.startswith("gpu.") and k.endswith(".temp")


# (nazwa, z_members(keys)->list, proximity(series)->float|None)
_SPOKES = (
    ("CPU",      lambda keys: [k for k in keys if k == "cpu.loadavg.1"], lambda s: None),
    ("RAM",      lambda keys: [k for k in keys if k == "mem.used"],
                 lambda s: ratio(s, "mem.used", "mem.total")),
    ("Swap",     lambda keys: [k for k in keys if k == "swap.used"], lambda s: None),
    ("GPU",      _members_suffix("gpu.", ".util"), lambda s: None),
    ("VRAM",     _members_suffix("gpu.", ".vram_used"), lambda s: gpu_vram_ratio(s)),
    ("CPU temp", lambda keys: [k for k in keys if _coretemp_pkg(k)],
                 lambda s: max_temp_ratio(s, _coretemp_pkg, CPU_TEMP_LIMIT)),
    ("GPU temp", lambda keys: [k for k in keys if _gpu_temp(k)],
                 lambda s: max_temp_ratio(s, _gpu_temp, GPU_TEMP_LIMIT)),
    ("Disk IO",  lambda keys: disk_io_members(keys), lambda s: None),
    ("Net IO",   _members_suffix("net.", ".rx_bps") if False else
                 (lambda keys: [k for k in keys
                                if k.startswith("net.") and k.endswith((".rx_bps", ".tx_bps"))]),
                 lambda s: None),
)

SPOKE_NAMES = [name for name, _z, _p in _SPOKES]


class GlyphModel:
    """Stanowy (EWMA per-seria) builder ramion glifu. Zero Qt."""

    def __init__(self) -> None:
        self._sm: dict = {}                 # seria → wygładzona live
        self._alpha = ewma_alpha()
        self.calibrating = True

    def update(self, series: dict, now_ms: int, provider) -> list:
        keys = list(series.keys())
        any_baseline = False
        spokes = []
        for name, z_members, proximity in _SPOKES:
            best_z = 0.0
            best_val = None
            best_tier = None
            for m in z_members(keys):
                v = series.get(m)
                if v is None:
                    continue
                self._sm[m] = ewma(self._sm.get(m), v, self._alpha)
                base = provider(m)
                if base is not None:
                    any_baseline = True
                z = z_norm(self._sm[m], base)
                if z >= best_z or best_val is None:
                    best_z, best_val = z, v
                    best_tier = base[3] if base is not None else best_tier
            prox = proximity(series)
            score = max(best_z, 0.0 if prox is None else clamp01(prox))
            spokes.append(SpokeScore(name=name, score=score, value=best_val, tier=best_tier))
        self.calibrating = not any_baseline
        return spokes
```

Uwaga: linia `_members_suffix("net.", ".rx_bps") if False else (...)` to jawny inline — Net IO matchuje OBA suffiksy `.rx_bps`/`.tx_bps`, więc nie da się użyć jednosufiksowego helpera. (Zostawione czytelnie; przy refaktorze można dodać `_members_suffixes` z krotką.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_glyph_model.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/glyph_model.py tests/test_glyph_model.py
git commit -m "feat(glyph): 9 osi + GlyphModel.update (worst-of, EWMA, calibrating)"
```

---

### Task 6: `VitalGlyph` widget — render wielokąta (QPainter)

**Files:**
- Create: `kokpit/ui/widgets/vital_glyph.py`
- Test: `tests/test_vital_glyph.py`

**Interfaces:**
- Consumes: `SpokeScore` (Task 5), `palette.util_rgb`.
- Produces: `VitalGlyph(QtWidgets.QWidget)` z `set_spokes(spokes: list[SpokeScore], calibrating: bool) -> None` i (na potrzeby testu geometrii) metodą `vertex_radius(score: float) -> float`. Stałe: `R_BASE`, `R_SPAN`, `GLOW_THRESHOLD = 0.5`.

- [ ] **Step 1: Write the failing tests**

Utwórz `tests/test_vital_glyph.py`:

```python
from kokpit.ui.glyph_model import SpokeScore, SPOKE_NAMES


def test_vertex_radius_monotonic():
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    assert w.vertex_radius(0.0) == VitalGlyph.R_BASE
    assert w.vertex_radius(1.0) == VitalGlyph.R_BASE + VitalGlyph.R_SPAN
    assert w.vertex_radius(0.0) < w.vertex_radius(0.5) < w.vertex_radius(1.0)


def test_set_spokes_renders_without_crash(qapp):
    from PySide6 import QtGui
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    w.resize(300, 300)
    calm = [SpokeScore(n, 0.0, 0.0, "circadian") for n in SPOKE_NAMES]
    w.set_spokes(calm, calibrating=False)
    img = QtGui.QImage(300, 300, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    w.render(img)                 # paintEvent nie rzuca
    assert img.width() == 300


def test_set_spokes_cold_start_proximity_only(qapp):
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    # cold-start: 4 osie z limitem na proximity, 5 z-only na 0
    spokes = []
    for n in SPOKE_NAMES:
        score = 0.6 if n in ("RAM", "VRAM", "CPU temp", "GPU temp") else 0.0
        spokes.append(SpokeScore(n, score, None, None))
    w.set_spokes(spokes, calibrating=True)
    active = [s for s in w.current_spokes() if s.score > 0]
    assert {s.name for s in active} == {"RAM", "VRAM", "CPU temp", "GPU temp"}


def test_set_spokes_spiked_geometry(qapp):
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    spokes = [SpokeScore(n, (1.0 if n == "CPU temp" else 0.0), None, "circadian")
              for n in SPOKE_NAMES]
    w.set_spokes(spokes, calibrating=False)
    radii = [w.vertex_radius(s.score) for s in w.current_spokes()]
    assert max(radii) == w.vertex_radius(1.0)          # CPU temp wydłużone
    assert radii.count(VitalGlyph.R_BASE) == 8         # reszta spokojna
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_vital_glyph.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'kokpit.ui.widgets.vital_glyph'`).

- [ ] **Step 3: Implement the widget**

Utwórz `kokpit/ui/widgets/vital_glyph.py`:

```python
import math

from PySide6 import QtCore, QtGui, QtWidgets

from kokpit.ui.glyph_model import SpokeScore
from kokpit.ui.theme.palette import DIM_FG, util_rgb

GLOW_THRESHOLD = 0.5


class VitalGlyph(QtWidgets.QWidget):
    """Wielokąt anomalii: promień wierzchołka = R_BASE + score*R_SPAN.
    Spokojny = regularny wielokąt; kolec = wydłużone ramię (spec §4.3)."""

    R_BASE = 40.0
    R_SPAN = 90.0

    def __init__(self) -> None:
        super().__init__()
        self._spokes: list = []
        self._calibrating = True
        self.setMinimumSize(220, 220)

    def vertex_radius(self, score: float) -> float:
        return self.R_BASE + self.R_SPAN * max(0.0, min(1.0, score))

    def current_spokes(self) -> list:
        return self._spokes

    def set_spokes(self, spokes, calibrating: bool) -> None:
        self._spokes = list(spokes)
        self._calibrating = calibrating
        self.update()   # zażądaj repaint

    def _vertex(self, cx: float, cy: float, i: int, n: int, r: float):
        ang = -math.pi / 2 + 2 * math.pi * i / n     # start u góry, zgodnie z zegarem
        return QtCore.QPointF(cx + r * math.cos(ang), cy + r * math.sin(ang))

    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        n = len(self._spokes)
        if n == 0:
            p.end()
            return
        # baseline ring (spokojny wielokąt referencyjny)
        ref = QtGui.QPolygonF([self._vertex(cx, cy, i, n, self.R_BASE) for i in range(n)])
        pen = QtGui.QPen(QtGui.QColor(DIM_FG))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPolygon(ref)
        # glif: wypełniony wielokąt z wierzchołkami wg score
        poly = QtGui.QPolygonF(
            [self._vertex(cx, cy, i, n, self.vertex_radius(s.score)) for i, s in enumerate(self._spokes)]
        )
        peak = max((s.score for s in self._spokes), default=0.0)
        r, g, b = util_rgb(peak)
        fill = QtGui.QColor(r, g, b, 70 if not self._calibrating else 35)
        edge = QtGui.QColor(r, g, b)
        p.setBrush(QtGui.QBrush(fill))
        p.setPen(QtGui.QPen(edge, 2.0))
        p.drawPolygon(poly)
        # glow per-ramię: drugi, grubszy/półprzezroczysty obrys wierzchołków > próg
        for i, s in enumerate(self._spokes):
            if s.score >= GLOW_THRESHOLD:
                gr, gg, gb = util_rgb(s.score)
                p.setPen(QtGui.QPen(QtGui.QColor(gr, gg, gb, 120), 6.0))
                v = self._vertex(cx, cy, i, n, self.vertex_radius(s.score))
                p.drawEllipse(v, 4.0, 4.0)
        # centrum: skalar zdrowia + stan kalibracji
        p.setPen(QtGui.QPen(QtGui.QColor(edge)))
        f = p.font()
        f.setPointSize(20)
        f.setBold(True)
        p.setFont(f)
        label = "··" if self._calibrating else f"{int(round(peak * 100))}"
        p.drawText(self.rect(), QtCore.Qt.AlignCenter, label)
        p.end()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_vital_glyph.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/widgets/vital_glyph.py tests/test_vital_glyph.py
git commit -m "feat(glyph): VitalGlyph widget (paintEvent, baseline ring, per-ramię glow)"
```

---

### Task 7: Wpięcie w `app.py` — baseline cache + live wiring

**Files:**
- Modify: `kokpit/ui/app.py`
- Modify: `kokpit/ui/history_model.py` (publiczny dostęp do Store)
- Test: `tests/test_glyph_model.py` (dopisz test cache; cache to czysta logika)

**Interfaces:**
- Consumes: `Store.baseline` (Task 2), `GlyphModel` (Task 5), `VitalGlyph` (Task 6), `config.BASELINE_REFRESH_S`.
- Produces: `BaselineCache(store, now_fn)` z `get(series: str) -> tuple | None` (recompute nie częściej niż `BASELINE_REFRESH_S`). `MainWindow` rysuje glif w `_on_snapshot`.

- [ ] **Step 1: Write the failing test for the cache**

W `tests/test_glyph_model.py` dopisz (cache nie importuje Qt — testowalny wprost):

```python
def test_baseline_cache_throttles_recompute():
    from kokpit.ui.glyph_model import BaselineCache

    class FakeStore:
        def __init__(self):
            self.calls = 0
        def baseline(self, series, now_ms):
            self.calls += 1
            return (1.0, 1.0, 12, "global")

    clock = {"t": 1_700_000_000_000}
    store = FakeStore()
    cache = BaselineCache(store, now_fn=lambda: clock["t"])
    assert cache.get("cpu.loadavg.1") == (1.0, 1.0, 12, "global")
    cache.get("cpu.loadavg.1")                 # ten sam czas → z cache
    assert store.calls == 1
    clock["t"] += int(config.BASELINE_REFRESH_S * 1000) + 1   # po oknie
    cache.get("cpu.loadavg.1")
    assert store.calls == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_glyph_model.py::test_baseline_cache_throttles_recompute -q`
Expected: FAIL (`ImportError: cannot import name 'BaselineCache'`).

- [ ] **Step 3: Implement `BaselineCache` in glyph_model**

W `kokpit/ui/glyph_model.py` dopisz na końcu:

```python
class BaselineCache:
    """Throttluje Store.baseline() — recompute per-seria nie częściej niż
    BASELINE_REFRESH_S. Zwraca (mean,σ,n,tier)|None. Bez Qt."""

    def __init__(self, store, now_fn) -> None:
        self._store = store
        self._now = now_fn
        self._cache: dict = {}     # series → (ts_ms, value)

    def get(self, series: str):
        now = self._now()
        hit = self._cache.get(series)
        if hit is not None and now - hit[0] < config.BASELINE_REFRESH_S * 1000:
            return hit[1]
        try:
            val = self._store.baseline(series, now)
        except Exception:
            val = hit[1] if hit is not None else None   # DB error → ostatnia znana / None
        self._cache[series] = (now, val)
        return val
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_glyph_model.py -q`
Expected: PASS.

- [ ] **Step 5: Wire the glyph into `MainWindow`**

W `kokpit/ui/app.py`:

(a) Dopisz importy (obok istniejących `from kokpit.ui...`):

```python
from kokpit.ui.glyph_model import BaselineCache, GlyphModel
from kokpit.ui.widgets.vital_glyph import VitalGlyph
```

(b) W `MainWindow.__init__`, po `self._procs = ProcTable()` (linia 66), dodaj:

```python
        self._glyph = VitalGlyph()
        self._glyph_model = GlyphModel()
        self._baseline = BaselineCache(model.store, now_fn=_now_ms)
```

Zależność: `BaselineCache` woła `model.store.baseline(...)`, ale `HistoryModel` trzyma Store prywatnie (`self._store`). Dodaj publiczną property w `kokpit/ui/history_model.py` — po `def __init__` (linia 14-15), wewnątrz klasy:

```python
    @property
    def store(self):
        return self._store
```

(c) Dodaj glif do gridu — po `grid.addWidget(self._procs, 2, 2, 1, 2)` (linia 102) dopisz nową kolumnę po prawej:

```python
        grid.addWidget(self._glyph, 0, 4, 3, 2)   # hero po prawej, 3 wiersze × 2 kol
```

(d) W `_on_snapshot`, po `self._hist.on_snapshot(snap)` (linia 155) dopisz:

```python
        spokes = self._glyph_model.update(s, snap.get("ts", _now_ms()), self._baseline.get)
        self._glyph.set_spokes(spokes, self._glyph_model.calibrating)
```

(e) Poszerz okno, by hero-kolumna się zmieściła — zmień `win.resize(1500, 950)` (linia 174) na:

```python
    win.resize(1900, 950)
```

- [ ] **Step 6: Run full suite + manual smoke**

Run: `.venv/bin/pytest -q`
Expected: PASS (cały zestaw).

Manualny smoke (jeśli demon kokpit działa i socket żyje):
Run: `QT_QPA_PLATFORM=xcb .venv/bin/python -m kokpit.ui.app`
Expected: okno startuje, po prawej widoczny glif (na świeżej bazie: centrum `··`, ~4 ramiona na proximity). Brak crasha gdy demon nie żyje (glif DIM/calibrating).

- [ ] **Step 7: Commit**

```bash
git add kokpit/ui/app.py kokpit/ui/history_model.py kokpit/ui/glyph_model.py tests/test_glyph_model.py
git commit -m "feat(glyph): wpięcie VitalGlyph w MainWindow (baseline cache, live wiring)"
```

---

## Self-Review

**1. Spec coverage:**
- §1 cel → Task 6 (render wielokąta). ✓
- §2 osie (9, suffix-match, disk bez partycji, CPU loadavg) → Task 4 (`disk_io_members`), Task 5 (`_SPOKES`). ✓
- §3 score (z_norm, max(z,prox), guard σ≈0, ujemny z→0, EWMA na z / proximity z surowej) → Task 3. ✓
- §4.1 baseline drabina → Task 2. ✓
- §4.2 glyph_model + `snap["series"]`/`snap["ts"]` → Task 5 + Task 7(d). ✓
- §4.3 widget (util_rgb nie alert_color, glow per-ramię, baseline ring, centrum/tier) → Task 6. ✓
- §4.4 wpięcie app.py → Task 7. ✓
- §5 data flow (live 1Hz × cache 60s) → Task 7 (`BaselineCache`). ✓
- §6 degradacja/cold-start (calibrating, 4 osie proximity) → Task 5 (`calibrating`), Task 6 (test cold-start). ✓
- §7 testy (fallback first-class, DST, EWMA, used_pct/partycje, geometria) → Task 2/3/4/5/6. **Uwaga:** test DST z §7 NIE jest osobnym krokiem — UTC-deterministyczne testy w Task 2 dokumentują zachowanie 'localtime'; jawny test granicy DST pominięty świadomie (flaky, zależny od tz CI). Known-limitation pozostaje w specu §4.1.
- §9 stałe → Task 1 (config) + Task 5 (limity w glyph_model). ✓

**2. Placeholder scan:** Brak TBD/TODO/„handle errors"; każdy krok ma pełny kod i komendę.

**3. Type consistency:** `baseline` zwraca `(mean,σ,n,tier)` wszędzie (Task 2 produce → Task 3 `z_norm` rozpakowuje 4 pola → Task 7 cache przekazuje krotkę). `SpokeScore(name,score,value,tier)` spójne Task 5↔6. `GlyphModel.update(series, now_ms, provider)` i `.calibrating` spójne Task 5↔7. `set_spokes(spokes, calibrating)` spójne Task 6↔7.

**Rozwiązane ryzyko:** `HistoryModel` trzyma Store jako `self._store` (prywatne) — Task 7 krok 5(b) dodaje publiczną property `store` zamiast sięgać po `_store`.
