# ThreadStar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ThreadStar` — a friendly animated starfish widget where each organic arm shows one CPU thread's utilization — alongside the existing `VitalGlyph`.

**Architecture:** Pure, presentational `QWidget` mirroring `VitalGlyph`'s structure: testable pure functions (angle/reach/easing/breathing) separated from `paintEvent`. Fed once per snapshot from `MainWindow._on_snapshot` via `set_threads(series)`; thread count discovered dynamically from `cpu.thread.<i>.util` keys. Friendliness comes from plump rounded Bézier arms, soft `util_rgb` color gradients, glow bloom, and a continuous "breathing"/sway idle animation — no face.

**Tech Stack:** Python 3.12, PySide6 (QtWidgets/QtGui/QtCore, QPainterPath), pytest (offscreen Qt via `tests/conftest.py` `qapp` fixture).

## Global Constraints

- Python 3.12; PySide6 only (no new deps).
- TDD: write the failing test first (RED), then minimal code (GREEN). `.venv/bin/pytest -q` fully green before any MR.
- DRY: reuse `util_rgb`, `round_pen` (`kokpit/ui/theme/palette.py`), `thread_util_keys` (`kokpit/ui/widgets/heatmap.py`), `clamp01` (`kokpit/ui/glyph_model.py`).
- Out of scope (do NOT add): mascot/face, mouse interaction / drag-to-cap, per-thread freq/temp.
- Widget is read-only; never mutates `series`.
- Tests use the session `qapp` fixture; widget paint is smoke-tested via `widget.render(QImage)`.

---

### Task 1: `thread_count` helper

Dynamic thread-count discovery so the star scales to any CPU (8/16/32…) without hardcoding.

**Files:**
- Modify: `kokpit/ui/widgets/heatmap.py` (add `thread_count` next to `thread_util_keys`)
- Test: `tests/test_heatmap.py`

**Interfaces:**
- Produces: `thread_count(series: dict) -> int` — returns `max(i)+1` over keys matching `cpu.thread.<digits>.util` (latch behaviour: gaps don't shrink the count), or `0` if none.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_heatmap.py`:

```python
def test_thread_count_from_series():
    from kokpit.ui.widgets.heatmap import thread_count
    assert thread_count({f"cpu.thread.{i}.util": 1 for i in range(16)}) == 16
    assert thread_count({"cpu.thread.0.util": 1, "cpu.thread.5.util": 1}) == 6  # max+1 (latch over gaps)
    assert thread_count({}) == 0
    assert thread_count({"mem.used": 1, "cpu.thread.x.util": 1}) == 0           # non-digit / non-thread ignored
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_heatmap.py::test_thread_count_from_series -v`
Expected: FAIL — `ImportError: cannot import name 'thread_count'`.

- [ ] **Step 3: Write minimal implementation**

Add to `kokpit/ui/widgets/heatmap.py` (below `thread_util_keys`):

```python
def thread_count(series) -> int:
    """Liczba wątków CPU z kluczy cpu.thread.<i>.util: max(i)+1 (latch nad dziurami), albo 0."""
    idxs = []
    for k in series:
        if k.startswith("cpu.thread.") and k.endswith(".util"):
            mid = k[len("cpu.thread."):-len(".util")]
            if mid.isdigit():
                idxs.append(int(mid))
    return max(idxs) + 1 if idxs else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_heatmap.py::test_thread_count_from_series -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/widgets/heatmap.py tests/test_heatmap.py
git commit -m "feat(ui): thread_count helper — dynamic CPU thread discovery from series"
```

---

### Task 2: Pure geometry & animation functions

The testable math core of the widget, with no Qt event-loop dependency.

**Files:**
- Create: `kokpit/ui/widgets/thread_star.py` (module-level constants + pure functions only; the class comes in Task 3)
- Test: `tests/test_thread_star.py` (create)

**Interfaces:**
- Consumes: `clamp01` from `kokpit.ui.glyph_model`.
- Produces (used by Task 3's `ThreadStar`):
  - Constants: `EASE`, `SETTLE_EPS`, `TICK_MS`, `R_BODY`, `R_ARM_MIN`, `R_ARM_SPAN`, `R_MAX`, `MARGIN`, `GLOW_THRESHOLD`, `BREATH_AMP_R`, `BREATH_AMP_A`, `BASE_HALF_ANG`.
  - `arm_angle(i: int, n: int) -> float` — `-π/2 + 2π·i/n` (arm 0 at top, clockwise).
  - `arm_reach(body_r: float, arm_min: float, arm_span: float, frac: float) -> float` — tip radius from centre; `frac` clamped 0..1.
  - `ease_step(current: list[float], target: list[float], eps=SETTLE_EPS, ease=EASE) -> tuple[list[float], bool]` — one easing tick; bool is `moving`.
  - `breath_offset(phase: int, i: int, n: int, amp_r=BREATH_AMP_R, amp_a=BREATH_AMP_A) -> tuple[float, float]` — `(dr, dθ)`, each bounded by its amplitude.

- [ ] **Step 1: Write the failing test**

Create `tests/test_thread_star.py`:

```python
import math

from kokpit.ui.widgets import thread_star as ts


def test_arm_angle_first_is_top():
    assert abs(ts.arm_angle(0, 8) - (-math.pi / 2)) < 1e-9
    assert abs(ts.arm_angle(2, 8) - 0.0) < 1e-9            # quarter turn clockwise → +x


def test_arm_reach_maps_frac():
    assert ts.arm_reach(20, 10, 80, 0.0) == 30
    assert ts.arm_reach(20, 10, 80, 1.0) == 110
    assert ts.arm_reach(20, 10, 80, 2.0) == 110            # clamp high
    assert ts.arm_reach(20, 10, 80, -1.0) == 30            # clamp low


def test_ease_step_converges_and_settles():
    cur, tgt = [0.0, 0.0], [1.0, 0.5]
    moving = True
    for _ in range(500):
        cur, moving = ts.ease_step(cur, tgt)
    assert abs(cur[0] - 1.0) < 1e-3 and abs(cur[1] - 0.5) < 1e-3
    assert moving is False


def test_ease_step_at_target_not_moving():
    _cur, moving = ts.ease_step([0.5], [0.5])
    assert moving is False


def test_breath_offset_bounded():
    for ph in range(0, 240, 7):
        for i in range(4):
            dr, da = ts.breath_offset(ph, i, 4)
            assert abs(dr) <= ts.BREATH_AMP_R + 1e-9
            assert abs(da) <= ts.BREATH_AMP_A + 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_thread_star.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kokpit.ui.widgets.thread_star'`.

- [ ] **Step 3: Write minimal implementation**

Create `kokpit/ui/widgets/thread_star.py`:

```python
"""ThreadStar — przyjazna animowana rozgwiazda: każde ramię = util jednego wątku CPU.
Czyste funkcje geometrii/animacji (testowalne bez Qt) oddzielone od paintEvent —
wzorzec jak w kokpit/ui/widgets/vital_glyph.py. Spec 2026-06-19."""
import math

from kokpit.ui.glyph_model import clamp01

EASE = 0.22
SETTLE_EPS = 0.002
TICK_MS = 25                # ~40 fps; timer biegnie ciągle (oddech), 1 paint/tick

R_BODY = 26.0               # promień centralnego dysku (przed skalą)
R_ARM_MIN = 16.0            # długość stubu przy 0% utilu (idle = wciąż rozgwiazda)
R_ARM_SPAN = 82.0           # dodatkowa długość przy 100% utilu
R_MAX = R_BODY + R_ARM_MIN + R_ARM_SPAN   # 124 — max zasięg czubka
MARGIN = 18.0              # margines do krawędzi widgetu
GLOW_THRESHOLD = 0.55      # próg bloomu dla zajętych ramion
BREATH_AMP_R = 3.0         # px (przed skalą) — puls promienia (oddech)
BREATH_AMP_A = 0.045       # rad — kołysanie kąta ramienia
BASE_HALF_ANG = 0.30       # rad — połowa kątowej szerokości bazy ramienia na ciele


def arm_angle(i: int, n: int) -> float:
    return -math.pi / 2 + 2 * math.pi * i / n


def arm_reach(body_r: float, arm_min: float, arm_span: float, frac: float) -> float:
    return body_r + arm_min + arm_span * clamp01(frac)


def ease_step(current, target, eps: float = SETTLE_EPS, ease: float = EASE):
    nxt, moving = [], False
    for c, t in zip(current, target):
        c2 = c + (t - c) * ease
        if abs(t - c2) >= eps:
            moving = True
        nxt.append(c2)
    return nxt, moving


def breath_offset(phase: int, i: int, n: int,
                  amp_r: float = BREATH_AMP_R, amp_a: float = BREATH_AMP_A):
    dr = amp_r * math.sin(phase * 0.06)
    da = amp_a * math.sin(phase * 0.05 + i * (2 * math.pi / max(1, n)))
    return dr, da
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_thread_star.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/widgets/thread_star.py tests/test_thread_star.py
git commit -m "feat(ui): ThreadStar pure geometry/animation core (angle, reach, ease, breath)"
```

---

### Task 3: `ThreadStar` widget (data + animation + paint)

The widget itself: ingests a series snapshot, eases toward targets, breathes, and paints organic arms.

**Files:**
- Modify: `kokpit/ui/widgets/thread_star.py` (add the `ThreadStar` class + `_arm_path`)
- Test: `tests/test_thread_star.py` (append widget tests)

**Interfaces:**
- Consumes: `thread_util_keys`, `thread_count` (Task 1) from `kokpit.ui.widgets.heatmap`; `util_rgb`, `round_pen` from `kokpit.ui.theme.palette`; the pure functions from Task 2.
- Produces (used by Task 4):
  - `ThreadStar()` — `QWidget`, `minimumSize 220×220`.
  - `set_threads(series: dict) -> None` — discovers `n`, sets `self._target` (list of clamped 0..1 fractions), snaps `self._current` on count change, starts the timer.
  - Attributes read by tests: `self._target: list[float]`, `self._current: list[float]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_thread_star.py`:

```python
def test_set_threads_maps_util_to_fraction(qapp):
    w = ts.ThreadStar()
    w.set_threads({f"cpu.thread.{i}.util": 50.0 for i in range(8)})
    assert len(w._target) == 8
    assert all(abs(t - 0.5) < 1e-9 for t in w._target)


def test_set_threads_missing_key_is_zero(qapp):
    w = ts.ThreadStar()
    w.set_threads({"cpu.thread.0.util": 100.0, "cpu.thread.3.util": 0.0})  # n=4, gaps→0
    assert len(w._target) == 4
    assert w._target[0] == 1.0 and w._target[1] == 0.0 and w._target[3] == 0.0


def test_thread_count_change_snaps_current(qapp):
    w = ts.ThreadStar()
    w.set_threads({f"cpu.thread.{i}.util": 80.0 for i in range(16)})
    w.set_threads({f"cpu.thread.{i}.util": 20.0 for i in range(8)})    # count drops 16→8
    assert len(w._current) == 8                                        # snapped, no stale length


def test_paint_smoke_16_threads(qapp):
    from PySide6 import QtGui
    w = ts.ThreadStar(); w.resize(240, 240)
    w.set_threads({f"cpu.thread.{i}.util": (i * 7) % 100 for i in range(16)})
    img = QtGui.QImage(240, 240, QtGui.QImage.Format_ARGB32)
    w.render(img)                                                      # paintEvent must not crash


def test_paint_smoke_zero_threads(qapp):
    from PySide6 import QtGui
    w = ts.ThreadStar(); w.resize(240, 240)
    w.set_threads({})
    img = QtGui.QImage(240, 240, QtGui.QImage.Format_ARGB32)
    w.render(img)                                                      # n==0 guard, no crash
    assert w._target == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_thread_star.py -v`
Expected: FAIL — `AttributeError: module 'kokpit.ui.widgets.thread_star' has no attribute 'ThreadStar'`.

- [ ] **Step 3: Write minimal implementation**

Edit `kokpit/ui/widgets/thread_star.py`: change the import line and append the class.

Change the top import block to:

```python
import math

from PySide6 import QtCore, QtGui, QtWidgets

from kokpit.ui.glyph_model import clamp01
from kokpit.ui.theme.palette import round_pen, util_rgb
from kokpit.ui.widgets.heatmap import thread_count, thread_util_keys
```

Append at the end of the file:

```python
class ThreadStar(QtWidgets.QWidget):
    """Rozgwiazda wątków: n ramion = n wątków CPU, długość ramienia = util,
    kolor z rampy util_rgb. Pulchne ramiona Béziera + ciągły oddech/kołysanie."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(220, 220)
        self._target: list[float] = []
        self._current: list[float] = []
        self._phase = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._advance)

    def set_threads(self, series: dict) -> None:
        n = thread_count(series)
        self._target = [clamp01((series.get(k) or 0.0) / 100.0) for k in thread_util_keys(n)]
        if len(self._current) != n:                    # liczba wątków zmieniła się → snap
            self._current = list(self._target)
        if n and not self._timer.isActive():
            self._timer.start()
        self.update()

    def _advance(self) -> None:
        self._phase += 1
        if self._current:
            self._current, _moving = ease_step(self._current, self._target)
        self.update()                                  # timer biegnie ciągle (oddech)

    def _arm_path(self, cx: float, cy: float, a: float, body_r: float,
                  reach: float, n: int) -> QtGui.QPainterPath:
        # baza ramienia na ciele, zaciśnięta pod sektor, by ramiona się nie zlewały
        half_ang = min(BASE_HALF_ANG, (math.pi / n) * 0.8)
        a0, a1 = a - half_ang, a + half_ang
        p0 = QtCore.QPointF(cx + body_r * math.cos(a0), cy + body_r * math.sin(a0))
        p1 = QtCore.QPointF(cx + body_r * math.cos(a1), cy + body_r * math.sin(a1))
        tip = QtCore.QPointF(cx + reach * math.cos(a), cy + reach * math.sin(a))
        mid = (body_r + reach) * 0.5                   # punkty kontrolne wybrzuszone na zewnątrz
        bow = half_ang * 1.6                           # → pulchne, zaokrąglone ramię (friendly)
        c0 = QtCore.QPointF(cx + mid * math.cos(a - bow), cy + mid * math.sin(a - bow))
        c1 = QtCore.QPointF(cx + mid * math.cos(a + bow), cy + mid * math.sin(a + bow))
        path = QtGui.QPainterPath(p0)
        path.quadTo(c0, tip)
        path.quadTo(c1, p1)
        path.closeSubpath()
        return path

    def paintEvent(self, _event) -> None:
        n = len(self._current)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        if n == 0:
            p.end()
            return
        cx, cy = self.width() / 2.0, self.height() / 2.0
        center = QtCore.QPointF(cx, cy)
        half = min(cx, cy)
        sc = max(0.1, (half - MARGIN) / R_MAX)
        dr_breath, _ = breath_offset(self._phase, 0, n)     # globalny puls (oddech)
        body_r = (R_BODY + dr_breath) * sc

        for i in range(n):
            frac = self._current[i]
            _, da = breath_offset(self._phase, i, n)
            a = arm_angle(i, n) + da
            reach = arm_reach(R_BODY + dr_breath, R_ARM_MIN, R_ARM_SPAN, frac) * sc
            r, g, b = util_rgb(frac)
            path = self._arm_path(cx, cy, a, body_r, reach, n)
            tip = QtCore.QPointF(cx + reach * math.cos(a), cy + reach * math.sin(a))
            grad = QtGui.QLinearGradient(center, tip)
            base_col = QtGui.QColor(r, g, b); base_col.setAlpha(70)
            tip_col = QtGui.QColor(r, g, b); tip_col.setAlpha(235)
            grad.setColorAt(0.0, base_col)
            grad.setColorAt(1.0, tip_col)
            if frac >= GLOW_THRESHOLD:                       # bloom dla rozgrzanych wątków
                glow = QtGui.QColor(r, g, b); glow.setAlpha(70)
                p.setPen(round_pen(glow, 10.0)); p.setBrush(QtCore.Qt.NoBrush)
                p.drawPath(path)
            p.setPen(round_pen(QtGui.QColor(r, g, b, 180), 1.4))
            p.setBrush(QtGui.QBrush(grad))
            p.drawPath(path)

        bg = QtGui.QRadialGradient(center, body_r)           # ciało rozgwiazdy na wierzchu
        bg.setColorAt(0.0, QtGui.QColor(60, 80, 110, 230))
        bg.setColorAt(1.0, QtGui.QColor(28, 40, 60, 180))
        p.setPen(round_pen(QtGui.QColor(120, 150, 180, 160), 1.4))
        p.setBrush(QtGui.QBrush(bg))
        p.drawEllipse(center, body_r, body_r)
        p.end()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_thread_star.py -v`
Expected: PASS (all 10 tests).

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/widgets/thread_star.py tests/test_thread_star.py
git commit -m "feat(ui): ThreadStar widget — organic per-thread arms, gradient+bloom, breathing"
```

---

### Task 4: Wire `ThreadStar` into `MainWindow`

Place the star under CORES in the left vitals column and feed it each snapshot.

**Files:**
- Modify: `kokpit/ui/app.py` (import; `__init__` instantiation; `zone_vitals` layout; `_on_snapshot`)
- Test: `tests/test_widgets_smoke.py` (append wiring test)

**Interfaces:**
- Consumes: `ThreadStar`, `set_threads` (Task 3); existing `_titled(icon_name, color, text, widget)` helper and `NEON_CYAN` in `app.py`.
- Produces: `MainWindow._thread_star: ThreadStar` attribute, fed in `_on_snapshot`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_widgets_smoke.py`:

```python
def test_mainwindow_feeds_thread_star(qapp):
    from kokpit.ui.app import MainWindow
    from kokpit.ui.history_model import HistoryModel
    from kokpit.ui.live_client import LiveClient

    class FakeStore:
        def query(self, n, a, b): return [(a, 1.0), (b, 2.0)]
        def query_rollup(self, n, a, b): return [(a, 0.0, 9.0, 4.5, 5.0)]
        def list_series(self, prefix=None): return []

    win = MainWindow(LiveClient("/nonexistent.sock"), HistoryModel(FakeStore()), gpu_indices=[0])
    win._on_snapshot({
        "ts": 1000,
        "series": {f"cpu.thread.{i}.util": 40 for i in range(16)},
        "procs": [],
    })
    assert len(win._thread_star._target) == 16
    assert all(abs(t - 0.4) < 1e-9 for t in win._thread_star._target)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_widgets_smoke.py::test_mainwindow_feeds_thread_star -v`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_thread_star'`.

- [ ] **Step 3: Write minimal implementation**

In `kokpit/ui/app.py`:

(a) Add the import beside the other widget imports (after line 26, `from kokpit.ui.widgets.vital_glyph import VitalGlyph`):

```python
from kokpit.ui.widgets.thread_star import ThreadStar
```

(b) In `MainWindow.__init__`, right after `self._core = CoreRingGrid()`:

```python
        self._thread_star = ThreadStar()
```

(c) In the `zone_vitals` layout, right after the existing CORES line
`zv.addWidget(_titled("cpu", NEON_CYAN, "CORES", self._core))`:

```python
        zv.addWidget(_titled("cpu", NEON_CYAN, "THREADS", self._thread_star))
```

(d) In `_on_snapshot`, right after `self._core.set_util(s)`:

```python
        self._thread_star.set_threads(s)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_widgets_smoke.py::test_mainwindow_feeds_thread_star -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all green (existing + new tests).

- [ ] **Step 6: Commit**

```bash
git add kokpit/ui/app.py tests/test_widgets_smoke.py
git commit -m "feat(ui): wire ThreadStar into MainWindow (THREADS under CORES, fed per snapshot)"
```

---

## Notes for the implementer

- Run the app to eyeball it if you can: `.venv/bin/python -m kokpit.ui.app` (needs the collector socket; the widget animates/breathes even with idle threads). Optional — not a gate.
- The timer runs continuously by design (breathing). That's one cheap `update()` per 25 ms — acceptable, matching the existing fps budget.
- Keep arms rounded (plump Bézier), never spiky — "friendly" is the explicit design goal.
