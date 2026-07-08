# Temperatury w ringach — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Liczbowe °C w mini-ringach CORE TEMP + dwa nowe kafle hero `MultiRingGauge` (NVME TEMPS, CPU/MB TEMPS) zasilane rozszerzonym `ThermalSource` (SYSTIN z NCT67xx).

**Architecture:** Nowy widget `MultiRingGauge` (N koncentrycznych łuków) generalizuje i **zastępuje** `DualRingGauge`; kafel TEMPS migruje na niego, dwa nowe kafle dochodzą do pasa hero. `ThermalSource` dostaje trzecie źródło `thermal.board` (label `SYSTIN` z chipów Super I/O `nct*`). `CoreRingGrid` powiększa komórki bloku temp do 30 px i rysuje w nich liczbę °C.

**Tech Stack:** Python 3.12, PySide6 (QPainter, QVariantAnimation), pytest (fixture `qapp` z `tests/conftest.py`).

**Spec:** `docs/superpowers/specs/2026-07-08-temp-rings-design.md`

## Global Constraints

- Branch roboczy: `feat/temp-rings` odgałęziony od HEAD brancha `fix/glyph-drag-feedback` (spec i plan są w jego historii). Praca w **git worktree** (skill `superpowers:using-git-worktrees`) — katalog główny repo ping-ponguje branche przez równoległą sesję.
- TDD: w każdym tasku najpierw test (RED), potem implementacja (GREEN).
- Pełny zestaw `.venv/bin/pytest -q` musi być zielony przed MR.
- Klucze serii bez zmian schematu: jedyny zapisywany klucz to istniejący `thermal.board`.
- Kolejność ringów w `MultiRingGauge` i `set_values`: **zewnętrzny → wewnętrzny**.
- Progi per kafel (nie per ring): TEMPS 75/90, NVME 70/80, CPU/MB 80/90.
- Komentarze/copy po polsku, w stylu istniejących plików.

---

### Task 1: ThermalSource — `SYSTIN` z chipów NCT67xx jako `thermal.board`

**Files:**
- Modify: `kokpit/sources/thermal.py` (metoda `sample`, nowa `_read_systin`)
- Test: `tests/test_thermal.py`

**Interfaces:**
- Consumes: istniejące helpery `_read_text`, `_read_temp`, `_label_path` z `thermal.py`.
- Produces: `thermal.board` wypełniany także na hostach z chipem `nct*` (label `SYSTIN`). Priorytet: `pch` > `SYSTIN` > `acpitz`. Task 4 zależy od obecności tej serii.

- [ ] **Step 1: Napisz failing testy**

Dopisz na końcu `tests/test_thermal.py`:

```python
def test_thermal_board_from_nct_systin(tmp_path):
    _mkchip(tmp_path, 4, "nct6798", {
        "temp1": ("SYSTIN", 40000),
        "temp3": ("AUXTIN0", 111500),   # niepodłączony pin — śmieciowe ~112°C, musi być zignorowany
        "temp10": ("PCH_CHIP_TEMP", 0),
    })
    out = ThermalSource(root=tmp_path).sample(now_ms=0, dt_s=1.0)
    assert out["thermal.board"] == 40.0


def test_thermal_board_priority_pch_systin_acpitz(tmp_path):
    _mkchip(tmp_path, 0, "acpitz", {"temp1": ("", 45000)})
    _mkchip(tmp_path, 1, "nct6798", {"temp1": ("SYSTIN", 40000)})
    out = ThermalSource(root=tmp_path).sample(now_ms=0, dt_s=1.0)
    assert out["thermal.board"] == 40.0       # SYSTIN > acpitz
    _mkchip(tmp_path, 2, "pch_cannonlake", {"temp1": ("", 61000)})
    out = ThermalSource(root=tmp_path).sample(now_ms=0, dt_s=1.0)
    assert out["thermal.board"] == 61.0       # pch > SYSTIN


def test_thermal_nct_without_systin_no_board(tmp_path):
    _mkchip(tmp_path, 0, "nct6798", {"temp3": ("AUXTIN0", 111500)})
    out = ThermalSource(root=tmp_path).sample(now_ms=0, dt_s=1.0)
    assert "thermal.board" not in out
```

- [ ] **Step 2: Uruchom — mają FAILować**

Run: `.venv/bin/pytest tests/test_thermal.py -q`
Expected: 3 nowe testy FAIL (`KeyError: 'thermal.board'` / assert 45.0 == 40.0), stare PASS.

- [ ] **Step 3: Implementacja w `thermal.py`**

W `sample()` zamień inicjalizację i pętlę gałęzi (fragment `acpitz = pch = None` … `board = pch if ...`):

```python
        nvme_idx = 0
        acpitz = pch = systin = None
        for chip in chips:
            name = _read_text(chip / "name")
            if name is None:
                continue
            if name.startswith("coretemp"):
                self._read_coretemp(chip, _hwmon_num(chip), out)
            elif name.startswith("nvme"):
                if self._read_nvme(chip, nvme_idx, out):
                    nvme_idx += 1
            elif "iwlwifi" in name or "wifi" in name:
                self._read_wifi(chip, out)
            elif name.startswith("pch"):            # chipset (PCH) — sensor płyty głównej
                pch = _read_temp(chip / "temp1_input")
            elif name.startswith("nct"):            # Super I/O (Nuvoton) — dedykowany SYSTIN
                systin = self._read_systin(chip)
            elif name == "acpitz":                  # ambient ACPI thermal zone (fallback MB)
                acpitz = _read_temp(chip / "temp1_input")
        # chipset > dedykowany sensor płyty (SYSTIN) > rozmyta strefa ACPI
        board = next((t for t in (pch, systin, acpitz) if t is not None), None)
        if board is not None:
            out["thermal.board"] = board
        return out
```

Dopisz metodę statyczną (obok `_read_nvme`):

```python
    @staticmethod
    def _read_systin(chip: Path) -> float | None:
        """Tylko wejście z labelem SYSTIN — niepodłączone AUXTIN raportują ~112°C."""
        for inp in sorted(chip.glob("temp*_input")):
            if (_read_text(_label_path(inp)) or "") == "SYSTIN":
                return _read_temp(inp)
        return None
```

Zaktualizuj docstring klasy: do listy kluczy dopisz `thermal.board` (pch > SYSTIN > acpitz).

- [ ] **Step 4: Testy zielone**

Run: `.venv/bin/pytest tests/test_thermal.py -q`
Expected: wszystkie PASS.

- [ ] **Step 5: Commit**

```bash
git add kokpit/sources/thermal.py tests/test_thermal.py
git commit -m "feat(thermal): thermal.board z SYSTIN chipów NCT67xx (pch > SYSTIN > acpitz)"
```

---

### Task 2: Widget `MultiRingGauge`

**Files:**
- Create: `kokpit/ui/widgets/multi_ring_gauge.py`
- Test: `tests/test_multi_ring_gauge.py`

**Interfaces:**
- Consumes: `START_DEG`, `arc_span`, `ring_fraction` z `kokpit/ui/widgets/ring_gauge.py`; `DIM_FG`, `round_pen`, `value_color` z `kokpit/ui/theme/palette.py`.
- Produces (Taski 3–4 na tym polegają):
  - `MultiRingGauge(title: str, rings: list[tuple[str, str]], high: float | None = None, crit: float | None = None, unit: str = "°", vmax: float = 100.0)` — `rings` to `[(label, accent_hex), ...]` zewn.→wewn.
  - `.set_values(values: list[float | None]) -> None` — ta sama kolejność; krótsza lista → brakujące `None`, dłuższa → nadmiar ignorowany.
  - `ring_width(side: float, n: int) -> float` — czysta funkcja modułowa.

- [ ] **Step 1: Napisz failing testy**

Utwórz `tests/test_multi_ring_gauge.py`:

```python
import pytest


def test_multi_ring_stores_values(qapp):
    from kokpit.ui.widgets.multi_ring_gauge import MultiRingGauge
    g = MultiRingGauge("NVME TEMPS", [("N0", "#3df0ff"), ("N1", "#ff3cc8"), ("N2", "#39ff14")],
                       high=70, crit=80)
    g.set_values([41.0, 52.0, None])
    assert g._vals == [41.0, 52.0, None]


def test_multi_ring_defensive_lengths(qapp):
    from kokpit.ui.widgets.multi_ring_gauge import MultiRingGauge
    g = MultiRingGauge("T", [("A", "#3df0ff"), ("B", "#ff3cc8"), ("C", "#39ff14")])
    g.set_values([41.0])                      # za krótko → reszta None
    assert g._vals == [41.0, None, None]
    g.set_values([1.0, 2.0, 3.0, 4.0])        # za długo → nadmiar ignorowany
    assert g._vals == [1.0, 2.0, 3.0]


def test_ring_width_adapts():
    from kokpit.ui.widgets.multi_ring_gauge import ring_width
    assert ring_width(128, 2) == 9.0                      # małe N → dzisiejsza grubość Dual
    assert ring_width(128, 3) == 9.0
    assert ring_width(128, 5) == pytest.approx(0.6 * 48 / 5)   # więcej ringów → cieńsze


def test_multi_ring_render_smoke(qapp):
    from PySide6 import QtGui
    from kokpit.ui.widgets.multi_ring_gauge import MultiRingGauge
    g = MultiRingGauge("TEMPS", [("PCI", "#3df0ff"), ("MB", "#39ff14"), ("N0", "#ff3cc8")])
    g.set_values([53.0, None, 44.0])          # ring bez danych — bez crasha
    g.resize(160, 160)
    img = QtGui.QImage(160, 160, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    g.render(img)
    assert img.width() == 160
```

- [ ] **Step 2: Uruchom — ma FAILować**

Run: `.venv/bin/pytest tests/test_multi_ring_gauge.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kokpit.ui.widgets.multi_ring_gauge'`.

- [ ] **Step 3: Implementacja**

Utwórz `kokpit/ui/widgets/multi_ring_gauge.py`:

```python
"""Hero gauge z N koncentrycznymi łukami (zewn.→wewn.) do powiązanych temperatur
(np. dyski NVMe albo pakiet CPU + płyta). Generalizacja dawnego DualRingGauge:
grubość ringów adaptuje się do N, środek zawsze zostaje na N linii wartości."""
from PySide6 import QtCore, QtGui, QtWidgets

from kokpit.ui.theme.palette import DIM_FG, round_pen, value_color
from kokpit.ui.widgets.ring_gauge import START_DEG, arc_span, ring_fraction

MARGIN = 16        # margines kwadratu gauge'a (jak w dawnym Dual)
MAX_RING_W = 9.0   # grubość ringu przy małym N (dzisiejszy wygląd hero)


def ring_width(side: float, n: int) -> float:
    """N ringów zajmuje maks. 60% promienia — środek zostaje na tekst wartości."""
    r = side / 2.0 - MARGIN
    return min(MAX_RING_W, 0.6 * r / max(1, n))


class MultiRingGauge(QtWidgets.QWidget):
    def __init__(self, title: str, rings: list[tuple[str, str]],
                 high: float | None = None, crit: float | None = None,
                 unit: str = "°", vmax: float = 100.0) -> None:
        super().__init__()
        self._title = title
        self._labels = [lb for lb, _ in rings]
        self._accents = [ac for _, ac in rings]
        self._high, self._crit = high, crit
        self._unit, self._vmax = unit, vmax
        n = len(rings)
        self._vals: list[float | None] = [None] * n
        self._shown: list[float] = [0.0] * n
        self.setMinimumSize(128, 128)
        self._anims = [self._mk_anim(i) for i in range(n)]

    def _mk_anim(self, i: int) -> QtCore.QVariantAnimation:
        a = QtCore.QVariantAnimation(self, duration=450)
        a.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        a.valueChanged.connect(lambda v, i=i: self._on_anim(i, v))
        return a

    def _on_anim(self, i: int, v) -> None:
        self._shown[i] = float(v)
        self.update()

    def set_values(self, values: list[float | None]) -> None:
        """Wartości zewn.→wewn.; brakujące → None, nadmiar ignorowany."""
        n = len(self._vals)
        vals = (list(values) + [None] * n)[:n]
        for i, v in enumerate(vals):
            if v is None:
                self._vals[i] = None
                self._anims[i].stop()
                continue
            self._vals[i] = float(v)
            self._anims[i].stop()
            self._anims[i].setStartValue(self._shown[i])
            self._anims[i].setEndValue(float(v))
            self._anims[i].start()
        self.update()

    def _color(self, value: float | None, accent: str) -> QtGui.QColor:
        if value is None:
            return QtGui.QColor(DIM_FG)
        return QtGui.QColor(value_color(accent, value, self._high, self._crit))

    def _draw_ring(self, p, rect, value, shown, accent, width) -> None:
        start16 = int(START_DEG * 16)
        p.setPen(round_pen("#16263a", width))
        p.drawArc(rect, start16, int(arc_span(1.0) * 16))
        if value is None:
            return
        qc = self._color(value, accent)
        span = int(arc_span(ring_fraction(shown, self._vmax)) * 16)
        glow = QtGui.QColor(qc)
        glow.setAlpha(70)
        p.setPen(round_pen(glow, width + 6))
        p.drawArc(rect, start16, span)
        p.setPen(round_pen(qc, width))
        p.drawArc(rect, start16, span)

    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        side = min(self.width(), self.height())
        x0 = (self.width() - side) / 2
        y0 = (self.height() - side) / 2
        n = len(self._vals)
        w = ring_width(side, n)
        outer = QtCore.QRectF(x0 + MARGIN, y0 + MARGIN, side - 2 * MARGIN, side - 2 * MARGIN)
        rect = outer
        for i in range(n):
            self._draw_ring(p, rect, self._vals[i], self._shown[i], self._accents[i], w)
            rect = rect.adjusted(w, w, -w, -w)   # kolejny ring tuż przy poprzednim
        cy = outer.center().y()
        f = p.font()
        f.setBold(True)
        f.setPointSize(max(7, int(side * 0.07)))
        p.setFont(f)
        lh = side * min(0.11, 0.33 / max(1, n))   # linie ciaśniejsze, gdy ringów więcej
        top = cy - lh * n / 2
        # N linii "LABEL 72°" w centrum, każda w kolorze swojego ringu
        for i in range(n):
            t = "--" if self._vals[i] is None else f"{self._shown[i]:.0f}{self._unit}"
            p.setPen(self._color(self._vals[i], self._accents[i]))
            p.drawText(QtCore.QRectF(outer.left(), top + i * lh, outer.width(), lh),
                       QtCore.Qt.AlignCenter, f"{self._labels[i]} {t}")
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(QtGui.QColor("#5fb8d6"))
        p.drawText(QtCore.QRectF(outer.left(), outer.bottom() - side * 0.14, outer.width(), 14),
                   QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, self._title)
        p.end()
```

- [ ] **Step 4: Testy zielone**

Run: `.venv/bin/pytest tests/test_multi_ring_gauge.py -q`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/widgets/multi_ring_gauge.py tests/test_multi_ring_gauge.py
git commit -m "feat(ui): MultiRingGauge — N koncentrycznych ringów z adaptacyjną grubością"
```

---

### Task 3: Migracja TEMPS na MultiRingGauge, usunięcie DualRingGauge

**Files:**
- Modify: `kokpit/ui/app.py` (import ~linia 22, konstruktor `self._temps` ~95–97, `_on_snapshot` ~282–288)
- Delete: `kokpit/ui/widgets/dual_ring_gauge.py`, `tests/test_dual_ring_gauge.py`

**Interfaces:**
- Consumes: `MultiRingGauge` i `set_values` z Taska 2 (sygnatury tamże).
- Produces: `self._temps: MultiRingGauge` — jedyny użytkownik `DualRingGauge` znika, klasa i test usunięte. Task 4 dokłada kafle obok w tym samym stylu.

- [ ] **Step 1: Usuń stary widget i test (RED przez ImportError)**

```bash
git rm kokpit/ui/widgets/dual_ring_gauge.py tests/test_dual_ring_gauge.py
```

Run: `.venv/bin/pytest -q`
Expected: FAIL — `app.py` importuje nieistniejący `dual_ring_gauge` (testy ciągnące `kokpit.ui.app`).

- [ ] **Step 2: Przełącz `app.py`**

Import (linia `from kokpit.ui.widgets.dual_ring_gauge import DualRingGauge`) zamień na:

```python
from kokpit.ui.widgets.multi_ring_gauge import MultiRingGauge
```

Konstruktor `self._temps` (w `MainWindow.__init__`) zamień na:

```python
        self._temps = MultiRingGauge(
            "TEMPS", [("PCI", NEON_MAGENTA), ("MB" if self._has_board else "SSD", NEON_LIME)],
            high=75, crit=90)
```

W `_on_snapshot` fragment z `set_outer`/`set_inner` zamień na:

```python
        # PCI adapter (wifi) na zewn. ringu; płyta (board) lub najgorętszy NVMe na wewn.
        board = s.get("thermal.board")
        if board is None:
            nvme = [v for k, v in s.items() if k.startswith("thermal.nvme.") and v is not None]
            board = max(nvme) if nvme else None
        self._temps.set_values([s.get("thermal.wifi"), board])
```

- [ ] **Step 3: Pełny zestaw zielony**

Run: `.venv/bin/pytest -q`
Expected: PASS (bez testów Duala, z testami Multi).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(ui): TEMPS na MultiRingGauge, DualRingGauge usunięty"
```

---

### Task 4: Kafle NVME TEMPS i CPU/MB TEMPS w pasie hero

**Files:**
- Modify: `kokpit/ui/app.py` (funkcje modułowe przy `primary_net_key`, konstruktor `MainWindow`, `top_lay` ~200–202, `_on_snapshot`)
- Test: `tests/test_temp_tiles.py` (nowy)

**Interfaces:**
- Consumes: `MultiRingGauge` (Task 2); `thermal.board` z Taska 1; istniejący `thermal_series = set(model.available_series("thermal."))` w konstruktorze.
- Produces (czyste funkcje modułowe w `app.py`):
  - `nvme_temp_keys(names: list[str]) -> list[str]` — klucze `thermal.nvme.<i>` posortowane numerycznie.
  - `cpu_mb_rings(names: list[str]) -> list[tuple[str, str]]` — `[(label, klucz)]`: pakiety CPU (`CPU` lub `CPU0`, `CPU1`…) + `("MB", "thermal.board")` jeśli obecny.

- [ ] **Step 1: Napisz failing testy**

Utwórz `tests/test_temp_tiles.py`:

```python
from kokpit.ui.app import cpu_mb_rings, nvme_temp_keys


def test_nvme_temp_keys_numeric_sort():
    names = ["thermal.nvme.10", "thermal.nvme.2", "thermal.board", "net.eth0.rx_bps"]
    assert nvme_temp_keys(names) == ["thermal.nvme.2", "thermal.nvme.10"]


def test_nvme_temp_keys_empty():
    assert nvme_temp_keys(["thermal.board"]) == []


def test_cpu_mb_rings_single_socket_with_board():
    names = ["thermal.coretemp.3.pkg", "thermal.coretemp.3.core.0", "thermal.board"]
    assert cpu_mb_rings(names) == [("CPU", "thermal.coretemp.3.pkg"), ("MB", "thermal.board")]


def test_cpu_mb_rings_dual_socket_no_board():
    names = ["thermal.coretemp.5.pkg", "thermal.coretemp.3.pkg"]
    assert cpu_mb_rings(names) == [("CPU0", "thermal.coretemp.3.pkg"),
                                   ("CPU1", "thermal.coretemp.5.pkg")]


def test_cpu_mb_rings_nothing():
    assert cpu_mb_rings(["thermal.nvme.0"]) == []
```

- [ ] **Step 2: Uruchom — ma FAILować**

Run: `.venv/bin/pytest tests/test_temp_tiles.py -q`
Expected: FAIL — `ImportError: cannot import name 'nvme_temp_keys'`.

- [ ] **Step 3: Implementacja — funkcje modułowe**

W `kokpit/ui/app.py`, pod `primary_net_key`, dodaj:

```python
def nvme_temp_keys(names: list[str]) -> list[str]:
    """Serie thermal.nvme.<i> posortowane numerycznie po indeksie dysku."""
    ks = [n for n in names if n.startswith("thermal.nvme.")]
    return sorted(ks, key=lambda k: int(k.rsplit(".", 1)[1]))


def cpu_mb_rings(names: list[str]) -> list[tuple[str, str]]:
    """[(label, klucz)] kafla CPU/MB: pakiety CPU (zewn.) + płyta (wewn.), jeśli są."""
    pkgs = sorted(n for n in names if n.startswith("thermal.coretemp.") and n.endswith(".pkg"))
    rings = [("CPU" if len(pkgs) == 1 else f"CPU{i}", k) for i, k in enumerate(pkgs)]
    if "thermal.board" in names:
        rings.append(("MB", "thermal.board"))
    return rings
```

- [ ] **Step 4: Testy funkcji zielone**

Run: `.venv/bin/pytest tests/test_temp_tiles.py -q`
Expected: 5 PASS.

- [ ] **Step 5: Wiring w konstruktorze `MainWindow`**

Zaraz po utworzeniu `self._temps` dodaj (skład kafli rozstrzygany raz, przy starcie — wzorzec `_has_board`; brak serii → kafla nie ma w layoutcie):

```python
        thermal_names = sorted(thermal_series)
        self._nvme_keys = nvme_temp_keys(thermal_names)
        self._nvme = None
        if self._nvme_keys:
            _acc = [NEON_CYAN, NEON_MAGENTA, NEON_LIME]
            self._nvme = MultiRingGauge(
                "NVME TEMPS",
                [(f"N{i}", _acc[i % len(_acc)]) for i in range(len(self._nvme_keys))],
                high=70, crit=80)
        self._cpu_mb_rings = cpu_mb_rings(thermal_names)
        self._cpu_mb = None
        if self._cpu_mb_rings:
            self._cpu_mb = MultiRingGauge(
                "CPU/MB TEMPS",
                [(lb, NEON_LIME if key == "thermal.board" else NEON_MAGENTA)
                 for lb, key in self._cpu_mb_rings],
                high=80, crit=90)
```

W sekcji layoutu (po `top_lay.addWidget(self._temps, 1)`):

```python
        if self._nvme is not None:
            top_lay.addWidget(self._nvme, 1)
        if self._cpu_mb is not None:
            top_lay.addWidget(self._cpu_mb, 1)
```

W `_on_snapshot` (po `self._temps.set_values(...)`):

```python
        if self._nvme is not None:
            self._nvme.set_values([s.get(k) for k in self._nvme_keys])
        if self._cpu_mb is not None:
            self._cpu_mb.set_values([s.get(k) for _, k in self._cpu_mb_rings])
```

- [ ] **Step 6: Pełny zestaw zielony**

Run: `.venv/bin/pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add kokpit/ui/app.py tests/test_temp_tiles.py
git commit -m "feat(ui): kafle NVME TEMPS i CPU/MB TEMPS w pasie hero (MultiRingGauge)"
```

---

### Task 5: CoreRingGrid — liczby °C w ringach CORE TEMP

**Files:**
- Modify: `kokpit/ui/widgets/core_ring_grid.py`
- Test: `tests/test_core_ring_grid.py`

**Interfaces:**
- Consumes: `heat_rgb(frac) -> (r, g, b)` z palety (kolor liczby = kolor łuku).
- Produces: `TEMP_CELL = 30` (stała modułowa), `CoreRingGrid._temp_vals: dict[str, float | None]` (surowe °C). Publiczne API (`set_util`/`set_temp`) bez zmian — `app.py` nie wymaga edycji.

- [ ] **Step 1: Napisz failing testy**

Dopisz na końcu `tests/test_core_ring_grid.py`:

```python
def test_core_ring_grid_stores_raw_temps(qapp):
    from kokpit.ui.widgets.core_ring_grid import CoreRingGrid
    g = CoreRingGrid()
    g.set_temp({"thermal.coretemp.3.core.0": 47.6})
    assert g._temp_vals["thermal.coretemp.3.core.0"] == 47.6
    g.set_temp({})                                   # klucz latchuje, wartość znika
    assert g._temp_vals["thermal.coretemp.3.core.0"] is None


def test_core_ring_grid_temp_cells_wider(qapp):
    from kokpit.ui.widgets.core_ring_grid import (
        CELL, GAP, PAD, SECTION_GAP, TEMP_CELL, TEMP_COLS, UTIL_COLS, CoreRingGrid,
    )
    assert TEMP_CELL > CELL                          # komórka temp mieści liczbę °C
    g = CoreRingGrid()
    assert g.minimumWidth() == (PAD + UTIL_COLS * (CELL + GAP) + SECTION_GAP
                                + TEMP_COLS * (TEMP_CELL + GAP) + PAD)


def test_core_ring_grid_render_smoke_numbers(qapp):
    from PySide6 import QtGui
    from kokpit.ui.widgets.core_ring_grid import CoreRingGrid
    g = CoreRingGrid()
    g.set_util({f"cpu.thread.{i}.util": (i * 3) % 100 for i in range(32)})
    g.set_temp({f"thermal.coretemp.3.core.{i}": 40 + i for i in (0, 4, 8)})
    g.resize(g.minimumWidth(), g.minimumHeight())
    img = QtGui.QImage(g.width(), g.height(), QtGui.QImage.Format_ARGB32)
    img.fill(0)
    g.render(img)
    assert img.width() == g.width()
```

- [ ] **Step 2: Uruchom — ma FAILować**

Run: `.venv/bin/pytest tests/test_core_ring_grid.py -q`
Expected: nowe testy FAIL (`AttributeError: _temp_vals` / `ImportError: TEMP_CELL`), stare PASS.

- [ ] **Step 3: Implementacja**

W `kokpit/ui/widgets/core_ring_grid.py`:

Stałe — dodaj `TEMP_CELL` pod `CELL`:

```python
CELL = 17
TEMP_CELL = 30     # większe komórki bloku temp — mieszczą liczbę °C w środku
```

`__init__` — szerokość/wysokość bloku temp liczona z `TEMP_CELL` + init `_temp_vals`:

```python
    def __init__(self) -> None:
        super().__init__()
        self._util = [None] * UTIL_N
        self._temp_keys: list[str] = []
        self._temp_fracs: dict[str, float | None] = {}
        self._temp_vals: dict[str, float | None] = {}
        util_rows = (UTIL_N + UTIL_COLS - 1) // UTIL_COLS
        util_w = UTIL_COLS * (CELL + GAP)
        temp_w = TEMP_COLS * (TEMP_CELL + GAP)
        # util ‖ temp obok siebie → szerokość = suma bloków, wysokość = wyższy z bloków
        self.setMinimumWidth(PAD + util_w + SECTION_GAP + temp_w + PAD)
        self.setMinimumHeight(LABEL_H + max((util_rows + 1) * (CELL + GAP),
                                            4 * (TEMP_CELL + GAP) + GAP) + 2 * PAD)
```

`set_temp` — zapamiętaj też surowe °C:

```python
    def set_temp(self, series: dict) -> None:
        # latch kluczy: siatka nie kurczy się, gdy rdzeń chwilowo zniknie (jak w heatmapie)
        seen = set(self._temp_keys) | set(sorted_thermal_keys(series.keys()))
        self._temp_keys = sorted_thermal_keys(seen)
        self._temp_fracs = {k: _temp_frac(series.get(k)) for k in self._temp_keys}
        self._temp_vals = {k: series.get(k) for k in self._temp_keys}
        self.update()
```

`_paint_section` — parametry `cell` i `vals` (liczby rysowane w kolorze łuku):

```python
    def _paint_section(self, p: QtGui.QPainter, fracs, cols, y0, ramp,
                       x0=PAD, cell=CELL, vals=None) -> int:
        rects = ring_rects(len(fracs), cols, cell, GAP, x0=x0, y0=y0)
        for i, ((x, y, w, h), frac) in enumerate(zip(rects, fracs)):
            r = QtCore.QRectF(x, y, w, h)
            p.setPen(QtGui.QPen(QtGui.QColor("#16263a"), 2))
            p.drawArc(r, 0, 360 * 16)                       # tor (pełny pierścień)
            if frac is None:
                continue
            p.setPen(round_pen(ramp(frac), 2))
            p.drawArc(r, 90 * 16, int(-360 * 16 * frac))    # wypełnienie od góry
            if vals is not None and vals[i] is not None:
                p.setPen(QtGui.QColor(*ramp(frac)))         # liczba w kolorze łuku
                p.drawText(r, QtCore.Qt.AlignCenter, f"{vals[i]:.0f}")
        rows = (len(fracs) + cols - 1) // cols
        return y0 + rows * (cell + GAP)
```

`paintEvent` — nagłówek z jednostką, mniejszy font liczb, blok temp na `TEMP_CELL`:

```python
    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        f = p.font()
        f.setBold(True)
        f.setPointSize(8)
        p.setFont(f)
        temp_x0 = PAD + UTIL_COLS * (CELL + GAP) + SECTION_GAP   # blok temp na prawo od util
        p.setPen(QtGui.QColor("#5fb8d6"))
        p.drawText(PAD, 12, "THREAD UTIL (32)")
        p.drawText(temp_x0, 12, f"CORE TEMP °C ({len(self._temp_keys)})")
        self._paint_section(p, self._util, UTIL_COLS, LABEL_H, util_rgb)
        f.setPointSize(7)
        p.setFont(f)                                             # font liczb °C w ringach
        self._paint_section(p, [self._temp_fracs.get(k) for k in self._temp_keys],
                            TEMP_COLS, LABEL_H, heat_rgb, x0=temp_x0, cell=TEMP_CELL,
                            vals=[self._temp_vals.get(k) for k in self._temp_keys])
        p.end()
```

- [ ] **Step 4: Testy zielone (w tym stary latching)**

Run: `.venv/bin/pytest tests/test_core_ring_grid.py -q`
Expected: wszystkie PASS (latching z `test_core_ring_grid_latches_temp` nietknięty).

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/widgets/core_ring_grid.py tests/test_core_ring_grid.py
git commit -m "feat(ui): liczby °C w ringach CORE TEMP (TEMP_CELL 30 px, kolor łuku)"
```

---

### Task 6: Weryfikacja końcowa + MR + review bota ARP

**Files:**
- Brak nowych — pełny zestaw testów, smoke wizualny, MR.

**Interfaces:**
- Consumes: wszystkie poprzednie taski zcommitowane na `feat/temp-rings`.
- Produces: MR na `main` w GitLab `perun/kokpit` (project id 18), zielony review ARP.

- [ ] **Step 1: Pełny zestaw testów**

Run: `.venv/bin/pytest -q`
Expected: wszystkie PASS, zero failures.

- [ ] **Step 2: Smoke wizualny (jeśli działa collectord)**

Run: `.venv/bin/python -m kokpit.ui.app` (zamknij po oględzinach)
Expected: pas hero z 7 kaflami (NVME TEMPS z 3 ringami, CPU/MB TEMPS z 2), liczby °C w ringach CORE TEMP, TEMPS pokazuje `MB` (SYSTIN działa). Brak collectorda → okno wstaje z `--` wszędzie, bez crasha.

- [ ] **Step 3: Push + MR**

```bash
git push -u origin feat/temp-rings
```

Utwórz MR przez `glab mr create` albo MCP `create_merge_request` (target `main`, tytuł: "Temperatury w ringach: °C w CORE TEMP + kafle MultiRing NVMe/CPU-MB").

- [ ] **Step 4: Review bota ARP do zielonego**

Per workflow projektu (CLAUDE.md): `arp_wait_for_review(mrIid=<IID>)` → `arp_get_findings(mrIid=<IID>, projectSlug="perun-kokpit")` → popraw findings → push (re-triggeruje review) → `arp_is_green(mrIid=<IID>, projectSlug="perun-kokpit")`. Merge dopiero na zielono (albo findings świadomie odrzucone z uzasadnieniem).
