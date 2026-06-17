# kokpit — natywny dashboard telemetrii systemu — Design

**Wersja:** 1.1
**Data:** 2026-06-17
**Status:** Draft — po adwersaryjnym review (do akceptacji)

> v1.1 wprowadza poprawki z adwersaryjnego review (zweryfikowane na maszynie docelowej):
> kontrakt źródeł stateful dla delt bps (K1), realistyczny model kontencji SQLite WAL (K2),
> `nvidia-ml-py` zamiast `pynvml` (W1), wydajność UI jako spike a nie pewnik (W2),
> rozdział util(32)/temp(24) dla P/E-core (W3), VRAM per-proces przez NVML (W4),
> `series_id` + batch insert, migracje schematu, NDJSON/broadcast socketu, lingering, filtrowanie iface.

---

## 1. Cel

Natywna aplikacja desktopowa „mission control" pokazująca w czasie rzeczywistym
obciążenie tej maszyny (CPU, GPU, RAM/dyski, sieć, procesy, temperatury) oraz
historię tych metryk na wykresach — w gęstej, neonowej estetyce „NOC video-wall".
Trzymana na drugim monitorze / wirtualnym pulpicie, „wpięta w OS" przez
autostartujący demon zbierający dane w tle.

### Maszyna docelowa (rekonesans + weryfikacja 2026-06-17)
- CPU: Intel i9-13900KF — **24 fizyczne rdzenie (8 P z HT + 16 E), 32 wątki**. Pod obciążeniem pakiet ~97°C (high=80, crit=100).
  `coretemp` udostępnia **24 czujniki „Core N"** (per fizyczny rdzeń, numeracja nieciągła: 0,4,8,12…).
- GPU: NVIDIA RTX 4060 Ti 16GB, driver 560.35.03 → NVML/`nvidia-smi` dostępne (jako user, bez roota).
- OS: Ubuntu 24.04, KDE Plasma 5.27.12, X11, Qt 5.15. `lm-sensors` 3.6.0 — `sensors -j` daje czysty JSON (exit 0).
- `$XDG_RUNTIME_DIR` = `/run/user/1000`, `drwx------` → socket dziedziczy dostęp tylko-właściciel.
- `psutil` widzi 22 interfejsy sieciowe (docker0, veth*, br-*, tailscale0, lo…) → wymaga filtrowania.
- Żaden z `nvidia-ml-py / PySide6 / pyqtgraph` nie jest jeszcze zainstalowany → czysty bootstrap `.venv`.

## 2. Zamrożone decyzje

| Decyzja | Wybór | Uzasadnienie |
|---|---|---|
| Forma | Standalone „mission control" (natywne okno) | Maksimum swobody na bogate wykresy live+historia |
| Zakres | Tylko ta maszyna, z cienką abstrakcją `Host` | Wymaganie dotyczy lokalnego OS; abstrakcja nie zamyka drogi do multi-host |
| Historia | SQLite (WAL) + rollupy + żywy ring-buffer w RAM | Trwała historia bez zewnętrznych demonów; sweet spot single-host |
| Metryki | CPU · GPU · RAM+dyski · sieć+procesy | Pełen zakres „wypasiony" |
| Stack renderujący | PySide6 (Qt6) + pyqtgraph, natywnie | Najdojrzalszy realtime-plotting w Pythonie; zoom/pan po historii za darmo |
| `/frontend-design` | **Wyłączony z flow** | To skill webowy — nie stylizuje Qt; wygląd robimy natywnie (QSS + styling pyqtgraph) |
| Layout | Bento NOC grid | Maksymalna gęstość, „video-wall" |
| Styl wizualny | Cyberpunk neon / NOC | Czerń + neon + glow; duch `ghostty-vitals`; alerty świecą |

## 3. Architektura — dwa odrębne procesy

Demon-kolektor jest oddzielony od UI. Gdyby zbieranie żyło w aplikacji GUI,
historia powstawałaby tylko gdy okno jest otwarte — a wymaganie to „co działo się
w nocy". Rozdzielenie czyni demon jedynym źródłem prawdy o danych, a UI czystym
konsumentem. To też realizuje „wpięty w OS": demon autostartuje, okno odpalasz gdy chcesz popatrzeć.

```
┌─ kokpit-collectord  (systemd --user + linger, zawsze żyje) ───────┐
│  sources/* (stateful)  →  store (SQLite WAL, 1 tx/tick)            │
│             →  rollupy + retencja + checkpoint (TYLKO writer)      │
│             →  live snapshot  →  Unix socket (NDJSON, broadcast)   │
└───────────────────────────────────────────────────────────────────┘
            │ live: Unix socket            │ historia: SQLite (krótkie read-tx)
            ▼                              ▼
   ┌─ kokpit  (PySide6 + pyqtgraph, bento NOC grid, neon theme) ─┐
   │  live_client (socket, auto-reconnect)  ·  history_model      │
   └──────────────────────────────────────────────────────────────┘
```

## 4. Komponenty (dobrze odgraniczone jednostki)

### 4.1 `sources/` — adaptery źródeł danych

**Kontrakt (poprawka K1 — źródła są STATEFUL tam, gdzie liczą prędkości):**
`Source.sample(now_ms) -> dict[str, float]`. Źródła oparte na **licznikach kumulatywnych**
(sieć, dyski) trzymają stan poprzedniego ticku (`self._last`) i zwracają już policzone prędkości:
`bps = max(0, value - prev) / dt`, gdzie `dt` = **zmierzony** odstęp ticków (nie nominalny 1.0).
Pierwszy tick po starcie **pomija** serie `*_bps` (brak poprzedniej próbki). Ujemna delta
(reset licznika / hotplug / restart iface) jest clampowana do 0.

| Moduł | Backend | Serie (przykłady) | Uwagi |
|---|---|---|---|
| `cpu.py` | psutil | `cpu.thread.{0..31}.util`, `cpu.thread.{n}.freq`, `cpu.loadavg.1` | 32 wątki (`percpu=True`) |
| `gpu.py` | **nvidia-ml-py** (import `pynvml`) | `gpu.{i}.util`, `.vram_used`, `.vram_total`, `.temp`, `.power`, `.clock_sm`, `.fan` | iteruje `nvmlDeviceGetCount()` (0/multi-GPU); kafel „n/a" gdy brak |
| `thermal.py` | `sensors -j` | `thermal.core.{phys}` (24, per fizyczny rdzeń), `thermal.pkg`, `thermal.nvme.{0,1}`, `thermal.wifi` | mapowanie „Core N"→fizyczny rdzeń→{wątki} (patrz §4.4) |
| `memory.py` | psutil | `mem.used`, `mem.total`, `swap.used` | |
| `disk.py` | psutil (stateful) | `disk.{dev}.read_bps`, `.write_bps`, `disk.{mount}.used_pct` | delta liczników; filtr `loop*` |
| `net.py` | psutil (stateful) | `net.{iface}.rx_bps`, `.tx_bps` | delta liczników; filtr `lo/veth*/br-*/docker*/tailscale*/*warp*` |
| `proc.py` | psutil (CPU/RAM) **+ NVML (VRAM)** | top-N procesów (lista, nie serie czasowe) | VRAM przez `nvmlDevice*RunningProcesses`, merge po PID, `n/a` gdy NVML zwróci brak |

**Filtrowanie (poprawka D3):** sieć/dyski pomijają interfejsy/urządzenia wirtualne wg listy reguł (konfigurowalnej).

**Abstrakcja hosta:** interfejs `Host.collect() -> Snapshot`. `LocalHost` teraz; zdalny = nowa implementacja później (nie budujemy).

### 4.2 `store/` — warstwa trwałości
- Schemat SQLite (WAL), słownik serii, writer (batch), job rollupów + retencji + **checkpoint (tylko writer)**, API zapytań (`query(series, since, until)`), migracje (`PRAGMA user_version`).

### 4.3 `collectord/` — demon
- Pętla 1 Hz: dla każdego źródła `sample(now_ms)` z **izolacją błędów per-source** (wyjątek → log do journald + pominięcie ticku tego źródła), zapis **wszystkich serii ticku w JEDNEJ transakcji** (`executemany`), publikacja live snapshotu na socket.
- Osobny harmonogram: rollup `sample`→`rollup_1m`, prune wg retencji, `wal_checkpoint(TRUNCATE)`.

### 4.4 `ui/` — aplikacja PySide6
- `app.py` — główne okno, bento NOC grid (layout A).
- `widgets/` — `CoreHeatmap` (**util: 32 komórki per wątek**; **temp: 24 komórki per fizyczny rdzeń** — osobna warstwa/overlay, mapowanie `thermal.core.{phys}`), `GpuPanel` (util/VRAM/power/temp/fan/zegary, per-GPU), `Gauge`, `Sparkline` (oś X = sliding window „ostatnie N s"), `HistoryStrip` (stos wykresów, wspólna oś czasu).
- `theme/` — neon QSS + styling pyqtgraph (pens z glow), progi-kolory alertów.
- `live_client.py` — klient Unix socketu, NDJSON, auto-reconnect z backoffem.
- `history_model.py` — **krótkie, samodzielne read-transakcje** (open→SELECT→close), bez `immutable`, bez wiecznego połączenia.

### 4.5 `packaging/`
- Unit `systemd --user` dla `kokpit-collectord` (enabled). **`loginctl enable-linger $USER`** — bez tego demon ginie po wylogowaniu i nie ma danych „w nocy" (świadoma decyzja, patrz §13).
- `.desktop` launcher dla UI `kokpit`. UI startujące przed demonem → auto-reconnect to pokrywa.
- Logowanie: stderr → journald (`journalctl --user -u kokpit-collectord`).

## 5. Model danych (SQLite)

Format „long/narrow" z **słownikiem serii** (poprawka S3 — `series_id INTEGER` zamiast powtarzanego `series TEXT`).

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;        -- bezpieczne w WAL, tańsze I/O
PRAGMA user_version = 1;             -- wersjonowanie schematu (migracje stepwise na starcie)

CREATE TABLE series_dict (
  id   INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE          -- np. 'gpu.0.util', 'cpu.thread.7.util'
);

-- surowe próbki (retencja 48h). 1 transakcja/tick (executemany).
CREATE TABLE sample (
  ts        INTEGER NOT NULL,        -- epoch ms
  series_id INTEGER NOT NULL REFERENCES series_dict(id),
  value     REAL    NOT NULL,
  PRIMARY KEY (series_id, ts)
) WITHOUT ROWID;

-- rollup 1-minutowy (retencja 30 dni). bucket = floor(ts/60000)*60000 (epoch, DST-safe).
CREATE TABLE rollup_1m (
  bucket    INTEGER NOT NULL,
  series_id INTEGER NOT NULL REFERENCES series_dict(id),
  vmin REAL, vmax REAL, vavg REAL, vlast REAL,
  PRIMARY KEY (series_id, bucket)
) WITHOUT ROWID;
```

**Wolumen (oszacowanie):** ~120 serii × 1 Hz × 48 h ≈ **~20.7 mln wierszy** w `sample`. `series_id INTEGER` (zamiast długiego TEXT w PK `WITHOUT ROWID`) drastycznie zmniejsza rozmiar i koszt indeksu.

**Model kontencji (poprawka K2):** writer (demon) jest jedynym checkpointerem (`wal_checkpoint(TRUNCATE)` periodycznie + rozsądny `wal_autocheckpoint`). UI robi **krótkie read-transakcje**, nie trzyma wiecznego połączenia, nie używa `immutable` → świeże dane + brak checkpoint-starvation. „Brak kontencji" zastąpione: *minimalna kontencja przy krótkich read-tx*.

**Live snapshot (socket):** `SOCK_STREAM`, **newline-delimited JSON** (jeden snapshot/linia): `{"ts":…, "series": {"gpu.0.util": 63.0, …}}`. Demon akceptuje N połączeń i **broadcastuje**; wolny/martwy klient → drop snapshotu dla niego (nie blokuje pętli). Live **nie** czyta z SQLite.

## 6. Przepływ danych
- **Co 1 s:** demon próbkuje (stateful delty dla bps) → 1 transakcja do `sample` + push live snapshotu (NDJSON) na socket.
- **Rollupy:** `sample` (48 h) → `rollup_1m` (30 dni); prune + checkpoint w tle.
- **UI live:** subskrypcja socketu (1 Hz = tempo danych) → gauge'e, heatmapa, żywe sparkline (`setData` na ring-bufferze, sliding window). **Render ~10–15 fps** (dane są 1 Hz; 60 fps to nie cel) — dokładny budżet/fps i decyzja o `useOpenGL` dopiero po spike (§13).
- **UI historia:** okna 1h / 6h / 24h / 7d z `rollup_1m`, zoom/pan, dolny pasek zsynchronizowany w czasie; oś X konwertuje epoch→local tylko do wyświetlania.

## 7. Obsługa błędów / odporność
- **bps:** pierwszy tick → brak serii bps; reset/hotplug licznika → clamp `max(0, Δ)`; `dt` mierzony, nie nominalny.
- NVML/GPU błąd → kafel GPU „n/a", brak crasha. Per-proces VRAM może być `n/a` (NVML) — UI to znosi. Brakujący chip w `sensors` → pomiń serię.
- Demon padł gdy UI startuje → UI „disconnected/stale", **historia z SQLite działa**; auto-reconnect socketu.
- **Stale socket:** demon na starcie `unlink` istniejącego pliku socketu przed `bind`; fallback ścieżki gdy brak `$XDG_RUNTIME_DIR`.
- Wyjątek w jednym `source` łapany per-source → nie wywala pętli.
- **Pierwszy run / pusta historia:** UI pokazuje placeholder „brak danych", nie pusty/błędny wykres.
- Progi alertów z `sensors` (CPU high=80 / crit=100): zielony < high, amber high–crit, czerwony ≥ ~crit. Konfigurowalne.

## 8. Testy (TDD)
- Unit per `source`: zamockowany output psutil / `nvidia-ml-py` / `sensors -j` → asercja znormalizowanego dicta serii.
- **Delty bps:** pierwszy tick (brak serii), reset licznika (clamp), jitter `dt` (dzielenie przez zmierzony odstęp).
- **Mapowanie temp:** `coretemp "Core N"` (24, nieciągłe) → fizyczny rdzeń → {wątki}.
- `store`: insert → rollup → query (poprawność agregatów); retencja/prune; **migracja `user_version`**.
- **Protokół socketu:** NDJSON serializacja/deserializacja, sklejanie ramek w buforze, reconnect, drop wolnego klienta.
- UI cienkie (logika poza Qt) → smoke-testy widgetów na danych przykładowych.

## 9. Bezpieczeństwo
- Socket w `$XDG_RUNTIME_DIR` (katalog `drwx------`) → dostęp tylko-właściciel; **bez SO_PEERCRED, bez roota**. Zweryfikowane.
- Demon **nie wymaga uprawnień podniesionych**: `/sys`/hwmon i NVML czytane jako user (zweryfikowane: `sensors -j` i `nvidia-smi` działają bez sudo).
- Brak nasłuchu sieciowego (tylko Unix socket lokalny).

## 10. Stack i zależności
- Python 3.12 (Ubuntu 24.04), `pyproject.toml`, `.venv` (wzorzec jak w `ghostty-vitals`).
- Runtime: `PySide6`, `pyqtgraph`, `psutil`, **`nvidia-ml-py`** (NIE `pynvml` — deprecated; import w kodzie dalej `pynvml`). Temperatury: subprocess `sensors -j` (podstawa; hwmon sysfs jako ewentualna optymalizacja później, nie „lub").
- Test: `pytest`.

## 11. Domyślne wartości (konfigurowalne)
- Próbkowanie: **1 Hz**. Live socket: **= tempo próbkowania (1 Hz)**. Render UI: **~10–15 fps** (do potwierdzenia spike'em).
- Retencja raw: **48 h**. `rollup_1m`: **30 dni**.
- Katalog projektu: `~/Code/kokpit`. Dane: `~/.local/share/kokpit/kokpit.db`. Socket: `$XDG_RUNTIME_DIR/kokpit.sock`.

## 12. Zakres

### MVP
- `kokpit-collectord`: 4 wiązki źródeł (stateful delty), SQLite WAL + słownik serii + batch tx, rollup_1m, retencja+checkpoint, live socket (NDJSON/broadcast), migracje schematu.
- `kokpit` UI: bento NOC grid (neon), live + historia, wszystkie 4 wiązki; util(32)/temp(24) rozdzielone.
- Autostart demona (`systemd --user` + linger), `.desktop` dla UI.

### Później (NIE w MVP)
- Multi-host (agregacja zdalnych maszyn).
- Mini-wskaźnik w panelu (GTK3 + Ayatana AppIndicator wg wzorca `gitlab-runner-tray` — omija pułapkę Qt6/Plasma 5).
- Shadery GLSL glow (start na efektach QSS/Qt).
- Rollup roczny / hwmon zamiast `sensors -j`.

## 13. Spike'i / decyzje przed planem
- **W2 — wydajność pyqtgraph (SPIKE):** zmierzyć render ~32 sparkline + heatmapa + gauge'e na tej maszynie; dźwignie: jeden `ViewBox`/wiele krzywych gdzie się da, wyłączony auto-range w live, `setDownsampling(auto=True, mode='peak')` + `clipToView=True`, `useOpenGL` **tylko po pomiarze**. Cel: budżet renderu, nie 60 fps.
- **Lingering — decyzja:** włączamy `enable-linger` (domyślnie TAK), żeby „nocna" historia działała nawet po wylogowaniu. Jeśli stacja zawsze zalogowana — można pominąć.
- **`series_id` vs `series TEXT`:** przyjęte `series_id INTEGER` (rozmiar/koszt PK). Akceptuje minimalnie bardziej złożony schemat.

## 14. Pytania otwarte
Brak blokujących. Nazwa „kokpit", retencje/cadence, render-fps i decyzja o lingerze są łatwo zmienialne przed startem implementacji.
