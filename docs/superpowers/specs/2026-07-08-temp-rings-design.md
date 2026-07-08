# Temperatury w ringach — °C w CORE TEMP + kafle MultiRing (NVMe, CPU/MB)

**Data:** 2026-07-08
**Status:** Zatwierdzony (brainstorming z użytkownikiem, sekcje 1–3 zaakceptowane)

## 1. Cel

Trzy niezależne kawałki podnoszące czytelność temperatur na dashboardzie:

1. Mini-ringi **CORE TEMP** w panelu CORES pokazują liczbową wartość °C w środku
   (blok THREAD UTIL bez zmian).
2. Dwa nowe kafle hero typu multiring: **NVME TEMPS** (jeden ring na dysk NVMe)
   i **CPU/MB TEMPS** (pakiet CPU + płyta główna). Pas hero rośnie do 7 kafli:
   `[CPU][GPU][RAM][VRAM][TEMPS][NVME][CPU/MB]` — istniejący kafel TEMPS zostaje.
3. `ThermalSource` czyta temperaturę płyty głównej z chipa Super I/O (Nuvoton
   NCT67xx, sensor `SYSTIN`) — bez tego `thermal.board` na hostach desktopowych
   bez `pch`/`acpitz` (jak maszyna referencyjna) jest zawsze `None`.

## 2. Warstwa danych — `kokpit/sources/thermal.py`

- Nowa gałąź w `sample()`: chip o nazwie zaczynającej się od `nct` → przeszukaj
  `temp*_input` i weź **wyłącznie** wejście z labelem `SYSTIN`. Filtrowanie po
  labelu jest obowiązkowe: niepodłączone wejścia AUXTIN raportują fikcyjne
  ~112 °C (ten sam wzorzec co filtr `Composite` dla NVMe).
- Priorytet źródła `thermal.board`: **`pch` > `SYSTIN` > `acpitz`**
  (chipset → dedykowany sensor płyty → rozmyta strefa ACPI).
- Klucz `thermal.board` bez zmian → istniejący kafel TEMPS i historia dostają
  MB automatycznie. Schemat bazy nietknięty.

## 3. Widget `MultiRingGauge` — `kokpit/ui/widgets/multi_ring_gauge.py`

Generalizacja `DualRingGauge` na N koncentrycznych ringów. `dual_ring_gauge.py`
zostaje **usunięty**, a TEMPS migruje na nowy widget (jedna ścieżka rysowania
łuków, zero duplikacji).

### API

```python
MultiRingGauge(title: str,
               rings: list[tuple[str, str]],   # [(label, accent_hex), ...] zewn.→wewn.
               high: float | None = None, crit: float | None = None,
               unit: str = "°", vmax: float = 100.0)
  .set_values(values: list[float | None])      # ta sama kolejność zewn.→wewn.
```

- Liczba ringów **stała po konstrukcji** — skład rozstrzygany raz przy starcie
  z `model.available_series("thermal.")` (wzorzec `_has_board` z `app.py`).
  Hotplug dysku nie zmienia kafla do restartu — świadomy trade-off.
- `set_values` defensywnie: brakujące pozycje → `None`, nadmiar ignorowany.
- `None` na pozycji → ring rysuje sam tor, w legendzie `--`.

### Rysowanie

- Łuki od `START_DEG` (import z `ring_gauge`), glow-pass + core-pass,
  `value_color(accent, v, high, crit)` — progi wspólne per kafel.
- Adaptacyjna grubość: `ring_w = min(9.0, 0.6 * R / N)`, gdzie
  `R = side/2 − margines`. N ringów zajmuje maks. 60 % promienia; przy N=2–3
  wychodzi dzisiejsze 9 px, przy większych N ringi cienieją zamiast zjadać
  środek. `ring_width(side, n)` jako czysta funkcja modułowa (testowalna).
- Centrum: N linii `LABEL 72°`, każda w kolorze swojego ringu; wysokość linii
  skaluje się w dół gdy N rośnie. Tytuł na dole jak w Dual.
- Jedna `QVariantAnimation` (450 ms, OutCubic) per ring.

### Instancje w pasie hero

| Kafel | Ringi (zewn.→wewn.) | Progi high/crit |
|---|---|---|
| TEMPS (migracja) | PCI (wifi), MB/SSD (fallback jak dziś) | 75 / 90 |
| NVME TEMPS | N0, N1, … (po jednym na `thermal.nvme.<i>`) | 70 / 80 |
| CPU/MB TEMPS | CPU (pkg; przy 2 socketach CPU0/CPU1), MB (board) | 80 / 90 |

Kafel NVME / CPU-MB powstaje tylko, gdy przy starcie istnieją jego serie
(brak NVMe → kafla nie ma w layoutcie).

## 4. `CoreRingGrid` — liczby °C w bloku CORE TEMP

- Nowa stała `TEMP_CELL = 30` px dla komórek bloku temp (util zostaje na
  `CELL = 17`). Szerokość panelu rośnie o ~80 px — mieści się w strefie
  vitals (stretch 5). Minimalne wymiary przeliczone pod większy blok temp.
- `set_temp()` obok frakcji zapamiętuje surowe °C; `paintEvent` rysuje w środku
  ringu `f"{v:.0f}"` (bez „°C" — jednostka w nagłówku bloku:
  `CORE TEMP °C (24)`), font 7 pt bold, **kolor liczby = kolor łuku**
  (heat ramp).
- `None` → sam tor bez liczby. Nadal jeden `paintEvent`, zero nowych animacji.

## 5. Wiring — `kokpit/ui/app.py`

- Przy starcie (obok `_has_board`): `nvme_keys` i `pkg_keys` posortowane
  z `model.available_series("thermal.")`; budowa kafli warunkowa.
- Pas hero: `top_lay` = `[hero:4][TEMPS:1][NVME:1][CPU/MB:1]`.
- `_on_snapshot`: trzy wywołania `set_values([...])`; TEMPS zachowuje
  dzisiejszy fallback (board `None` → najgorętszy NVMe, label „SSD" wybrany
  przy starcie).

## 6. Testy (TDD, RED→GREEN)

- `test_thermal.py` +2: fake sysfs z `nct6798` (SYSTIN 40 °C + śmieciowe
  AUXTIN 112 °C) → `thermal.board == 40.0`; przypadek z `pch` obecnym →
  wygrywa `pch`.
- `test_multi_ring_gauge.py` (zastępuje `test_dual_ring_gauge.py`):
  przechowywanie wartości, `None`-y, defensywne długości `set_values`,
  render smoke z 3 ringami, jednostkowy test `ring_width(side, n)`.
- `test_core_ring_grid.py`: surowe °C zapamiętane, render smoke z liczbami,
  minimalna szerokość urosła.
- Pełny `.venv/bin/pytest -q` zielony przed MR; potem standardowy flow
  projektu: MR → review bota ARP → green.

## 7. Poza zakresem

- Hotplug NVMe / zmiana składu ringów w runtime.
- Progi per-ring (progi są per kafel).
- Odczyt innych sensorów NCT67xx (CPUTIN, wentylatory, napięcia).
- Zmiany w bloku THREAD UTIL (zostaje bez liczb).
