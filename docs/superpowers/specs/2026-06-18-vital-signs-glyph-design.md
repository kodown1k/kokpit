# Vital-Signs Glyph — design

**Data:** 2026-06-18
**Status:** Zaakceptowany (do implementacji)
**Branch docelowy:** nowy feature branch z `main` (np. `feat/ui-vital-glyph`)
**Placement:** aplikacja desktop PySide6 (`kokpit/ui`)

---

## 1. Cel produktu

Jeden hero-widget: wielokąt (gwiazda) o N ramionach, gdzie **długość ramienia =
„zaskoczenie" danej osi względem baseline TEJ maszyny o TEJ porze tygodnia** —
a nie wartość surowa. Zdrowa maszyna = spokojny regularny wielokąt; anomalia =
kolec na konkretnej osi, percepowany pre-atentywnie (<200 ms) bez czytania liczb.

**Dlaczego niekonwencjonalne (uzasadnienie z brainstormu):** koduje *zaskoczenie*,
nie *poziom*. Pyta „czy 60% CPU jest normalne dla tej maszyny teraz?", a nie
pokazuje surowe 60%. Transplant z monitoringu ICU (zintegrowany glif vitalsów,
percepcja deformacji kształtu). Wykorzystuje martwy już constraint „mało historii /
brak lokalnego ML" — kokpit MA `rollup_1m` (30 dni retencji) i może liczyć baseline.

Konwencjonalna alternatywa (kolejne ring-gauge'y pokazujące surowe %) świadomie
odrzucona — kokpit już je ma; dźwignia leży w *co* kodujemy (zaskoczenie), nie
*jak ładnie* rysujemy tarczę.

## 2. Osie glifu (9 ramion)

Każda oś mapuje na **rodzinę serii**; agregat to **worst-of** po członkach rodziny
(glif anomalii — świeci najgorszy rdzeń / dysk / interfejs).

| Oś       | Serie (rodzina)                     | Score             | Limit (proximity) |
|----------|-------------------------------------|-------------------|-------------------|
| CPU      | `cpu.loadavg.1`                     | z-score           | —                 |
| RAM      | `mem.used` (z) + `mem.used/mem.total` | max(z, prox)    | 100%              |
| Swap     | `swap.used`                         | z-score           | — (>0 = sygnał)   |
| GPU      | `gpu.*.util`                        | z-score           | —                 |
| VRAM     | `gpu.*.vram_used / gpu.*.vram_total` | max(z, prox)     | 100%              |
| CPU temp | `thermal.coretemp.*.pkg`            | max(z, prox)      | ~95 °C            |
| GPU temp | `gpu.*.temp`                        | max(z, prox)      | ~90 °C            |
| Disk IO  | `disk.*.read_bps`, `disk.*.write_bps` | z-score         | —                 |
| Net IO   | `net.*.rx_bps`, `net.*.tx_bps`      | z-score           | —                 |

Uwagi:
- **CPU** używa `cpu.loadavg.1` (pojedyncza seria, naturalny baseline, unbounded →
  czysty z-score) zamiast agregowania `cpu.thread.*.util`. **Known-limitation
  (review HIGH):** loadavg.1 to 1-minutowa średnia krocząca z jądra, więc przy
  bucketach 1-min jest podwójnie wygładzony → kolec CPU będzie tępy/opóźniony.
  Akceptowane w v1; alternatywa do rozważenia: `cpu.thread.*.util` worst-of
  (0–100, reaguje natychmiast).
- **Discovery rodzin = suffix-match, nie prefix (review HIGH).** `disk.` jako prefix
  łapie też `disk.<mount>.used_pct` (0–100, absurdalny z-score w rodzinie IO) — więc
  Disk IO matchuje **wyłącznie** serie kończące się na `.read_bps` / `.write_bps`.
  Dodatkowo bierzemy **tylko całe dyski** (`nvme0n1`, `sda`), NIE partycje
  (`nvme0n1p1`) — IO całego dysku ≈ suma partycji, worst-of double-countowałby.
  Wzorzec dysku: `disk.<dev>.{read,write}_bps` gdzie `<dev>` bez sufiksu `pN`.
- **Swap**: `swap.total` nie jest składowany → brak czystej proximity; sam z-score
  (nagły wzrost swap = zaskoczenie). Każda aktywność swap na maszynie z zapasem RAM
  i tak da wysoki z-score względem baseline ≈ 0.
- **RAM proximity** = bieżące `mem.used / mem.total` (oba w live-snapshocie);
  z-score liczony na `mem.used` (bajty).
- Progi limitów (95/90 °C itd.) → stałe w `config.py` lub w tabeli osi `glyph_model`.

## 3. Definicja score'u

Dla pojedynczej serii-członka:

```
z      = 0 if sigma < EPS else (value_sm - mean) / sigma  # guard: σ≈0 ⇒ z=0
z_norm = clamp(z / Z_FULL, 0, 1)                           # Z_FULL np. 3.0 σ = pełny kolec; ujemne z → 0
prox   = clamp(value / limit, 0, 1)   if limit else 0.0    # proximity z surowej live
spike  = max(z_norm, prox)            # dla osi z limitem
spike  = z_norm                       # dla osi bez limitu
```

- **Dopasowanie granularności (review HIGH).** Baseline σ liczone jest z `vavg`
  (średnich minutowych) → mierzy zmienność *między* minutami, mniejszą niż rozrzut
  surowych próbek 1 Hz. Porównanie surowej live (pełny rozrzut) z taką σ zawyżałoby
  z-score (czulszy niż „3σ surowego sygnału"). Dlatego do **z-score** używamy
  `value_sm` = krótki EWMA live (okno ~30–60 s, half-life ≈ bucket), żeby licznik
  i mianownik były na tej samej granularności. **Proximity** liczymy z **surowej**
  live (chcemy złapać natychmiastowy skok temp/RAM bez wygładzenia). EWMA żyje
  w `glyph_model` (stan per-seria), nie w Store.
- **Guard σ≈0 jest kluczowy:** maszyna która *zawsze* grzeje się do 95 °C ma σ≈0 →
  z=0 (brak zaskoczenia), ale `prox=0.95` → kolec i tak rośnie. Łapie chroniczny
  problem, którego czysty z-score by przeoczył.
- **Baseline `None`** (za mało danych): `z_norm=0`; oś z limitem pokazuje samą
  proximity, oś bez limitu → stan „brak danych" (DIM).
- **Score osi** = `max(spike)` po wszystkich członkach rodziny (worst-of).
- Ujemne z-score (wartość *poniżej* baseline) traktujemy jako spokój — kolec liczymy
  tylko dla odchyleń w górę (`z` przed clampem może być ujemne → clamp do 0).
  Wyjątek do rozważenia w planie: gwałtowny *spadek* IO/util bywa też sygnałem
  (zawieszenie) — v1 NIE łapie spadków (YAGNI), tylko wzrosty.

## 4. Komponenty (izolacja: logika osobno od Qt)

### 4.1 `kokpit/store.py` — nowa metoda `baseline()`

```python
def baseline(self, series: str, now_ms: int, min_samples: int | None = None) -> tuple | None:
    """(mean, sigma, n, tier) dla serii względem rollup_1m, albo None gdy za mało danych.

    Drabina fallbacku (review CRIT-2) — pierwszy poziom z n >= min_samples wygrywa:
      1. 'circadian' — buckety o tej samej godzinie-tygodnia co now_ms (30d).
      2. 'hour'      — ta sama GODZINA doby, dowolny dzień (30d) — wygładza brak
                       danych w konkretnym slocie tygodnia, wciąż respektuje dobę.
      3. 'global'    — dowolna pora, ostatnie 7 dni.
    Żaden poziom nie zbiera min_samples → None. `tier` wraca do UI (etykieta stanu
    'calibrating' dopóki nie osiągniemy 'circadian'). min_samples=None → z configu.
    """
```

- Hour-of-week w SQL: `CAST(strftime('%w', bucket/1000,'unixepoch','localtime') AS INT)*24
  + CAST(strftime('%H', bucket/1000,'unixepoch','localtime') AS INT)`; ten sam wzór
  na `now_ms` daje bieżącą hour-of-week (porównanie w `WHERE`). Tier 'hour' używa
  samego `strftime('%H', ...)`.
- mean/σ: `AVG(vavg)`, `AVG(vavg*vavg)` → `sigma = sqrt(max(0, E[x²] - E[x]²))`.
  (σ jest między-minutowa — patrz dopasowanie granularności w §3.)
- Czysty dopisek w klasie `Store` pod `list_series()` — bez zmian w schemacie,
  `write()`, `rollup_1m()`, `prune()`. (Spójne z konwencją kontraktu store-history-api.)
- **Realna dostępność tieru 'circadian' (review CRIT-2):** pełny slot godzina-tygodnia
  z `min_samples` próbkami wymaga, by ta sama godzina tego samego dnia tygodnia
  powtórzyła się ≥`min_samples` razy → **~tygodnie pracy** (laptop gaszony nocą
  zbiera wolniej). Przez pierwszy okres realnie działa tier 'hour'/'global'. To
  **stan domyślny, nie edge-case** — patrz §6. Drabina degraduje płynnie zamiast
  skakać circadian→global.
- **Known-limitation: `strftime 'localtime'` + DST (review MED).** Strefa hosta —
  akceptowalne dla single-machine. Ale 2× w roku (przejście DST) sloty hour-of-week
  zsuwają się o godzinę względem historii sprzed zmiany → baseline dla godzin
  granicznych jest tego dnia zły. Świadoma decyzja, nie cichy bug; pokryte testem (§7).

### 4.2 `kokpit/ui/glyph_model.py` (nowy, czysty Python — bez importu Qt)

- Tabela definicji osi (nazwa, wzorzec/lista serii, czy z-only, limit).
- `spike_score(value, baseline, limit) -> float` (wzór z §3).
- Odkrywanie dynamicznych członków rodziny z kluczy live-snapshotu (suffix-match,
  §2) i/lub `Store.list_series(prefix)` gdy demon nie żyje.
- Agregacja worst-of → `list[SpokeScore]` (nazwa osi, score 0..1, wartość surowa do
  tooltipa, flaga „brak danych", `tier` baseline).
- **Kształt wejścia (review CRIT-1):** live-snapshot jest ZAGNIEŻDŻONY —
  `{"ts": now_ms, "series": {...}, "procs": [...]}` (`collectord.py` publikuje tak,
  `app.py` czyta `snap["series"]`). glyph_model bierze **`snap["series"]`** jako dict
  serii→wartość, a `now_ms` z **`snap["ts"]`** (potrzebne do hour-of-week i providera).
  NIE traktować całego `snap` jako flat dict — `ts`/`procs` wpadłyby jako fałszywe serie.
- Baseline-provider: callable `series → (mean,σ,n,tier)|None`. **W pełni testowalne
  bez Qt** (provider i snapshot to czyste struktury).

### 4.3 `kokpit/ui/widgets/vital_glyph.py` (nowy QWidget)

- `paintEvent` rysuje wielokąt z `list[SpokeScore]` (QPainter, jak inne widgety):
  N ramion równomiernie po okręgu, promień wierzchołka = `R_base + score * R_span`.
- **Kolor ramienia (review MED):** `palette.util_rgb(score)` — bierze frac 0–1, pasuje
  wprost do score. NIE `alert_color()` bezpośrednio (jego progi to °C: high=80, crit=100);
  jeśli chcemy eskalacji amber→czerwień w skali score, wołać z jawnymi progami
  `alert_color(score, high=0.5, crit=0.8)`.
- **Glow per-ramię (review MED):** `palette.apply_glow` ustawia `QGraphicsDropShadowEffect`
  na CAŁYM widgecie (i sam ostrzega „nie na stosach krzywych") — NIE rysuje glow na
  pojedynczym wierzchołku. Per-ramię glow rysujemy w `paintEvent` (drugi przebieg
  QPainter rozmytym/grubszym pędzlem pod wierzchołkiem). `apply_glow` użyć co najwyżej
  dla glow całego glifu gdy `max(score)` przekroczy próg.
- Faint „baseline ring" = referencyjny spokojny wielokąt (wszystkie score=0) dla oka.
- Centrum: skalar zdrowia = `max(score)` (lub RMS) + krótka etykieta (w tym stan
  `tier`: „calibrating" dopóki baseline nie jest 'circadian').

### 4.4 Wpięcie w `kokpit/ui/app.py`

- Glif jako hero-element layoutu (dokładne miejsce w planie — obok/zamiast części ringów).

## 5. Data flow

- **Live wartości:** 1 Hz z istniejącego `live_client` (NDJSON socket) — bez zmian.
- **Baseline'y:** zmieniają się wolno → **cache w pamięci, recompute co 60 s oraz
  przy zmianie hour-of-week**. Glif przerysowuje się 1 Hz: świeże wartości ×
  cache'owany baseline. Recompute baseline'ów (zapytania SQL) NIE leci co klatkę.

## 6. Degradacja / cold-start

- **Pierwszy okres pracy (review CRIT-2) — to STAN DOMYŚLNY, nie edge-case.** Zanim
  uzbiera się tier 'circadian' (tygodnie), glif działa na 'hour'/'global', a osie
  bez limitu o baseline `None` (CPU, GPU, Swap, Disk, Net — 5 z 9) świecą score 0.
  Realnie przez pierwsze dni glif to **~4-ramienny kształt na proximity** (RAM, VRAM,
  CPU temp, GPU temp), nie 9-ramienny na zaskoczeniu. Centrum pokazuje stan `tier`
  („calibrating"). Testy geometrii (§7) muszą to uwzględnić.
- **Świeża maszyna (brak rollup):** wszystkie baseline `None` → wszystkie osie z-only
  martwe; tylko proximity. Glif „calibrating" (DIM, spokojny wielokąt).
- **Demon nie żyje:** live-snapshot pusty → glif DIM; baseline ze Store nadal czytelny
  z DB (read-only).
- **σ≈0 / pojedyncza próbka:** guard z §3 (z=0), brak dzielenia przez zero.

## 7. Testy (TDD, RED → GREEN)

- `tests/test_store.py` (dopisać): `baseline` — syntetyczny rollup o znanej
  hour-of-week → poprawne mean/σ/n + `tier=='circadian'`; **drabina fallbacku
  (first-class, review CRIT-2/LOW):** slot ma n=3 (<min) ale godzina-doby ma dość →
  zwraca tier 'hour'; tylko global ma dość → tier 'global'; nic → `None`. Pusty
  zakres → `None`; seria stała → σ=0 zwrócone. **DST (review MED/LOW):** test na
  granicy zmiany czasu dokumentujący znane zachowanie 'localtime'.
- `tests/test_glyph_model.py` (nowy): czysty z dla unbounded; `max(z,prox)` dla
  bounded; **EWMA live → z liczony z `value_sm`, proximity z surowej (review HIGH)**;
  σ≈0 ⇒ proximity dominuje; baseline `None` ⇒ proximity-only / „brak danych";
  agregacja worst-of po rodzinie; **discovery suffix-match: `disk.<mount>.used_pct`
  NIE wpada do rodziny Disk IO, partycje pomijane (review HIGH)**; CRIT-1: wejście
  `snap["series"]`/`snap["ts"]` (klucze `ts`/`procs` nie stają się seriami); ujemny z
  (spadek) ⇒ score 0.
- `tests/test_vital_glyph.py` (nowy): smoke — render N ramion do QImage; geometria
  calm (regularny wielokąt) vs spiked (jeden wydłużony wierzchołek) przez promienie;
  **cold-start = 4 aktywne ramiona (proximity-only), reszta R_base (review MED)**;
  brak crasha na `None` / pusty snapshot.

## 8. Świadomie poza zakresem v1 (YAGNI)

- Stożek prognozy („VRAM uderzy w 100% za ~40 s") — komponuje się, ale osobny spec.
- Sonifikacja (ambient audio, warstwa A z brainstormu) — osobny feature.
- Plasmoid / shared backend baseline — odrzucone na etapie wyboru placementu.
- Łapanie *spadków* (gwałtowny spadek IO = zawieszenie) — tylko wzrosty w v1.

## 9. Stałe konfiguracyjne (do `config.py` lub `glyph_model`)

- `Z_FULL` (np. 3.0) — z-score dający pełny kolec.
- `EPS_SIGMA` — próg „σ≈0".
- `LIVE_EWMA_S` (np. 45) — okno wygładzania live dla z-score (dopasowanie granularności, §3).
- Limity: CPU temp 95 °C, GPU temp 90 °C, RAM/VRAM 100%.
- `BASELINE_REFRESH_S` = 60, fallback global window = 7 dni.
- `BASELINE_MIN_SAMPLES` = 10 — **jedyne źródło prawdy**; `Store.baseline(min_samples=None)`
  czyta tę stałą (sygnatura bez zaszytego default, review LOW).
- Próg glow na wierzchołku (np. score ≥ 0.5).
