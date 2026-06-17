# Kontrakt: rozszerzenie `store.py` o API historii (dla Plan 2 / UI)

**Data:** 2026-06-17
**Właściciel realizacji:** sesja backendowa (ta, która robi poprawki Plan 1)
**Konsument:** Plan 2 / UI (`history_model.py`) — okna historii 1h/6h/24h/7d (spec §6)
**Status:** do zaimplementowania

---

## Dlaczego

`Store.query()` (`kokpit/store.py:65`) czyta **tylko** raw `sample` (retencja 48 h).
Okna historii UI to **1h / 6h / 24h / 7d** — dla 7d (i realnie 24h, gdy chcemy rzadszych
punktów) trzeba czytać z `rollup_1m`. Tej metody jeszcze nie ma. Dodatkowo, gdy demon
padł a UI startuje (spec §7: „historia z SQLite działa"), UI nie dostaje live-snapshotu,
więc musi odkryć **nazwy serii** wprost z bazy.

UI samo zdecyduje, *kiedy* sięgnąć po raw vs rollup (selektor okna żyje w `history_model.py`).
Backend dostarcza tylko dwie czyste metody odczytu na `Store`.

## Do zrobienia (2 metody + testy, TDD)

### 1. `Store.query_rollup(series, since_ms, until_ms) -> list[tuple]`

```python
def query_rollup(self, series: str, since_ms: int, until_ms: int) -> list:
    """Punkty z rollup_1m dla danej serii, rosnąco po bucket.
    Zwraca [(bucket_ms, vmin, vmax, vavg, vlast)].
    Symetryczne do query() (które zwraca [(ts, value)] z raw `sample`)."""
```

- Filtr po nazwie serii (JOIN `series_dict`), `bucket >= since_ms AND bucket <= until_ms`,
  `ORDER BY bucket`.
- Zwraca **pełną piątkę agregatów** (vmin, vmax, vavg, vlast) w jednym zapytaniu — UI
  rysuje linię z `vavg` i opcjonalnie pasmo min–max bez drugiego round-tripu.
- Typy jak w `query()`: `int(bucket)`, `float(...)` dla agregatów.

**Test (`tests/test_store.py`, dopisać):** write kilku próbek → `rollup_1m(now)` → `query_rollup(series, since, until)` zwraca posortowane buckety z poprawnymi vmin/vmax/vavg/vlast; pusty zakres → `[]`.

### 2. `Store.list_series(prefix: str | None = None) -> list[str]`

```python
def list_series(self, prefix: str | None = None) -> list[str]:
    """Nazwy serii znane bazie (z series_dict), rosnąco.
    prefix (np. 'net.' albo 'thermal.core.') filtruje przez LIKE prefix%.
    UI używa tego, gdy demon nie żyje i nie ma live-snapshotu do odkrycia
    dynamicznych serii (interfejsy sieci, dyski, rdzenie temp)."""
```

- `SELECT name FROM series_dict [WHERE name LIKE ?||'%'] ORDER BY name`.

**Test (`tests/test_store.py`, dopisać):** po write kilku serii → `list_series()` zwraca wszystkie posortowane; `list_series('net.')` zwraca tylko `net.*`.

## Czego NIE robić w tym zadaniu (to robota Plan 2 / UI)

- Selektor „raw vs rollup wg długości okna" — żyje w `history_model.py` (frontend).
- Łączenie ogona live (socket) z historią (DB) na wspólnej osi — frontend.
- Żadnych zmian w schemacie ani w pętli demona — tylko dwie metody odczytu na `Store`.

## Uwaga koordynacyjna

Obie metody to **czysty dopisek** w klasie `Store` (`kokpit/store.py`), pod istniejącym
`query()` — bez dotykania `write()`, `rollup_1m()`, `prune()`, schematu. Dzięki temu nie
koliduje z poprawkami Plan 1 poza tym jednym plikiem.
