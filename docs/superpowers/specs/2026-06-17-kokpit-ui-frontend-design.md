# kokpit — UI / Frontend (Plan 2) — Design

**Wersja:** 1.0
**Data:** 2026-06-17
**Status:** Draft — zatwierdzony w brainstormingu (wejście do writing-plans)

Addendum do `2026-06-17-kokpit-design.md` (główny design, §4.4/§6/§13). Domyka decyzje
UI na poziomie wykonalnym. Backend (Plan 1) zaimplementowany; kontrakty integracyjne
zamrożone w kodzie. Zależność store: `2026-06-17-store-history-api-contract.md`.

---

## 1. Cel Planu 2

Aplikacja `kokpit` (PySide6 + pyqtgraph) — czysty konsument danych demona: bento NOC
grid (neon), live + historia, 4 wiązki metryk, heatmapa util(32)/temp(24) rozdzielone,
historia z trybem „follow now". Estetyka natywnie (QSS + styling pyqtgraph) — `/frontend-design`
wyłączony (spec główny §2: to skill webowy).

## 2. Powierzchnia integracji (zweryfikowana w kodzie Plan 1)

| Kanał | Kontrakt | Źródło |
|---|---|---|
| Live | Unix socket `$XDG_RUNTIME_DIR/kokpit.sock`, NDJSON, 1 linia/snapshot: `{"ts": int_ms, "series": {nazwa: float}, "procs": [...]}` | `kokpit/live.py` `LiveServer.publish()` / `kokpit/collectord.py:38` |
| Proc row | `{"pid","name","cpu":float,"rss":float_bytes,"vram":float_bytes}`, sort malejąco po `cpu`, top-N | `kokpit/proc.py:33` |
| Historia raw | `Store.query(series, since_ms, until_ms) -> [(ts_ms, value)]` (raw `sample`, 48h) | `kokpit/store.py:65` |
| Historia rollup | `Store.query_rollup(series, since_ms, until_ms) -> [(bucket_ms, vmin, vmax, vavg, vlast)]` — **do dostarczenia przez sesję backendową** | kontrakt |
| Lista serii | `Store.list_series(prefix=None) -> [str]` — **do dostarczenia przez sesję backendową** | kontrakt |

**Nazwy serii (dosłowny kontrakt widgetów):**
- `cpu.thread.{0..31}.util`, `cpu.thread.{n}.freq`, `cpu.loadavg.1`
- `thermal.core.{N}` (N = nieciągły numer „Core N": 0,4,8,12…), `thermal.pkg`, `thermal.nvme.{i}`, `thermal.wifi`
- `gpu.{i}.util|vram_used|vram_total|temp|power|clock_sm|fan`
- `mem.*`, `swap.*`, `net.{iface}.rx_bps|tx_bps`, `disk.{dev}.read_bps|write_bps`, `disk.{mount}.used_pct`

## 3. Architektura — live i historia jako dwa pody danych

```
kokpit-collectord ──unix socket(NDJSON)──┐        SQLite(WAL) ──krótkie read-tx──┐
                                          ▼                                       ▼
                                  live_client.py                          history_model.py
                                  (observer, broadcast)                   (selektor raw/rollup)
                                     │           │                              │
                          ┌──────────┘           └──────────┐                   │
                          ▼                                  ▼                   ▼
                  ring-buffery live                  HistoryStrip (follow)  HistoryStrip (blok DB)
                  (Gauge/Sparkline/Heatmap)                  └──── ten sam strip ────┘
```

`live_client` to **jedno źródło broadcastujące** snapshoty do N subskrybentów (observer):
ring-buffery live oraz `HistoryStrip` w trybie follow. Live **nie** czyta z SQLite;
historia **nie** zna bufora live poza doklejanym ogonem follow-mode.

## 4. Komponenty

### 4.1 `live_client.py`
- Wątek czyta socket, **buforuje częściowe linie** (stream Unix nie gwarantuje 1 read = 1 linia), parsuje NDJSON, woła subskrybentów `on_snapshot(dict)`.
- Auto-reconnect z backoffem (0.5→5 s). Stan `connected` / `stale` (>3 s bez snapshotu) / `disconnected` (brak połączenia) wystawiony do UI.
- Obserwator: `subscribe(callback)` — wielu konsumentów, jeden socket.

### 4.2 `history_model.py`
- Krótkie, samodzielne read-tx (open→SELECT→close) — bez wiecznego połączenia, bez `immutable` (spec główny §4.2/K2).
- **Selektor okna:** okno raw-friendly (≤48 h, gęste punkty) → `query()`; okno długie (7d, oraz 24h gdy chcemy rzadziej) → `query_rollup()` (linia z `vavg`, opcjonalne pasmo `vmin`–`vmax`).
- Gdy demon nie żyje a UI startuje: `list_series(prefix)` odkrywa dynamiczne serie (iface/dyski/rdzenie temp) z bazy, bez live-snapshotu (spec główny §7).

### 4.3 `HistoryStrip` — follow now
- Po wczytaniu bloku z DB **subskrybuje** `live_client`; każdy snapshot 1 Hz dokleja punkt do prawej krawędzi, lewa przycinana do długości okna → długie sliding-window (DB → potem socket).
- **Follow ON** domyślnie (prawa krawędź = „teraz"). Pan/zoom w przeszłość → follow OFF (auto-scroll pauza). Kontrolka `● LIVE / skok do teraz` wraca do follow.
- Rozdzielczość: dla okien rollup ogon live (1 Hz raw) doklejany bez downsamplingu — najświeższy ogon przy „teraz" jest pożądany; raw ≈ vavg jednopunktowego bucketu → linia ciągła. Luka load↔live (~1 s) po prostu się łączy. Demon martwy → ogon nie rośnie + znacznik „stale".
- Stos wykresów na wspólnej osi X (`DateAxisItem`, epoch→local tylko do wyświetlania), zlinkowany X do zoom/pan. Pusta historia → placeholder „brak danych" (spec główny §7).

### 4.4 Widgety live (cienkie, logika poza Qt — spec główny §8)
- **`Gauge`** — skalar; kolor wg progów `theme` (green<high · amber · red≥crit).
- **`Sparkline`** — X = sliding window „ostatnie N s", z ring-buffera live.
- **`CoreHeatmap`** — **dwa osobne gridy obok siebie**: UTIL 32 komórki (`cpu.thread.{0..31}.util`, fill=util%) i TEMP 24 komórki (`thermal.core.{N}`, fill=°C). Klucze temp nieciągłe → czytane wprost ze snapshotu/`list_series`, sortowane; bez mapowania phys→wątki w MVP (mapa zachowana na tooltip/przyszły overlay, nie na ścieżce krytycznej).
- **`GpuPanel`** — kafel per-GPU (iteruje `gpu.{i}.*`): util/VRAM used÷total/power/temp/fan/clock_sm. Kafel **„n/a"** gdy serie nieobecne (brak GPU / błąd NVML) — bez crasha.
- **`ProcTable`** — `QTableView`, top-N z `snapshot["procs"]`: pid·name·cpu·rss(MB)·vram(MB), sort po cpu.

### 4.5 `plot/` — szew renderowy (zamraża Task 0)
- API stałe (`update(series)` / `set_window(...)`); wnętrze ustala spike W2: shared `ViewBox`/wiele krzywych vs osobne `PlotWidget`, `setDownsampling(auto=True, mode='peak')` + `clipToView=True`, `disableAutoRange()` w live, `useOpenGL` **tylko jeśli spike uzasadni**. Zmiana decyzji renderowej nie dotyka konsumentów (`app.py`).

### 4.6 `theme/`
- `neon.qss` (chrome Qt), `palette.py` (rampy kolorów + progi alertu high=80/crit=100 z sensors, konfigurowalne). pyqtgraph: czarne tło, **glow pen** (szeroki półprzezroczysty pen pod właściwym).

### 4.7 `app.py` — bento NOC grid (Layout A)
```
┌ THREAD UTIL (32) ┬ CORE TEMP (24) ┬ GPU PANEL          ┐
│ heatmap          │ heatmap+pkg    │ util/vram/pwr/temp │
├──────┬───────────┼────────────────┼────────────────────┤
│ RAM  │ SWAP      │ NET rx/tx      │ DISK r/w + usage%  │
├──────┴───────────┴────────────────┴────────────────────┤
│ PROCESSES  top-N: pid name cpu rss vram                │
├────────────────────────────────────────────────────────┤
│ HISTORY STRIP  [1h|6h|24h|7d]  ● LIVE — stacked, shared X│
└────────────────────────────────────────────────────────┘
```
Spina `live_client` (subskrypcje), `history_model`, widgety. `main()` = entry point.

### 4.8 `packaging/`
- `kokpit.desktop` launcher dla UI. UI startujące przed demonem → auto-reconnect to pokrywa.
- pyproject: `kokpit = "kokpit.ui.app:main"` w `[project.scripts]`.

## 5. Zadania (TDD)

| T | Zakres | Zależność |
|---|---|---|
| T0 | Spike W2 (`bench/spike_w2.py`) — pomiar renderu, decyzja ViewBox/downsampling/OpenGL → notatka | blokuje T4–T9 |
| T1 | `live_client.py` (bufor NDJSON, reconnect, observer) + test | — |
| T2 | `history_model.py` (selektor raw/rollup, read-tx, feed follow) + test | kontrakt store |
| T3 | `theme/` (qss, palette, progi) | — |
| T4 | `plot/` szew (stosuje T0) | T0 |
| T5 | `Gauge`, `Sparkline` + smoke | T3,T4 |
| T6 | `CoreHeatmap` (2 gridy) + test mapowania | T3 |
| T7 | `GpuPanel`, `ProcTable` + smoke | T3 |
| T8 | `HistoryStrip` (DateAxis, linked X, follow) + smoke | T2,T4 |
| T9 | `app.py` bento + main + smoke | T1,T5–T8 |
| T10 | `kokpit.desktop` + entry point | T9 |

## 6. Testy (spec główny §8)
- Logika poza Qt → realne unit-testy: `live_client` (sklejanie ramek, reconnect, drop), `history_model` (wybór okna, granica raw↔rollup, fallback `list_series`), mapowanie heatmapy.
- Widgety → smoke na danych przykładowych pod `QT_QPA_PLATFORM=offscreen` (headless).

## 7. Obsługa błędów / odporność
- Demon padł → UI „disconnected/stale", **historia z SQLite działa** (`list_series`+`query`), auto-reconnect.
- NVML/GPU n/a → kafel „n/a", brak crasha. Per-proc VRAM `n/a` → tabela znosi.
- Pusta historia / pierwszy run → placeholder „brak danych".
- Częściowe ramki NDJSON → bufor sklejający; wolny/martwy socket → reconnect.

## 8. Decyzje zamrożone w tym addendum
- Spike W2 = **Task 0 blokujący** (na maszynie docelowej).
- `query_rollup` + `list_series` = **sesja backendowa** (kontrakt zapisany); selektor okna i stitching live+historia = frontend (`history_model.py`).
- Dolny pasek historii **„dożywa"** do teraz (follow mode), z auto-pauzą na pan/zoom.
- Heatmapa = **dwa gridy obok siebie** (util32 / temp24), bez mapowania phys→wątki w MVP.

## 9. Poza zakresem Planu 2 (spec główny §12 „Później")
Multi-host, mini-wskaźnik w panelu (GTK3/Ayatana), shadery GLSL glow, rollup roczny, overlay heatmapy z mapowaniem phys→wątki.
