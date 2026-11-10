# ThreadStar — przyjazna animowana rozgwiazda wątków CPU

**Data:** 2026-06-19
**Status:** Design (zatwierdzony do planu implementacji)
**Branch wyjściowy:** `fix/glyph-drag-feedback`

## 1. Cel

Nowy widget UI `ThreadStar` — żywa, organiczna **rozgwiazda**, w której **każde ramię
reprezentuje utilizację jednego wątku (logicznego rdzenia) CPU**. Widget jest
**osobny** od istniejącego `VitalGlyph` (którego ramiona to metryki-vitalsy, nie wątki)
i ma wyglądać **przyjaźnie** — nie przez twarz/maskotkę, lecz przez pulchny, zaokrąglony
kształt, miękkie kolory utilu i delikatną, „żywą" animację.

Dane już istnieją w kolektorze: `CpuSource` emituje `cpu.thread.<i>.util`
(`kokpit/sources/cpu.py:10-11`), dostępne w `snap["series"]` w `MainWindow._on_snapshot`.

## 2. Zakres

- [ ] Nowy widget `kokpit/ui/widgets/thread_star.py` (`ThreadStar(QWidget)`).
- [ ] Dynamiczne wykrycie liczby wątków z kluczy `cpu.thread.<i>.util` (8/16/32… — bez hardcode).
- [ ] Organiczne ramiona (Bézier, zaokrąglony czubek), długość = util, kolor = rampa `util_rgb`.
- [ ] Animacja: easing długości ku targetowi + ciągły „oddech"/kołysanie (idle alive).
- [ ] Integracja: jedna linijka w `_on_snapshot`, umieszczony w lewej kolumnie pod `CORES`.
- [ ] Testy TDD (RED→GREEN) na czystych funkcjach geometrii/animacji + smoke paint.
- ❌ Buźka/maskotka (świadomie poza zakresem — friendly robimy kształtem i ruchem).
- ❌ Drag-to-cap (to feature VitalGlyph; ThreadStar jest read-only wizualizacją).

## 3. Architektura i granice

Widget czysto prezentacyjny, wzorowany na strukturze `VitalGlyph`
(`kokpit/ui/widgets/vital_glyph.py`): rozdzielone **czyste funkcje** (testowalne bez Qt
event-loop) od `paintEvent`.

### 3.1 Wejście danych

```python
def set_threads(self, series: dict) -> None
```
- Wyłuskuje wątki z `series` przez nowy helper `thread_count(series) -> int`
  i `thread_util_keys(n)` (już istnieje w `kokpit/ui/widgets/heatmap.py`).
- Konwertuje util% → frakcja 0..1 (`v/100`, clamp). Brak klucza → 0.0 (ramię stub).
- Ustawia `self._target`; przy zmianie liczby wątków snapuje `self._current` (jak
  `VitalGlyph.set_spokes`, by uniknąć IndexError na zmianie długości).

`thread_count(series)` (nowy, w `heatmap.py` obok `thread_util_keys`): liczy klucze
pasujące do `cpu.thread.<i>.util` i zwraca `max(i)+1` (latch — siatka nie kurczy się,
gdy wątek chwilowo zniknie), albo 0 gdy brak.

### 3.2 Geometria ramienia

- Ramię `i` na kącie `θ_i = -π/2 + 2π·i/n` (start u góry, zgodnie z zegarem — jak glyph).
- Długość: `L_i = body_r + span · frac_i`, gdzie `body_r` = promień ciała, `span` skaluje
  się do widgetu (jak `VitalGlyph._scale`, z marginesem).
- Kształt ramienia: **wypełniony `QPainterPath`** — od lewego boku bazy (szeroki),
  dwiema krzywymi `quadTo`/`cubicTo` wybrzuszonymi na zewnątrz do **zaokrąglonego czubka**,
  z powrotem do prawego boku bazy. Czubek zaokrąglony (friendly), nie ostry.
- Czysta funkcja `arm_path(cx, cy, i, n, body_r, length, base_half_w) -> QPainterPath`
  (testowalna: sprawdzamy długość = odległość czubka od środka, kierunek = θ_i).

### 3.3 Kolor

- Rampa `util_rgb(frac)` z `kokpit/ui/theme/palette.py` (zieleń→bursztyn→czerwień).
- Wypełnienie: `QRadialGradient` od koloru ciała (przygaszony) do koloru utilu na czubku.
- Bloom (gruby półprzezroczysty pen) dla ramion `frac >= GLOW_THRESHOLD` — jak w glyph.

### 3.4 Animacja

Dwa źródła ruchu, oba na jednym `QTimer` (interval ~25 ms ≈ 40 fps, jak glyph):

1. **Easing danych**: `current[i] += (target[i]-current[i])·EASE` (EASE≈0.25).
   Po osiągnięciu `SETTLE_EPS` na wszystkich ramionach — easing „śpi", ale…
2. **Oddech/idle (alive)**: faza `self._phase` rośnie co tick; modeluje:
   - delikatny puls `body_r` (sinus, amplituda ~kilka px),
   - subtelne kołysanie kąta każdego ramienia (sinus z przesunięciem fazy `i`),
   tak że rozgwiazda „żyje" nawet przy zerowym utilu.
   Timer **nie zatrzymuje się** (w przeciwieństwie do glyph), bo oddech jest ciągły —
   ale to tani jeden `update()` na 25 ms, jeden paint na snapshot-tempie.

Czyste funkcje: `ease_step(current, target, eps) -> (next, moving)` oraz
`breath_offset(phase, i, n) -> (dr, dθ)` — testowalne bez Qt.

## 4. Integracja

`kokpit/ui/app.py`:
- Import + `self._thread_star = ThreadStar()` w `__init__`.
- W layoucie lewej kolumny (`zone_vitals`, `zv`) dodać pod `CORES`:
  `zv.addWidget(_titled("threads", NEON_CYAN, "THREADS", self._thread_star))`.
- W `_on_snapshot` jedna linijka: `self._thread_star.set_threads(s)`.

CORES może zostać usunięte później — ThreadStar jest jego docelowym następcą wizualnym.

## 5. Obsługa błędów / przypadki brzegowe

- `n == 0` (brak wątków w serii): `paintEvent` i `set_threads` robią early-return, brak crashu.
- Zmiana liczby wątków między snapshotami: snap `current`, reset ewentualnych buforów.
- Brak konkretnego klucza wątku: traktuj jak 0.0 (krótkie ramię), nie wyrzucaj.
- Widget bardzo mały: `span`/`body_r` skalują się do `min(w,h)/2` z marginesem; nigdy < 0.

## 6. Testy (TDD)

`tests/ui/test_thread_star.py` (offscreen Qt, jak istniejące testy widgetów):

1. `thread_count` zwraca poprawne N z serii (gęstej i dziurawej), 0 dla pustej.
2. `set_threads` ustawia `_target` jako frakcje 0..1 (clamp z util%).
3. Zmiana liczby wątków snapuje `_current` (brak IndexError).
4. `arm_path`: czubek na promieniu = `body_r + span·frac`, kierunek = `θ_i` (±tol).
5. `ease_step`: zbiega monotonicznie do targetu; flaga `moving` False po settle.
6. `breath_offset`: zwrócone przesunięcia ograniczone amplitudą (|dr| ≤ A_r, |dθ| ≤ A_θ) dla dowolnej fazy.
7. Smoke: `ThreadStar` z N=16 renderuje paint bez wyjątku; N=0 nie crashuje.

`.venv/bin/pytest -q` w całości zielony przed MR.

## 7. Poza zakresem (YAGNI)

- Twarz/maskotka, mruganie, mapowanie nastroju (świadomie odrzucone w brainstormie).
- Interakcja myszą / drag-to-cap (read-only widget).
- Per-thread freq/temp na ramieniu (na razie tylko util; rozszerzenie na przyszłość).
