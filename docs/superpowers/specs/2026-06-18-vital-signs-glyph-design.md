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
  czysty z-score) zamiast agregowania `cpu.thread.*.util`.
- **Swap**: `swap.total` nie jest składowany → brak czystej proximity; sam z-score
  (nagły wzrost swap = zaskoczenie). Każda aktywność swap na maszynie z zapasem RAM
  i tak da wysoki z-score względem baseline ≈ 0.
- **RAM proximity** = bieżące `mem.used / mem.total` (oba w live-snapshocie);
  z-score liczony na `mem.used` (bajty).
- Progi limitów (95/90 °C itd.) → stałe w `config.py` lub w tabeli osi `glyph_model`.

## 3. Definicja score'u

Dla pojedynczej serii-członka:

```
z      = 0 if sigma < EPS else (value - mean) / sigma     # guard: σ≈0 ⇒ z=0
z_norm = clamp(z / Z_FULL, 0, 1)                           # Z_FULL np. 3.0 σ = pełny kolec
prox   = clamp(value / limit, 0, 1)   if limit else 0.0
spike  = max(z_norm, prox)            # dla osi z limitem
spike  = z_norm                       # dla osi bez limitu
```

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
def baseline(self, series: str, now_ms: int, min_samples: int = 10) -> tuple | None:
    """(mean, sigma, n) dla serii względem rollup_1m, albo None gdy za mało danych.

    Circadian: agreguje vavg z bucketów o tej samej godzinie-tygodnia co now_ms
    (ostatnie ROLLUP_RETENTION). Gdy n < min_samples → fallback globalny (ostatnie
    7 dni, dowolna pora). Dalej za mało → None.
    """
```

- Hour-of-week w SQL: `CAST(strftime('%w', bucket/1000,'unixepoch','localtime') AS INT)*24
  + CAST(strftime('%H', bucket/1000,'unixepoch','localtime') AS INT)`; ten sam wzór
  na `now_ms` daje bieżącą hour-of-week (porównanie w `WHERE`).
- mean/σ: `AVG(vavg)`, `AVG(vavg*vavg)` → `sigma = sqrt(max(0, E[x²] - E[x]²))`.
- Czysty dopisek w klasie `Store` pod `list_series()` — bez zmian w schemacie,
  `write()`, `rollup_1m()`, `prune()`. (Spójne z konwencją kontraktu store-history-api.)
- **strftime 'localtime'** zależy od strefy hosta — akceptowalne dla single-machine.

### 4.2 `kokpit/ui/glyph_model.py` (nowy, czysty Python — bez importu Qt)

- Tabela definicji osi (nazwa, wzorzec/lista serii, czy z-only, limit).
- `spike_score(value, baseline, limit) -> float` (wzór z §3).
- Odkrywanie dynamicznych członków rodziny z kluczy live-snapshotu (i/lub
  `Store.list_series(prefix)` gdy demon nie żyje).
- Agregacja worst-of → `list[SpokeScore]` (nazwa osi, score 0..1, wartość surowa do
  tooltipa, flaga „brak danych").
- Wejście: snapshot (dict serii→wartość) + baseline-provider (callable
  `series → (mean,σ,n)|None`). **W pełni testowalne bez Qt.**

### 4.3 `kokpit/ui/widgets/vital_glyph.py` (nowy QWidget)

- `paintEvent` rysuje wielokąt z `list[SpokeScore]` (QPainter, jak inne widgety):
  N ramion równomiernie po okręgu, promień wierzchołka = `R_base + score * R_span`.
- Kolor ramienia: `palette.util_rgb` / eskalacja `alert_color` wg score.
- `palette.apply_glow` na wierzchołkach przekraczających próg.
- Faint „baseline ring" = referencyjny spokojny wielokąt (wszystkie score=0) dla oka.
- Centrum: skalar zdrowia = `max(score)` (lub RMS) + krótka etykieta.

### 4.4 Wpięcie w `kokpit/ui/app.py`

- Glif jako hero-element layoutu (dokładne miejsce w planie — obok/zamiast części ringów).

## 5. Data flow

- **Live wartości:** 1 Hz z istniejącego `live_client` (NDJSON socket) — bez zmian.
- **Baseline'y:** zmieniają się wolno → **cache w pamięci, recompute co 60 s oraz
  przy zmianie hour-of-week**. Glif przerysowuje się 1 Hz: świeże wartości ×
  cache'owany baseline. Recompute baseline'ów (zapytania SQL) NIE leci co klatkę.

## 6. Degradacja / cold-start

- **Świeża maszyna (brak rollup):** wszystkie baseline `None` → glif w stanie
  „calibrating" (DIM, spokojny wielokąt). Proximity dla osi z limitem (temp/RAM/VRAM)
  **nadal działa** — nie wymaga historii.
- **Demon nie żyje:** live-snapshot pusty → glif DIM; baseline ze Store nadal czytelny
  z DB (read-only).
- **σ≈0 / pojedyncza próbka:** guard z §3 (z=0), brak dzielenia przez zero.

## 7. Testy (TDD, RED → GREEN)

- `tests/test_store.py` (dopisać): `baseline` — syntetyczny rollup o znanej
  hour-of-week → poprawne mean/σ/n; `n < min_samples` → fallback 7d; pusty zakres →
  `None`; seria stała → σ=0 zwrócone (guard po stronie konsumenta).
- `tests/test_glyph_model.py` (nowy): czysty z dla unbounded; `max(z,prox)` dla
  bounded; σ≈0 ⇒ proximity dominuje; baseline `None` ⇒ proximity-only / „brak danych";
  agregacja worst-of po rodzinie; dynamiczne odkrywanie członków; ujemny z (spadek) ⇒
  score 0.
- `tests/test_vital_glyph.py` (nowy): smoke — render N ramion do QImage; geometria
  calm (regularny wielokąt) vs spiked (jeden wydłużony wierzchołek) przez promienie;
  brak crasha na cold-start / `None` / pusty snapshot.

## 8. Świadomie poza zakresem v1 (YAGNI)

- Stożek prognozy („VRAM uderzy w 100% za ~40 s") — komponuje się, ale osobny spec.
- Sonifikacja (ambient audio, warstwa A z brainstormu) — osobny feature.
- Plasmoid / shared backend baseline — odrzucone na etapie wyboru placementu.
- Łapanie *spadków* (gwałtowny spadek IO = zawieszenie) — tylko wzrosty w v1.

## 9. Stałe konfiguracyjne (do `config.py` lub `glyph_model`)

- `Z_FULL` (np. 3.0) — z-score dający pełny kolec.
- `EPS_SIGMA` — próg „σ≈0".
- Limity: CPU temp 95 °C, GPU temp 90 °C, RAM/VRAM 100%.
- `BASELINE_REFRESH_S` = 60, `BASELINE_MIN_SAMPLES` = 10, fallback window = 7 dni.
- Próg glow na wierzchołku (np. score ≥ 0.5).
