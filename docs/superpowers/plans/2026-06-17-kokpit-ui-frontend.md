# kokpit — UI / Frontend — Implementation Plan (Plan 2/2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zbudować natywne okno `kokpit` (PySide6 + pyqtgraph) — konsumenta demona-kolektora: bento NOC grid (neon), metryki live z Unix socketu i historia z SQLite z trybem „follow now".

**Architecture:** Dwa rozłączne pody danych. `live_client` (QObject) czyta NDJSON z socketu w wątku tła i emituje `QtCore.Signal(dict)` do widgetów (marshaling do wątku GUI). `history_model` robi krótkie read-tx do SQLite, wybierając raw (`query`) dla okna ≤1h lub rollup (`query_rollup`) dla 6h/24h/7d. Widgety są cienkie; cała logika (framing NDJSON, selektor okna, konwersje jednostek, mapowanie heatmapy, follow-mode) jest w czystych funkcjach testowanych bez Qt.

**Tech Stack:** Python 3.12, PySide6 (Qt6), pyqtgraph, pytest (`QT_QPA_PLATFORM=offscreen` dla smoke).

**Spec:** `docs/superpowers/specs/2026-06-17-kokpit-ui-frontend-design.md` (+ główny `2026-06-17-kokpit-design.md`).
**Kontrakt store (dostarcza sesja backendowa):** `docs/superpowers/specs/2026-06-17-store-history-api-contract.md` — `Store.query_rollup(series, since_ms, until_ms) -> [(bucket_ms, vmin, vmax, vavg, vlast)]`, `Store.list_series(prefix=None) -> [str]`. **Plan 2 nie jest tym zablokowany:** `HistoryModel` jest duck-typed na te metody i testowany przeciw fake-store; realne `Store` podpinamy w T9.

## Global Constraints

- Python `>=3.12`; deps UI: `PySide6>=6.7`, `pyqtgraph>=0.13` (optional-dep `ui` w `pyproject.toml`); dev: `pytest>=8.0`.
- **Nie ruszamy backendu** (`kokpit/{store,live,proc,collectord,host,sources}.py`) — UI to czysty konsument. Cały nowy kod pod `kokpit/ui/`, `bench/`, `packaging/`, `tests/`.
- **Timestampy backendu są w ms epoch.** pyqtgraph `DateAxisItem` chce **sekund** → każdy X dzielony przez `1000.0` przed `setData`.
- **`proc.rss`/`proc.vram` są w bajtach** → konwersja `/1024**2` do MB po stronie UI.
- **Odczyt serii zawsze defensywny:** `snapshot["series"].get(name)` z obsługą `None` — nigdy indeksowanie (pierwszy tick pomija `*_bps`; skip ticku; n/a GPU).
- **Thread→GUI tylko przez `QtCore.Signal`** — zakaz wołania widgetów z wątku socketu.
- Estetyka natywnie (QSS + styling pyqtgraph). `/frontend-design` wyłączony (skill webowy).
- Próbkowanie danych 1 Hz; budżet renderu ~10–15 fps (nie 60).
- Po każdym tasku: testy zielone + commit.

## File Structure

```
kokpit/ui/
  __init__.py            # T1
  live_client.py         # T1 — iter_ndjson() + LiveClient(QObject): Signal(dict)+state, wątek, reconnect
  history_model.py       # T2 — HistoryStore Protocol, HistoryModel: selektor raw/rollup, available_series
  theme/
    __init__.py          # T3
    palette.py           # T3 — alert_color(), heat_rgb(), progi
    neon.qss             # T3 — statyczny stylesheet chrome
  plot/
    __init__.py          # T4 — szew renderowy: USE_OPENGL, make_live_plot(), make_history_plot()
  widgets/
    __init__.py          # T5
    gauge.py             # T5 — Gauge(QWidget)
    sparkline.py         # T5 — Sparkline(QWidget) sliding window
    heatmap.py           # T6 — sorted_thermal_keys(), thread_util_keys(), CoreHeatmap(QWidget)
    gpu_panel.py         # T7 — expected_gpu_indices(), gpu_value(), GpuPanel(QWidget)
    proc_table.py        # T7 — bytes_to_mb(), ProcTableModel, ProcTable(QTableView)
    history_strip.py     # T8 — follow_active(), window_mode(), HistoryStrip(QWidget)
  app.py                 # T9 — MainWindow(QMainWindow) bento grid, main()
bench/
  spike_w2.py            # T0 — benchmark renderu
  SPIKE-W2-RESULTS.md    # T0 — zapis zmierzonych liczb + decyzja
packaging/
  kokpit.desktop         # T10 — launcher .desktop
tests/
  conftest.py            # T1 — fixture qapp (offscreen)
  test_live_client.py    # T1
  test_history_model.py  # T2
  test_palette.py        # T3
  test_heatmap.py        # T6
  test_gpu_proc.py       # T7
  test_history_strip.py  # T8
  test_widgets_smoke.py  # T5,T9
```

---

### Task 0: Spike W2 — benchmark renderu (BLOKUJE T4–T9)

**Cel:** zmierzyć, czy pełny bento utrzyma budżet renderu na maszynie docelowej, i wybrać dźwignie (downsampling / `useOpenGL`). Wynik (flaga `USE_OPENGL`, strategia) zasila T4. To zadanie pomiarowe — nie TDD.

**Kryterium wyjścia (pass/fail):** pełny bento (32 sparkline po ~300 pkt + 2 heatmapy 32/24 komórek + ~6 gauge'y + HistoryStrip z downsamplingiem) utrzymuje **≥10 fps przy <25% jednego rdzenia CPU**. Najpierw bez `useOpenGL`; włącz tylko jeśli próg nieosiągalny inaczej.

**Files:**
- Create: `bench/spike_w2.py`, `bench/SPIKE-W2-RESULTS.md`
- Modify: `pyproject.toml` (dodać entry-point UI; deps `ui` już są)

- [ ] **Step 1: Zainstaluj zależności UI**

```bash
cd ~/Code/kokpit
.venv/bin/pip install -e ".[ui,dev]"
```

- [ ] **Step 2: Dodaj entry-point UI do `pyproject.toml`**

W sekcji `[project.scripts]` (obok istniejącego `kokpit-collectord`) dopisz:

```toml
[project.scripts]
kokpit-collectord = "kokpit.collectord:main"
kokpit = "kokpit.ui.app:main"
```

- [ ] **Step 3: Napisz `bench/spike_w2.py`**

```python
"""Spike W2: zmierz fps i %CPU pełnego bento na tej maszynie.
Uruchom: .venv/bin/python bench/spike_w2.py [--opengl]
Renderuje 32 krzywe (~300 pkt), 2 siatki kafli (32/24), 6 gauge'y, 1 history-stos
i przez 10 s liczy klatki + czas CPU procesu. Decyzja zapisywana ręcznie do SPIKE-W2-RESULTS.md.
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")  # realny render; offscreen = nierzetelny fps

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

USE_OPENGL = "--opengl" in sys.argv
pg.setConfigOptions(antialias=False, useOpenGL=USE_OPENGL)


def build_window() -> tuple[QtWidgets.QWidget, list]:
    w = QtWidgets.QWidget()
    grid = QtWidgets.QGridLayout(w)
    curves = []
    # 32 sparkline w jednym ViewBox (wariant "shared ViewBox/wiele krzywych")
    plot = pg.PlotWidget()
    plot.setMenuEnabled(False)
    plot.disableAutoRange()
    plot.setYRange(0, 100)
    plot.setXRange(0, 300)
    for i in range(32):
        c = plot.plot(pen=pg.mkPen((i * 7 % 255, 200, 255 - (i * 5 % 255))))
        c.setDownsampling(auto=True, mode="peak")
        c.setClipToView(True)
        curves.append(c)
    grid.addWidget(plot, 0, 0, 1, 4)
    # history stos: 4 wykresy z DateAxis
    for r in range(4):
        hp = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        hp.disableAutoRange()
        hc = hp.plot(pen=pg.mkPen((0, 255, 200)))
        hc.setDownsampling(auto=True, mode="peak")
        hc.setClipToView(True)
        curves.append(hc)
        grid.addWidget(hp, 1 + r, 0, 1, 4)
    return w, curves


def main() -> int:
    app = QtWidgets.QApplication([])
    w, curves = build_window()
    w.resize(1400, 900)
    w.show()

    x = np.arange(300, dtype=float)
    frames = {"n": 0}
    t_cpu0 = time.process_time()
    t_wall0 = time.perf_counter()

    def tick():
        n = frames["n"]
        for c in curves:
            c.setData(x, 50 + 40 * np.sin(x / 20.0 + n / 5.0 + id(c) % 7))
        frames["n"] += 1

    timer = QtCore.QTimer()
    timer.timeout.connect(tick)
    timer.start(0)  # render tak szybko jak się da → mierzymy sufit

    def stop():
        wall = time.perf_counter() - t_wall0
        cpu = time.process_time() - t_cpu0
        fps = frames["n"] / wall
        print(f"opengl={USE_OPENGL}  frames={frames['n']}  fps={fps:.1f}  "
              f"cpu%={100 * cpu / wall:.1f}  (wall={wall:.1f}s)")
        app.quit()

    QtCore.QTimer.singleShot(10_000, stop)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Uruchom benchmark (bez i z OpenGL)**

```bash
.venv/bin/python bench/spike_w2.py
.venv/bin/python bench/spike_w2.py --opengl
```
Expected: dwie linie `opengl=... fps=... cpu%=...`. (Wymaga sesji graficznej; jeśli zdalnie — odpal na maszynie docelowej.)

- [ ] **Step 5: Zapisz decyzję do `bench/SPIKE-W2-RESULTS.md`**

```markdown
# Spike W2 — wyniki (maszyna docelowa i9-13900KF / RTX 4060 Ti)

Data: <YYYY-MM-DD>

| wariant | fps | %CPU (1 rdzeń) |
|---|---|---|
| bez OpenGL | <zmierz> | <zmierz> |
| z OpenGL   | <zmierz> | <zmierz> |

Próg: ≥10 fps / <25% rdzenia.

**Decyzja:** `USE_OPENGL = <True|False>`. Downsampling `auto/peak` + `clipToView` ON,
`disableAutoRange()` w live. Uzasadnienie: <która konfiguracja spełnia próg najtaniej>.
```

- [ ] **Step 6: Commit**

```bash
git add bench/spike_w2.py bench/SPIKE-W2-RESULTS.md pyproject.toml
git commit -m "spike(ui): W2 render benchmark + UI entry-point; record USE_OPENGL decision"
```

---

### Task 1: `live_client` — framing NDJSON + LiveClient (Signal/thread/reconnect)

**Files:**
- Create: `kokpit/ui/__init__.py`, `kokpit/ui/live_client.py`, `tests/conftest.py`, `tests/test_live_client.py`

**Interfaces:**
- Produces:
  - `iter_ndjson(buf: bytes) -> tuple[list[dict], bytes]` — parsuje kompletne linie, zwraca obiekty + niedokończony ogon bufora.
  - `class LiveClient(QtCore.QObject)`: sygnały `snapshot = QtCore.Signal(dict)`, `state = QtCore.Signal(str)` (`"connected"`/`"stale"`/`"disconnected"`); `__init__(sock_path: str, stale_after_s: float = 3.0)`, `start() -> None`, `stop() -> None`.
- Consumes: nic (T1 jest u podstawy). W teście integracyjnym używa `kokpit.live.LiveServer` (backend) do realnego round-tripu.

- [ ] **Step 1: Napisz `tests/conftest.py` (fixture qapp offscreen)**

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app
```

- [ ] **Step 2: Napisz failing test `tests/test_live_client.py`**

```python
import json
import time

from kokpit.ui.live_client import iter_ndjson, LiveClient


def test_iter_ndjson_two_complete_lines():
    buf = b'{"a":1}\n{"b":2}\n'
    objs, rest = iter_ndjson(buf)
    assert objs == [{"a": 1}, {"b": 2}]
    assert rest == b""


def test_iter_ndjson_keeps_partial_tail():
    objs, rest = iter_ndjson(b'{"a":1}\n{"b":')
    assert objs == [{"a": 1}]
    assert rest == b'{"b":'
    # dosklejenie reszty w kolejnym czytaniu
    objs2, rest2 = iter_ndjson(rest + b'2}\n')
    assert objs2 == [{"b": 2}]
    assert rest2 == b""


def test_iter_ndjson_empty():
    assert iter_ndjson(b"") == ([], b"")


def test_live_client_emits_snapshot(qapp, tmp_path):
    from kokpit.live import LiveServer
    from PySide6 import QtCore

    sock = str(tmp_path / "k.sock")
    srv = LiveServer(sock)
    srv.start()
    received = []
    states = []
    client = LiveClient(sock)
    client.snapshot.connect(lambda d: received.append(d))
    client.state.connect(lambda s: states.append(s))
    client.start()
    try:
        deadline = time.time() + 3.0
        while time.time() < deadline and "connected" not in states:
            qapp.processEvents()
            time.sleep(0.02)
        srv.publish({"ts": 1000, "series": {"gpu.0.util": 63.0}, "procs": []})
        deadline = time.time() + 3.0
        while time.time() < deadline and not received:
            qapp.processEvents()
            time.sleep(0.02)
    finally:
        client.stop()
        srv.stop()

    assert received and received[0]["series"]["gpu.0.util"] == 63.0
    assert "connected" in states
```

- [ ] **Step 3: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_live_client.py -q`
Expected: FAIL (ModuleNotFoundError: kokpit.ui.live_client)

- [ ] **Step 4: Napisz `kokpit/ui/__init__.py` (pusty) i `kokpit/ui/live_client.py`**

`kokpit/ui/__init__.py`:
```python
```

`kokpit/ui/live_client.py`:
```python
import json
import socket
import threading
import time

from PySide6 import QtCore


def iter_ndjson(buf: bytes) -> tuple[list[dict], bytes]:
    """Wytnij kompletne linie JSON z bufora; zwróć (obiekty, niedokończony ogon)."""
    objs: list[dict] = []
    while True:
        nl = buf.find(b"\n")
        if nl == -1:
            return objs, buf
        line, buf = buf[:nl], buf[nl + 1:]
        line = line.strip()
        if line:
            objs.append(json.loads(line.decode()))


class LiveClient(QtCore.QObject):
    snapshot = QtCore.Signal(dict)
    state = QtCore.Signal(str)

    def __init__(self, sock_path: str, stale_after_s: float = 3.0) -> None:
        super().__init__()
        self._sock_path = sock_path
        self._stale_after = stale_after_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)

    def _run(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                sock.connect(self._sock_path)
            except OSError:
                self.state.emit("disconnected")
                if self._stop.wait(backoff):
                    return
                backoff = min(backoff * 2, 5.0)
                continue
            backoff = 0.5
            self.state.emit("connected")
            buf = b""
            last = time.monotonic()
            try:
                while not self._stop.is_set():
                    try:
                        chunk = sock.recv(65536)
                    except socket.timeout:
                        if time.monotonic() - last > self._stale_after:
                            self.state.emit("stale")
                        continue
                    if not chunk:
                        break  # serwer zamknął — reconnect
                    buf += chunk
                    objs, buf = iter_ndjson(buf)
                    for obj in objs:
                        last = time.monotonic()
                        self.snapshot.emit(obj)
            finally:
                sock.close()
            if not self._stop.is_set():
                self.state.emit("disconnected")
```

- [ ] **Step 5: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_live_client.py -q`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add kokpit/ui/__init__.py kokpit/ui/live_client.py tests/conftest.py tests/test_live_client.py
git commit -m "feat(ui): LiveClient — NDJSON framing + QtCore.Signal over socket thread"
```

---

### Task 2: `history_model` — selektor okna raw/rollup + lista serii

**Files:**
- Create: `kokpit/ui/history_model.py`, `tests/test_history_model.py`

**Interfaces:**
- Produces:
  - `RAW_WINDOW_MAX_S = 3600` (≤1h → raw `sample`; powyżej → `rollup_1m`).
  - `@dataclass HistoryResult: line: list[tuple[float, float]]; band: list[tuple[float, float, float]] | None; is_rollup: bool` — `line`/`band` z czasem w **sekundach**.
  - `class HistoryModel`: `__init__(store)`, `window(name: str, window_s: int, now_ms: int) -> HistoryResult`, `available_series(prefix: str | None = None) -> list[str]`.
- Consumes (duck-typed `store`, dostarcza realnie `kokpit.store.Store` w T9): `query(name, since_ms, until_ms) -> [(ts_ms, value)]`, `query_rollup(name, since_ms, until_ms) -> [(bucket_ms, vmin, vmax, vavg, vlast)]`, `list_series(prefix=None) -> [str]`.

- [ ] **Step 1: Napisz failing test `tests/test_history_model.py`**

```python
from kokpit.ui.history_model import HistoryModel, RAW_WINDOW_MAX_S


class FakeStore:
    """Duck-typed kontrakt store; zapisuje co zawołano."""
    def __init__(self):
        self.calls = []

    def query(self, name, since_ms, until_ms):
        self.calls.append(("query", name, since_ms, until_ms))
        return [(since_ms, 1.0), (until_ms, 2.0)]

    def query_rollup(self, name, since_ms, until_ms):
        self.calls.append(("query_rollup", name, since_ms, until_ms))
        return [(since_ms, 0.0, 9.0, 4.5, 5.0), (until_ms, 1.0, 8.0, 4.0, 3.0)]

    def list_series(self, prefix=None):
        self.calls.append(("list_series", prefix))
        return ["net.eth0.rx_bps", "net.eth0.tx_bps", "gpu.0.util"]


def test_window_1h_uses_raw_seconds():
    st = FakeStore()
    res = HistoryModel(st).window("cpu.loadavg.1", 3600, now_ms=3_600_000)
    assert res.is_rollup is False
    assert st.calls[0][0] == "query"
    # czas w sekundach (ms/1000)
    assert res.line[0] == (0.0, 1.0)
    assert res.line[1] == (3600.0, 2.0)
    assert res.band is None


def test_window_24h_uses_rollup_with_band():
    st = FakeStore()
    res = HistoryModel(st).window("gpu.0.util", 86_400, now_ms=86_400_000)
    assert res.is_rollup is True
    assert st.calls[0][0] == "query_rollup"
    assert res.line[0] == (0.0, 4.5)          # vavg
    assert res.band[0] == (0.0, 0.0, 9.0)     # (t, vmin, vmax)


def test_threshold_boundary_is_raw_at_max():
    st = FakeStore()
    HistoryModel(st).window("x", RAW_WINDOW_MAX_S, now_ms=10_000_000)
    assert st.calls[0][0] == "query"


def test_available_series_delegates():
    st = FakeStore()
    assert HistoryModel(st).available_series("net.") == [
        "net.eth0.rx_bps", "net.eth0.tx_bps", "gpu.0.util",
    ]
    assert st.calls[-1] == ("list_series", "net.")
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_history_model.py -q`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Zaimplementuj `kokpit/ui/history_model.py`**

```python
from dataclasses import dataclass

RAW_WINDOW_MAX_S = 3600  # ≤1h → raw sample; powyżej → rollup_1m


@dataclass
class HistoryResult:
    line: list[tuple[float, float]]                 # (t_sekundy, wartość)
    band: list[tuple[float, float, float]] | None   # (t_sekundy, vmin, vmax) — tylko rollup
    is_rollup: bool


class HistoryModel:
    def __init__(self, store) -> None:
        self._store = store

    def window(self, name: str, window_s: int, now_ms: int) -> HistoryResult:
        since_ms = now_ms - window_s * 1000
        if window_s <= RAW_WINDOW_MAX_S:
            rows = self._store.query(name, since_ms, now_ms)
            line = [(ts / 1000.0, v) for ts, v in rows]
            return HistoryResult(line=line, band=None, is_rollup=False)
        rows = self._store.query_rollup(name, since_ms, now_ms)
        line = [(b / 1000.0, vavg) for b, _vmin, _vmax, vavg, _vlast in rows]
        band = [(b / 1000.0, vmin, vmax) for b, vmin, vmax, _vavg, _vlast in rows]
        return HistoryResult(line=line, band=band, is_rollup=True)

    def available_series(self, prefix: str | None = None) -> list[str]:
        return self._store.list_series(prefix)
```

- [ ] **Step 4: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_history_model.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/history_model.py tests/test_history_model.py
git commit -m "feat(ui): HistoryModel — raw/rollup window selector (ms->s), available_series"
```

---

### Task 3: `theme` — paleta alertów + rampa heatmapy + QSS

**Files:**
- Create: `kokpit/ui/theme/__init__.py`, `kokpit/ui/theme/palette.py`, `kokpit/ui/theme/neon.qss`, `tests/test_palette.py`

**Interfaces:**
- Produces:
  - `HIGH_C = 80.0`, `CRIT_C = 100.0`.
  - `alert_color(value: float, high: float = HIGH_C, crit: float = CRIT_C) -> str` — hex: zielony `#39ff14` (<high), amber `#ffb000` (high–crit), czerwony `#ff2a2a` (≥crit).
  - `heat_rgb(frac: float) -> tuple[int, int, int]` — frac clampowane 0..1, lerp `COLD=(10,12,28)`→`HOT=(255,40,80)`.
  - `qss_path() -> str` — ścieżka do `neon.qss`.

- [ ] **Step 1: Napisz failing test `tests/test_palette.py`**

```python
from kokpit.ui.theme.palette import alert_color, heat_rgb, qss_path
import os


def test_alert_color_bands():
    assert alert_color(50) == "#39ff14"     # zielony < high
    assert alert_color(80) == "#ffb000"     # amber na progu high
    assert alert_color(99) == "#ffb000"
    assert alert_color(100) == "#ff2a2a"    # czerwony na crit
    assert alert_color(120) == "#ff2a2a"


def test_heat_rgb_endpoints_and_clamp():
    assert heat_rgb(0.0) == (10, 12, 28)
    assert heat_rgb(1.0) == (255, 40, 80)
    assert heat_rgb(-5) == (10, 12, 28)     # clamp dół
    assert heat_rgb(9) == (255, 40, 80)     # clamp góra
    mid = heat_rgb(0.5)
    assert mid == (132, 26, 54)             # liniowa interpolacja


def test_qss_exists():
    assert os.path.isfile(qss_path())
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_palette.py -q`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Zaimplementuj `theme/`**

`kokpit/ui/theme/__init__.py`:
```python
```

`kokpit/ui/theme/palette.py`:
```python
import os

HIGH_C = 80.0
CRIT_C = 100.0

_GREEN = "#39ff14"
_AMBER = "#ffb000"
_RED = "#ff2a2a"

_COLD = (10, 12, 28)
_HOT = (255, 40, 80)


def alert_color(value: float, high: float = HIGH_C, crit: float = CRIT_C) -> str:
    if value >= crit:
        return _RED
    if value >= high:
        return _AMBER
    return _GREEN


def heat_rgb(frac: float) -> tuple[int, int, int]:
    f = 0.0 if frac < 0 else 1.0 if frac > 1 else frac
    return tuple(int(c0 + (c1 - c0) * f) for c0, c1 in zip(_COLD, _HOT))


def qss_path() -> str:
    return os.path.join(os.path.dirname(__file__), "neon.qss")
```

`kokpit/ui/theme/neon.qss`:
```css
QWidget {
    background-color: #07090f;
    color: #c8f5ff;
    font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace;
    font-size: 11px;
}
QMainWindow, QFrame { background-color: #07090f; }
QHeaderView::section {
    background-color: #0c111b;
    color: #6ad7ff;
    border: 0px;
    padding: 2px 6px;
}
QTableView {
    background-color: #07090f;
    gridline-color: #14202e;
    selection-background-color: #112233;
}
QLabel#tileTitle { color: #6ad7ff; font-weight: bold; letter-spacing: 1px; }
QPushButton {
    background-color: #0c111b; border: 1px solid #1d6b8c; padding: 2px 8px; color: #9fe9ff;
}
QPushButton:checked { background-color: #14384a; border-color: #39d0ff; }
```

- [ ] **Step 4: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_palette.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/theme tests/test_palette.py
git commit -m "feat(ui): neon theme — alert palette, heatmap ramp, QSS chrome"
```

---

### Task 4: `plot` — szew renderowy (stosuje decyzję spike'u)

**Files:**
- Create: `kokpit/ui/plot/__init__.py`, dopisek w `tests/test_widgets_smoke.py`

**Interfaces:**
- Consumes: decyzja z `bench/SPIKE-W2-RESULTS.md` (Task 0) → ustaw `USE_OPENGL`.
- Produces:
  - `USE_OPENGL: bool` (wartość wg spike'u; domyślnie `False`).
  - `make_live_plot() -> pg.PlotWidget` — `disableAutoRange()`, menu off, downsampling/clip skonfigurowane na krzywych przez wołającego.
  - `make_history_plot() -> pg.PlotWidget` — jak wyżej + `DateAxisItem` na osi X (epoch sekundy→local).
  - `configured_curve(plot, **pen_kwargs)` — dodaje krzywą z `setDownsampling(auto=True, mode="peak")` + `setClipToView(True)`.

- [ ] **Step 1: Napisz failing smoke test `tests/test_widgets_smoke.py`**

```python
def test_make_plots_smoke(qapp):
    from kokpit.ui.plot import make_live_plot, make_history_plot, configured_curve
    lp = make_live_plot()
    c = configured_curve(lp, color=(0, 255, 200))
    c.setData([0, 1, 2], [1, 2, 3])
    hp = make_history_plot()
    assert lp is not None and hp is not None
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_widgets_smoke.py::test_make_plots_smoke -q`
Expected: FAIL (ModuleNotFoundError: kokpit.ui.plot)

- [ ] **Step 3: Zaimplementuj `kokpit/ui/plot/__init__.py`**

```python
import pyqtgraph as pg

# Ustawione wg Task 0 (bench/SPIKE-W2-RESULTS.md). Domyślnie False — włącz tylko jeśli spike tego wymaga.
USE_OPENGL = False

pg.setConfigOptions(antialias=False, useOpenGL=USE_OPENGL, background="#07090f", foreground="#6ad7ff")


def make_live_plot() -> pg.PlotWidget:
    p = pg.PlotWidget()
    p.setMenuEnabled(False)
    p.hideButtons()
    p.disableAutoRange()
    return p


def make_history_plot() -> pg.PlotWidget:
    p = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
    p.setMenuEnabled(False)
    p.disableAutoRange()
    return p


def configured_curve(plot: pg.PlotWidget, color=(0, 255, 200), width: int = 1):
    curve = plot.plot(pen=pg.mkPen(color, width=width))
    curve.setDownsampling(auto=True, mode="peak")
    curve.setClipToView(True)
    return curve
```

- [ ] **Step 4: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_widgets_smoke.py::test_make_plots_smoke -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/plot/__init__.py tests/test_widgets_smoke.py
git commit -m "feat(ui): plot rendering seam (downsampling/clip, DateAxis, USE_OPENGL flag)"
```

---

### Task 5: widgety `Gauge` + `Sparkline`

**Files:**
- Create: `kokpit/ui/widgets/__init__.py`, `kokpit/ui/widgets/gauge.py`, `kokpit/ui/widgets/sparkline.py`, dopisek w `tests/test_widgets_smoke.py`

**Interfaces:**
- Consumes: `kokpit.ui.theme.palette.alert_color`, `kokpit.ui.plot.make_live_plot/configured_curve`.
- Produces:
  - `class Gauge(QtWidgets.QWidget)`: `__init__(title: str, unit: str = "", high=80, crit=100)`, `set_value(value: float | None) -> None` (None → „--", kolor wg `alert_color`).
  - `class Sparkline(QtWidgets.QWidget)`: `__init__(title: str, window_s: int = 300, y_range: tuple | None = None)`, `push(value: float | None) -> None` (ring-buffer sliding window; None pomija punkt).

- [ ] **Step 1: Dopisz failing smoke testy do `tests/test_widgets_smoke.py`**

```python
def test_gauge_set_value(qapp):
    from kokpit.ui.widgets.gauge import Gauge
    g = Gauge("CPU PKG", "°C")
    g.set_value(95)            # amber
    g.set_value(None)          # brak danych — bez crasha
    assert g._value_label.text() == "--"

def test_sparkline_push(qapp):
    from kokpit.ui.widgets.sparkline import Sparkline
    s = Sparkline("GPU", window_s=5, y_range=(0, 100))
    for v in [10, 20, None, 30]:
        s.push(v)
    assert len(s._ys) == 3     # None pominięte
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_widgets_smoke.py -q -k "gauge or sparkline"`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Zaimplementuj widgety**

`kokpit/ui/widgets/__init__.py`:
```python
```

`kokpit/ui/widgets/gauge.py`:
```python
from PySide6 import QtWidgets

from kokpit.ui.theme.palette import alert_color


class Gauge(QtWidgets.QWidget):
    def __init__(self, title: str, unit: str = "", high: float = 80, crit: float = 100) -> None:
        super().__init__()
        self._unit = unit
        self._high = high
        self._crit = crit
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        self._title = QtWidgets.QLabel(title)
        self._title.setObjectName("tileTitle")
        self._value_label = QtWidgets.QLabel("--")
        f = self._value_label.font()
        f.setPointSize(20)
        f.setBold(True)
        self._value_label.setFont(f)
        lay.addWidget(self._title)
        lay.addWidget(self._value_label)

    def set_value(self, value: float | None) -> None:
        if value is None:
            self._value_label.setText("--")
            self._value_label.setStyleSheet("color:#445;")
            return
        self._value_label.setText(f"{value:.0f}{self._unit}")
        self._value_label.setStyleSheet(f"color:{alert_color(value, self._high, self._crit)};")
```

`kokpit/ui/widgets/sparkline.py`:
```python
import time
from collections import deque

from PySide6 import QtWidgets

from kokpit.ui.plot import make_live_plot, configured_curve


class Sparkline(QtWidgets.QWidget):
    def __init__(self, title: str, window_s: int = 300, y_range: tuple | None = None) -> None:
        super().__init__()
        self._window_s = window_s
        self._xs: deque[float] = deque()
        self._ys: deque[float] = deque()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        label = QtWidgets.QLabel(title)
        label.setObjectName("tileTitle")
        lay.addWidget(label)
        self._plot = make_live_plot()
        if y_range:
            self._plot.setYRange(*y_range)
        self._curve = configured_curve(self._plot, color=(57, 208, 255))
        lay.addWidget(self._plot)

    def push(self, value: float | None) -> None:
        if value is None:
            return
        now = time.monotonic()
        self._xs.append(now)
        self._ys.append(float(value))
        cutoff = now - self._window_s
        while self._xs and self._xs[0] < cutoff:
            self._xs.popleft()
            self._ys.popleft()
        x0 = self._xs[0]
        self._curve.setData([t - x0 for t in self._xs], list(self._ys))
        self._plot.setXRange(0, self._window_s)
```

- [ ] **Step 4: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_widgets_smoke.py -q -k "gauge or sparkline"`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/widgets/__init__.py kokpit/ui/widgets/gauge.py kokpit/ui/widgets/sparkline.py tests/test_widgets_smoke.py
git commit -m "feat(ui): Gauge + Sparkline widgets (alert color, sliding-window ring)"
```

---

### Task 6: `CoreHeatmap` — util(32) + temp(24), dwa gridy

**Files:**
- Create: `kokpit/ui/widgets/heatmap.py`, `tests/test_heatmap.py`

**Interfaces:**
- Consumes: `kokpit.ui.theme.palette.heat_rgb`.
- Produces:
  - `thread_util_keys(n: int = 32) -> list[str]` → `["cpu.thread.0.util", …, "cpu.thread.31.util"]`.
  - `sorted_thermal_keys(names) -> list[str]` — filtruje `thermal.core.<N>`, sortuje rosnąco po int N (klucze nieciągłe).
  - `class CoreHeatmap(QtWidgets.QWidget)`: `__init__()`, `set_util(series: dict)`, `set_temp(series: dict)` — czyta przez `.get`, koloruje komórki przez `heat_rgb` (util: 0..100 → 0..1; temp: 20..100°C → 0..1).

- [ ] **Step 1: Napisz failing test `tests/test_heatmap.py`**

```python
from kokpit.ui.widgets.heatmap import thread_util_keys, sorted_thermal_keys


def test_thread_util_keys():
    keys = thread_util_keys(32)
    assert keys[0] == "cpu.thread.0.util"
    assert keys[31] == "cpu.thread.31.util"
    assert len(keys) == 32


def test_sorted_thermal_keys_noncontiguous():
    names = ["thermal.pkg", "thermal.core.12", "thermal.core.0",
             "thermal.core.4", "thermal.nvme.0"]
    assert sorted_thermal_keys(names) == [
        "thermal.core.0", "thermal.core.4", "thermal.core.12",
    ]
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_heatmap.py -q`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Zaimplementuj `kokpit/ui/widgets/heatmap.py`**

```python
import math

from PySide6 import QtWidgets

from kokpit.ui.theme.palette import heat_rgb


def thread_util_keys(n: int = 32) -> list[str]:
    return [f"cpu.thread.{i}.util" for i in range(n)]


def sorted_thermal_keys(names) -> list[str]:
    cores = [n for n in names if n.startswith("thermal.core.")]
    return sorted(cores, key=lambda n: int(n.rsplit(".", 1)[1]))


class _CellGrid(QtWidgets.QWidget):
    def __init__(self, title: str, cols: int) -> None:
        super().__init__()
        self._cols = cols
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        label = QtWidgets.QLabel(title)
        label.setObjectName("tileTitle")
        lay.addWidget(label)
        self._grid = QtWidgets.QGridLayout()
        self._grid.setSpacing(2)
        lay.addLayout(self._grid)
        self._cells: list[QtWidgets.QFrame] = []

    def ensure(self, count: int) -> None:
        while len(self._cells) < count:
            cell = QtWidgets.QFrame()
            cell.setFixedSize(18, 18)
            i = len(self._cells)
            self._grid.addWidget(cell, i // self._cols, i % self._cols)
            self._cells.append(cell)

    def paint(self, index: int, frac: float | None) -> None:
        cell = self._cells[index]
        if frac is None:
            cell.setStyleSheet("background:#0c111b;border:1px solid #14202e;")
            return
        r, g, b = heat_rgb(frac)
        cell.setStyleSheet(f"background:rgb({r},{g},{b});border:1px solid #14202e;")


class CoreHeatmap(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._util = _CellGrid("THREAD UTIL (32)", cols=8)
        self._temp = _CellGrid("CORE TEMP (24)", cols=6)
        lay.addWidget(self._util)
        lay.addWidget(self._temp)

    def set_util(self, series: dict) -> None:
        keys = thread_util_keys(32)
        self._util.ensure(len(keys))
        for i, k in enumerate(keys):
            v = series.get(k)
            self._util.paint(i, None if v is None else max(0.0, min(1.0, v / 100.0)))

    def set_temp(self, series: dict) -> None:
        keys = sorted_thermal_keys(series.keys())
        self._temp.ensure(len(keys))
        for i, k in enumerate(keys):
            v = series.get(k)
            # 20..100°C → 0..1
            self._temp.paint(i, None if v is None else max(0.0, min(1.0, (v - 20.0) / 80.0)))
```

- [ ] **Step 4: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_heatmap.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Dodaj smoke test i uruchom**

Dopisz do `tests/test_widgets_smoke.py`:
```python
def test_heatmap_smoke(qapp):
    from kokpit.ui.widgets.heatmap import CoreHeatmap
    h = CoreHeatmap()
    util = {f"cpu.thread.{i}.util": (i * 3) % 100 for i in range(32)}
    temp = {f"thermal.core.{i}": 40 + i for i in (0, 4, 8, 12, 16, 20)}
    temp["thermal.core.5"] = None  # brakująca seria — bez crasha
    h.set_util(util)
    h.set_temp({k: v for k, v in temp.items() if v is not None})
```

Run: `.venv/bin/pytest tests/test_heatmap.py tests/test_widgets_smoke.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add kokpit/ui/widgets/heatmap.py tests/test_heatmap.py tests/test_widgets_smoke.py
git commit -m "feat(ui): CoreHeatmap — util32 + temp24 grids, non-contiguous thermal keys"
```

---

### Task 7: `GpuPanel` + `ProcTable`

**Files:**
- Create: `kokpit/ui/widgets/gpu_panel.py`, `kokpit/ui/widgets/proc_table.py`, `tests/test_gpu_proc.py`

**Interfaces:**
- Consumes: `kokpit.ui.widgets.gauge.Gauge`.
- Produces:
  - `expected_gpu_indices(series_names) -> list[int]` — z nazw `gpu.<i>.*` zwraca posortowane unikalne `i`.
  - `gpu_value(snapshot: dict, i: int, field: str) -> float | None` — `snapshot["series"].get(f"gpu.{i}.{field}")`.
  - `class GpuPanel(QtWidgets.QWidget)`: `__init__(gpu_indices: list[int])`, `update_snapshot(snapshot: dict)` — brak serii znanego GPU → kafel „n/a".
  - `bytes_to_mb(n: float) -> float`.
  - `class ProcTableModel(QtCore.QAbstractTableModel)`, `class ProcTable(QtWidgets.QTableView)`: `set_rows(procs: list[dict])`.

- [ ] **Step 1: Napisz failing test `tests/test_gpu_proc.py`**

```python
from kokpit.ui.widgets.gpu_panel import expected_gpu_indices, gpu_value
from kokpit.ui.widgets.proc_table import bytes_to_mb


def test_expected_gpu_indices():
    names = ["gpu.0.util", "gpu.0.temp", "gpu.1.util", "cpu.loadavg.1"]
    assert expected_gpu_indices(names) == [0, 1]


def test_gpu_value_missing_is_none():
    snap = {"series": {"gpu.0.util": 63.0}}
    assert gpu_value(snap, 0, "util") == 63.0
    assert gpu_value(snap, 0, "temp") is None     # absent → n/a
    assert gpu_value(snap, 1, "util") is None


def test_bytes_to_mb():
    assert bytes_to_mb(1024 * 1024) == 1.0
    assert bytes_to_mb(0) == 0.0
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_gpu_proc.py -q`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Zaimplementuj widgety**

`kokpit/ui/widgets/gpu_panel.py`:
```python
from PySide6 import QtWidgets

from kokpit.ui.widgets.gauge import Gauge


def expected_gpu_indices(series_names) -> list[int]:
    idx = set()
    for n in series_names:
        if n.startswith("gpu."):
            try:
                idx.add(int(n.split(".")[1]))
            except (IndexError, ValueError):
                pass
    return sorted(idx)


def gpu_value(snapshot: dict, i: int, field: str) -> float | None:
    return snapshot.get("series", {}).get(f"gpu.{i}.{field}")


class GpuPanel(QtWidgets.QWidget):
    def __init__(self, gpu_indices: list[int]) -> None:
        super().__init__()
        lay = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel("GPU")
        title.setObjectName("tileTitle")
        lay.addWidget(title)
        self._tiles: dict[int, dict] = {}
        for i in gpu_indices:
            row = QtWidgets.QHBoxLayout()
            util = Gauge(f"GPU{i} UTIL", "%", high=90, crit=99)
            temp = Gauge(f"GPU{i} TEMP", "°C", high=80, crit=95)
            self._vram = QtWidgets.QLabel("VRAM --")
            row.addWidget(util)
            row.addWidget(temp)
            row.addWidget(self._vram)
            lay.addLayout(row)
            self._tiles[i] = {"util": util, "temp": temp, "vram": self._vram}

    def update_snapshot(self, snapshot: dict) -> None:
        for i, t in self._tiles.items():
            t["util"].set_value(gpu_value(snapshot, i, "util"))   # None → "--"/n/a
            t["temp"].set_value(gpu_value(snapshot, i, "temp"))
            used = gpu_value(snapshot, i, "vram_used")
            total = gpu_value(snapshot, i, "vram_total")
            if used is None or total is None or total == 0:
                t["vram"].setText("VRAM n/a")
            else:
                t["vram"].setText(f"VRAM {used / total * 100:.0f}%")
```

`kokpit/ui/widgets/proc_table.py`:
```python
from PySide6 import QtCore, QtWidgets

_COLS = ["PID", "NAME", "CPU%", "RSS MB", "VRAM MB"]


def bytes_to_mb(n: float) -> float:
    return float(n) / (1024 * 1024)


class ProcTableModel(QtCore.QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict] = []

    def set_rows(self, procs: list[dict]) -> None:
        self.beginResetModel()
        self._rows = procs
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return len(_COLS)

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if orientation == QtCore.Qt.Horizontal and role == QtCore.Qt.DisplayRole:
            return _COLS[section]
        return None

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if role != QtCore.Qt.DisplayRole:
            return None
        p = self._rows[index.row()]
        col = index.column()
        if col == 0:
            return str(p.get("pid", ""))
        if col == 1:
            return p.get("name", "")
        if col == 2:
            return f"{p.get('cpu', 0.0):.0f}"
        if col == 3:
            return f"{bytes_to_mb(p.get('rss', 0.0)):.0f}"
        if col == 4:
            return f"{bytes_to_mb(p.get('vram', 0.0)):.0f}"
        return None


class ProcTable(QtWidgets.QTableView):
    def __init__(self) -> None:
        super().__init__()
        self._model = ProcTableModel()
        self.setModel(self._model)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

    def set_rows(self, procs: list[dict]) -> None:
        self._model.set_rows(procs)
```

- [ ] **Step 4: Dodaj smoke test**

Dopisz do `tests/test_gpu_proc.py`:
```python
def test_widgets_smoke(qapp):
    from kokpit.ui.widgets.gpu_panel import GpuPanel
    from kokpit.ui.widgets.proc_table import ProcTable
    gp = GpuPanel([0])
    gp.update_snapshot({"series": {"gpu.0.util": 50.0, "gpu.0.temp": 60.0,
                                   "gpu.0.vram_used": 2e9, "gpu.0.vram_total": 16e9}})
    gp.update_snapshot({"series": {}})   # wszystko n/a — bez crasha
    pt = ProcTable()
    pt.set_rows([{"pid": 1, "name": "x", "cpu": 9.0, "rss": 2097152, "vram": 0.0}])
    assert pt._model.rowCount() == 1
```

- [ ] **Step 5: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_gpu_proc.py -q`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add kokpit/ui/widgets/gpu_panel.py kokpit/ui/widgets/proc_table.py tests/test_gpu_proc.py
git commit -m "feat(ui): GpuPanel (n/a via known indices) + ProcTable (bytes->MB)"
```

---

### Task 8: `HistoryStrip` — follow-mode + wybór trybu okna

**Files:**
- Create: `kokpit/ui/widgets/history_strip.py`, `tests/test_history_strip.py`

**Interfaces:**
- Consumes: `kokpit.ui.plot.make_history_plot/configured_curve`, `kokpit.ui.history_model.HistoryModel`.
- Produces:
  - `follow_active(view_x_max: float, last_ts_s: float, tol_s: float = 2.0) -> bool` — czy prawa krawędź widoku jest „przy teraz".
  - `window_mode(window_s: int) -> str` — `"raw"` (≤1h: ogon live 1 Hz) lub `"poll"` (>1h: odświeżanie DB, krótki ogon).
  - `TAIL_CAP_S = 3600` — twardy limit ogona live w sekundach.
  - `class HistoryStrip(QtWidgets.QWidget)`: `__init__(model: HistoryModel, series: list[str])`, `set_window(window_s, now_ms)`, `on_snapshot(snapshot)` (dokleja ogon tylko w trybie raw i gdy follow ON), `set_follow(bool)`.

- [ ] **Step 1: Napisz failing test `tests/test_history_strip.py`**

```python
from kokpit.ui.widgets.history_strip import follow_active, window_mode, TAIL_CAP_S


def test_follow_active_near_now():
    assert follow_active(view_x_max=1000.0, last_ts_s=1001.0) is True   # w tolerancji
    assert follow_active(view_x_max=900.0, last_ts_s=1001.0) is False   # odjechał w przeszłość


def test_window_mode_split():
    assert window_mode(3600) == "raw"
    assert window_mode(3601) == "poll"
    assert window_mode(86_400) == "poll"


def test_tail_cap_is_one_hour():
    assert TAIL_CAP_S == 3600
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_history_strip.py -q`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Zaimplementuj `kokpit/ui/widgets/history_strip.py`**

```python
from collections import deque

from PySide6 import QtWidgets

from kokpit.ui.history_model import HistoryModel, RAW_WINDOW_MAX_S
from kokpit.ui.plot import make_history_plot, configured_curve

TAIL_CAP_S = 3600  # twardy limit ogona live (sekundy) — chroni pamięć/fps


def follow_active(view_x_max: float, last_ts_s: float, tol_s: float = 2.0) -> bool:
    return view_x_max >= last_ts_s - tol_s


def window_mode(window_s: int) -> str:
    return "raw" if window_s <= RAW_WINDOW_MAX_S else "poll"


class HistoryStrip(QtWidgets.QWidget):
    def __init__(self, model: HistoryModel, series: list[str]) -> None:
        super().__init__()
        self._model = model
        self._series = series
        self._follow = True
        self._window_s = 3600
        self._mode = "raw"
        self._tail: dict[str, deque] = {s: deque() for s in series}
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        self._plots = {}
        self._curves = {}
        for s in series:
            p = make_history_plot()
            label = QtWidgets.QLabel(s)
            label.setObjectName("tileTitle")
            lay.addWidget(label)
            lay.addWidget(p)
            self._plots[s] = p
            self._curves[s] = configured_curve(p, color=(0, 255, 200))

    def set_follow(self, on: bool) -> None:
        self._follow = on

    def set_window(self, window_s: int, now_ms: int) -> None:
        self._window_s = window_s
        self._mode = window_mode(window_s)
        for s in self._series:
            res = self._model.window(s, window_s, now_ms)
            xs = [t for t, _ in res.line]
            ys = [v for _, v in res.line]
            self._curves[s].setData(xs, ys)
            self._tail[s] = deque(zip(xs, ys))

    def on_snapshot(self, snapshot: dict) -> None:
        if self._mode != "raw" or not self._follow:
            return  # tryb poll odświeża się przez set_window (timer w app.py); brak doklejania 1 Hz
        ts = snapshot.get("ts")
        if ts is None:
            return
        t_s = ts / 1000.0
        for s in self._series:
            v = snapshot.get("series", {}).get(s)
            if v is None:
                continue
            tail = self._tail[s]
            tail.append((t_s, v))
            cutoff = t_s - TAIL_CAP_S
            while tail and tail[0][0] < cutoff:
                tail.popleft()
            self._curves[s].setData([t for t, _ in tail], [y for _, y in tail])
```

- [ ] **Step 4: Dodaj smoke test**

Dopisz do `tests/test_history_strip.py`:
```python
def test_history_strip_smoke(qapp):
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.widgets.history_strip import HistoryStrip

    class FakeStore:
        def query(self, name, since_ms, until_ms):
            return [(since_ms, 1.0), (until_ms, 2.0)]
        def query_rollup(self, name, since_ms, until_ms):
            return [(since_ms, 0.0, 9.0, 4.5, 5.0)]
        def list_series(self, prefix=None):
            return []

    strip = HistoryStrip(HistoryModel(FakeStore()), ["cpu.loadavg.1"])
    strip.set_window(3600, now_ms=3_600_000)            # raw
    strip.on_snapshot({"ts": 3_600_500, "series": {"cpu.loadavg.1": 3.0}})
    strip.set_window(86_400, now_ms=90_000_000)         # poll — on_snapshot nie dokleja
    strip.on_snapshot({"ts": 90_000_500, "series": {"cpu.loadavg.1": 4.0}})
```

- [ ] **Step 5: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_history_strip.py -q`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add kokpit/ui/widgets/history_strip.py tests/test_history_strip.py
git commit -m "feat(ui): HistoryStrip — follow-mode, raw-tail cap, poll for long windows"
```

---

### Task 9: `app.py` — bento NOC grid + spięcie live/historia + main()

**Files:**
- Create: `kokpit/ui/app.py`, dopisek w `tests/test_widgets_smoke.py`

**Interfaces:**
- Consumes: `LiveClient`, `HistoryModel`, `kokpit.store.Store`, `kokpit.config.{socket_path,db_path}`, wszystkie widgety, `qss_path`.
- Produces:
  - `class MainWindow(QtWidgets.QMainWindow)`: `__init__(live: LiveClient, model: HistoryModel, gpu_indices: list[int])`, slot `_on_snapshot(dict)`, `_on_state(str)`.
  - `main() -> int` — entry-point (`pyproject [project.scripts] kokpit`).

- [ ] **Step 1: Napisz failing smoke test (dopisz do `tests/test_widgets_smoke.py`)**

```python
def test_mainwindow_builds_and_updates(qapp):
    from kokpit.ui.app import MainWindow
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.live_client import LiveClient

    class FakeStore:
        def query(self, n, a, b): return [(a, 1.0), (b, 2.0)]
        def query_rollup(self, n, a, b): return [(a, 0.0, 9.0, 4.5, 5.0)]
        def list_series(self, prefix=None): return []

    live = LiveClient("/nonexistent.sock")           # nie startujemy wątku w teście
    win = MainWindow(live, HistoryModel(FakeStore()), gpu_indices=[0])
    win._on_state("connected")
    win._on_snapshot({
        "ts": 1000,
        "series": {**{f"cpu.thread.{i}.util": 10 for i in range(32)},
                   "gpu.0.util": 50.0, "mem.used": 1e9, "mem.total": 8e9},
        "procs": [{"pid": 1, "name": "x", "cpu": 5.0, "rss": 1048576, "vram": 0.0}],
    })
    win._on_snapshot({"ts": 2000, "series": {}, "procs": []})   # puste — bez crasha
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_widgets_smoke.py::test_mainwindow_builds_and_updates -q`
Expected: FAIL (ModuleNotFoundError: kokpit.ui.app)

- [ ] **Step 3: Zaimplementuj `kokpit/ui/app.py`**

```python
import sys

from PySide6 import QtWidgets

from kokpit import config
from kokpit.ui.history_model import HistoryModel
from kokpit.ui.live_client import LiveClient
from kokpit.ui.theme.palette import qss_path
from kokpit.ui.widgets.gauge import Gauge
from kokpit.ui.widgets.gpu_panel import GpuPanel, expected_gpu_indices
from kokpit.ui.widgets.heatmap import CoreHeatmap
from kokpit.ui.widgets.history_strip import HistoryStrip
from kokpit.ui.widgets.proc_table import ProcTable
from kokpit.ui.widgets.sparkline import Sparkline

_HIST_SERIES = ["cpu.loadavg.1", "gpu.0.util", "mem.used", "net.eth0.rx_bps"]


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, live: LiveClient, model: HistoryModel, gpu_indices: list[int]) -> None:
        super().__init__()
        self.setWindowTitle("kokpit")
        self._live = live
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        grid = QtWidgets.QGridLayout(central)

        self._heatmap = CoreHeatmap()
        self._gpu = GpuPanel(gpu_indices or [0])
        self._ram = Gauge("RAM", "%", high=85, crit=95)
        self._swap = Gauge("SWAP", "%", high=50, crit=90)
        self._pkg = Gauge("CPU PKG", "°C", high=80, crit=100)
        self._net = Sparkline("NET rx", window_s=120)
        self._disk = Sparkline("DISK r", window_s=120)
        self._procs = ProcTable()
        self._hist = HistoryStrip(model, _HIST_SERIES)
        self._status = QtWidgets.QLabel("disconnected")
        self._status.setObjectName("tileTitle")

        grid.addWidget(self._heatmap, 0, 0, 1, 2)
        grid.addWidget(self._gpu, 0, 2, 1, 2)
        grid.addWidget(self._pkg, 1, 0)
        grid.addWidget(self._ram, 1, 1)
        grid.addWidget(self._swap, 1, 2)
        grid.addWidget(self._net, 1, 3)
        grid.addWidget(self._disk, 2, 0, 1, 2)
        grid.addWidget(self._procs, 2, 2, 1, 2)
        grid.addWidget(self._hist, 3, 0, 1, 4)
        grid.addWidget(self._status, 4, 0, 1, 4)

        live.snapshot.connect(self._on_snapshot)   # AutoConnection → wątek GUI
        live.state.connect(self._on_state)
        self._hist.set_window(3600, now_ms=0)       # placeholder dopóki nie znamy now

    def _on_state(self, state: str) -> None:
        self._status.setText(state)

    def _on_snapshot(self, snap: dict) -> None:
        s = snap.get("series", {})
        self._heatmap.set_util(s)
        self._heatmap.set_temp(s)
        self._gpu.update_snapshot(snap)
        self._pkg.set_value(s.get("thermal.pkg"))
        mt = s.get("mem.total")
        self._ram.set_value(None if not mt else s.get("mem.used", 0) / mt * 100)
        self._swap.set_value(s.get("swap.used"))
        self._net.push(s.get("net.eth0.rx_bps"))
        self._disk.push(s.get("disk.nvme0n1.read_bps"))
        self._procs.set_rows(snap.get("procs", []))
        self._hist.on_snapshot(snap)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    try:
        with open(qss_path()) as fh:
            app.setStyleSheet(fh.read())
    except OSError:
        pass
    from kokpit.store import Store
    store = Store(str(config.db_path()))
    model = HistoryModel(store)
    try:
        gpu_indices = expected_gpu_indices(store.list_series("gpu."))
    except Exception:
        gpu_indices = [0]
    live = LiveClient(str(config.socket_path()))
    win = MainWindow(live, model, gpu_indices)
    win.resize(1500, 950)
    win.show()
    live.start()
    try:
        return app.exec()
    finally:
        live.stop()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_widgets_smoke.py::test_mainwindow_builds_and_updates -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Uruchom cały zestaw testów UI**

Run: `.venv/bin/pytest tests/ -q`
Expected: PASS (wszystkie; backendowe + UI)

- [ ] **Step 6: Commit**

```bash
git add kokpit/ui/app.py tests/test_widgets_smoke.py
git commit -m "feat(ui): MainWindow bento grid + main() wiring live/history/store"
```

---

### Task 10: packaging — launcher `.desktop`

**Files:**
- Create: `packaging/kokpit.desktop`, dopisek w `tests/test_widgets_smoke.py`

**Interfaces:**
- Consumes: entry-point `kokpit` (Task 0, `pyproject [project.scripts]`).
- Produces: plik `.desktop` instalowalny do `~/.local/share/applications/`.

- [ ] **Step 1: Napisz failing test (dopisz do `tests/test_widgets_smoke.py`)**

```python
def test_desktop_file_valid():
    import configparser, os
    path = os.path.join(os.path.dirname(__file__), "..", "packaging", "kokpit.desktop")
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path)
    assert cp["Desktop Entry"]["Exec"] == "kokpit"
    assert cp["Desktop Entry"]["Type"] == "Application"
```

- [ ] **Step 2: Uruchom — failuje**

Run: `.venv/bin/pytest tests/test_widgets_smoke.py::test_desktop_file_valid -q`
Expected: FAIL (FileNotFoundError / KeyError)

- [ ] **Step 3: Napisz `packaging/kokpit.desktop`**

```ini
[Desktop Entry]
Type=Application
Name=kokpit
Comment=Native system telemetry dashboard
Exec=kokpit
Terminal=false
Categories=System;Monitor;
StartupNotify=false
```

- [ ] **Step 4: Uruchom — przechodzi**

Run: `.venv/bin/pytest tests/test_widgets_smoke.py::test_desktop_file_valid -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Smoke ręczny (na maszynie docelowej, opcjonalnie)**

```bash
.venv/bin/kokpit   # okno powinno wstać; "disconnected" gdy demon nie działa, historia z DB jeśli jest
```

- [ ] **Step 6: Commit**

```bash
git add packaging/kokpit.desktop tests/test_widgets_smoke.py
git commit -m "feat(packaging): .desktop launcher for kokpit UI"
```

---

## Self-Review

**1. Spec coverage (Plan 2 = UI):**
- live_client: NDJSON framing + Qt Signal + reconnect + stale (spec §4.1) → T1 ✓
- history_model: selektor raw/rollup, ms→s, available_series fallback (§4.2) → T2 ✓
- HistoryStrip follow-mode + cap taila + poll dla okien rollup + ms→s DateAxis (§4.3) → T8 ✓
- Gauge/Sparkline (§4.4) → T5; CoreHeatmap util32/temp24 dwa gridy, klucze nieciągłe (§4.4) → T6 ✓
- GpuPanel n/a przez list_series, ProcTable bajty→MB, defensywny `.get` (§4.4) → T7 ✓
- plot szew + USE_OPENGL wg spike (§4.5) → T4; theme neon/glow zawężony/progi (§4.6) → T3 ✓
- app bento Layout A + main() (§4.7) → T9; .desktop + entry-point (§4.8) → T0+T10 ✓
- Spike W2 z twardym progiem (§5, Task 0) → T0 ✓
- Testy logiki poza Qt + smoke offscreen (§6) → każdy task ✓
- Odporność: demon martwy/historia z DB, n/a GPU, pierwszy tick bez bps, placeholder (§7) → T1/T7/T8/T9 ✓
- Hot-plug known-limit (§9) → świadomie nieobsługiwane, nieznane klucze ignorowane przez `.get` ✓

**2. Placeholder scan:** każdy krok kodu ma pełny kod + komendę + expected. Jedyne `<...>` to pola do wpisania zmierzonych liczb w `SPIKE-W2-RESULTS.md` (Task 0) — z natury pomiarowe. Brak „TODO/handle edge cases". ✓

**3. Type consistency:** `snapshot` = `{"ts": int_ms, "series": dict, "procs": list}` spójny T1↔T8↔T9. `HistoryResult.line` = `[(t_s, v)]` (sekundy) spójny T2↔T8. `window_mode`/`RAW_WINDOW_MAX_S=3600`/`TAIL_CAP_S=3600` spójne T2↔T8. `gpu_value`/`expected_gpu_indices` spójne T7↔T9. `bytes_to_mb` jeden w T7. `alert_color`/`heat_rgb` z T3 używane w T5/T6. ✓

**Zależność zewnętrzna:** T2/T8/T9 używają `query_rollup`+`list_series` ze `Store` — dostarcza sesja backendowa (kontrakt). Testy Plan 2 używają fake-store, więc Plan 2 jest wykonywalny niezależnie; realny `Store` podpina się w T9 `main()` (poza testami).

---

## Execution Handoff

(Uzupełnione przy przekazaniu do wykonania.)
