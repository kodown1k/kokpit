from kokpit.ui.glyph_model import SpokeScore, SPOKE_NAMES


def make_spoke(score: float) -> SpokeScore:
    return SpokeScore("CPU", score, None, None, "")


def test_vertex_radius_monotonic(qapp):
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    assert w.vertex_radius(0.0) == VitalGlyph.R_BASE
    assert w.vertex_radius(1.0) == VitalGlyph.R_BASE + VitalGlyph.R_SPAN
    assert w.vertex_radius(0.0) < w.vertex_radius(0.5) < w.vertex_radius(1.0)


def test_label_radius_clamp_at_minimum_size(qapp):
    """_label_radius must keep labels inside widget bounds at min half-width (140px)."""
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    half_min = 140.0   # half of minimum widget size 280px
    assert w._label_radius(half_min) <= half_min - 6.0, (
        f"label_r overflows at min size: {w._label_radius(half_min)} > {half_min - 6.0}"
    )


def test_label_radius_settles_outside_polygon_when_room(qapp):
    """When the widget is large enough, labels sit at a fixed radius just
    outside the (fixed-size) polygon — and that is larger than the clamped
    value forced at minimum size. Proves both `min` branches are reachable."""
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    outside_polygon = w.R_BASE + w.R_SPAN + 14.0
    assert w._label_radius(400.0) == outside_polygon          # room → fixed offset branch
    assert w._label_radius(140.0) == 140.0 - 6.0              # cramped → clamp branch
    assert w._label_radius(400.0) > w._label_radius(140.0)


def test_set_spokes_renders_without_crash(qapp):
    from PySide6 import QtGui
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    w.resize(300, 300)
    calm = [SpokeScore(n, 0.0, 0.0, "circadian") for n in SPOKE_NAMES]
    w.set_spokes(calm, calibrating=False)
    img = QtGui.QImage(300, 300, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    w.render(img)                 # paintEvent nie rzuca
    assert img.width() == 300


def test_set_spokes_cold_start_proximity_only(qapp):
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    # cold-start: 4 osie z limitem na proximity, 5 z-only na 0
    spokes = []
    for n in SPOKE_NAMES:
        score = 0.6 if n in ("RAM", "VRAM", "CPU temp", "GPU temp") else 0.0
        spokes.append(SpokeScore(n, score, None, None))
    w.set_spokes(spokes, calibrating=True)
    active = [s for s in w.current_spokes() if s.score > 0]
    assert {s.name for s in active} == {"RAM", "VRAM", "CPU temp", "GPU temp"}


def test_render_with_display_strings_no_crash(qapp):
    """Rendering spokes that carry non-empty display strings must not crash."""
    from PySide6 import QtGui
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    w.resize(300, 300)
    spokes = [
        SpokeScore("CPU", 0.2, 1.5, "circadian", "CPU 1.5"),
        SpokeScore("RAM", 0.71, 71.0, None, "RAM 71%"),
        SpokeScore("Swap", 0.0, 0.0, None, "SWP 0M"),
        SpokeScore("GPU", 0.73, 73.0, None, "GPU 73%"),
        SpokeScore("VRAM", 0.4, None, None, "VRAM"),
        SpokeScore("CPU temp", 0.9, 87.0, None, "CPU° 87°"),
        SpokeScore("GPU temp", 0.5, 70.0, None, "GPU° 70°"),
        SpokeScore("Disk IO", 0.1, 8_000_000.0, None, "DISK 8"),
        SpokeScore("Net IO", 0.0, 500_000.0, None, "NET 0"),
    ]
    w.set_spokes(spokes, calibrating=False)
    img = QtGui.QImage(300, 300, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    w.render(img)
    assert img.width() == 300


def test_current_spokes_carry_display_strings(qapp):
    """Spokes stored in widget retain the display field set by glyph_model."""
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    spokes = [SpokeScore(n, 0.0, None, None, f"TST-{i}") for i, n in enumerate(SPOKE_NAMES)]
    w.set_spokes(spokes, calibrating=False)
    displays = [s.display for s in w.current_spokes()]
    assert displays == [f"TST-{i}" for i in range(len(SPOKE_NAMES))]


def test_render_empty_display_no_crash(qapp):
    """Spokes with empty display strings must not crash rendering."""
    from PySide6 import QtGui
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    w.resize(300, 300)
    spokes = [SpokeScore(n, 0.0, None, None, "") for n in SPOKE_NAMES]
    w.set_spokes(spokes, calibrating=False)
    img = QtGui.QImage(300, 300, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    w.render(img)
    assert img.width() == 300


def test_set_spokes_spiked_geometry(qapp):
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    spokes = [SpokeScore(n, (1.0 if n == "CPU temp" else 0.0), None, "circadian")
              for n in SPOKE_NAMES]
    w.set_spokes(spokes, calibrating=False)
    radii = [w.vertex_radius(s.score) for s in w.current_spokes()]
    assert max(radii) == w.vertex_radius(1.0)          # CPU temp wydłużone
    assert radii.count(VitalGlyph.R_BASE) == 8         # reszta spokojna


def test_render_spiked_neon_no_crash(qapp):
    """Spiked glyph (score >= GLOW_THRESHOLD) must render via the two-pass
    neon stroke (bloom + crisp) without crashing and produce a non-empty image."""
    from PySide6 import QtGui
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    w.resize(300, 300)
    spokes = [
        SpokeScore("CPU", 0.9, 90.0, "circadian", "CPU 90%"),
        SpokeScore("RAM", 0.85, 85.0, None, "RAM 85%"),
        SpokeScore("Swap", 0.0, 0.0, None, "SWP 0M"),
        SpokeScore("GPU", 0.7, 70.0, None, "GPU 70%"),
        SpokeScore("VRAM", 0.6, None, None, "VRAM"),
        SpokeScore("CPU temp", 0.95, 92.0, None, "CPU° 92°"),
        SpokeScore("GPU temp", 0.55, 71.0, None, "GPU° 71°"),
        SpokeScore("Disk IO", 0.1, 8_000_000.0, None, "DISK 8"),
        SpokeScore("Net IO", 0.0, 500_000.0, None, "NET 0"),
    ]
    w.set_spokes(spokes, calibrating=False)
    img = QtGui.QImage(300, 300, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    w.render(img)   # exercises bloom + crisp neon stroke path
    assert img.width() == 300
    # at least some pixels were painted (neon glow touches >0 pixels)
    painted = sum(1 for y in range(img.height())
                  for x in range(img.width())
                  if (img.pixel(x, y) >> 24) & 0xFF > 0)
    assert painted > 0, "neon render produced a blank image"


def test_advance_moves_current_toward_target(qapp):
    """After a big jump, _advance() moves _current monotonically toward target."""
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    # First call: 9 spokes all at 0.0
    zero_spokes = [make_spoke(0.0) for _ in range(9)]
    w.set_spokes(zero_spokes, False)

    # Now jump one spoke to 0.9 — len stays the same so current is NOT snapped
    high_spokes = [make_spoke(0.9)] + [make_spoke(0.0) for _ in range(8)]
    w.set_spokes(high_spokes, False)

    prev = w._current[0]
    for _ in range(5):
        w._advance()
        assert w._current[0] > prev, "_current[0] must move toward 0.9"
        assert w._current[0] <= 0.9 + 1e-9, "_current[0] must not overshoot target"
        prev = w._current[0]

    assert len(w._trail) > 0, "trail must be populated after _advance calls"


def test_trail_decays_and_settles(qapp):
    """After target reached, repeated _advance() calls decay trail and stop timer."""
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    spokes = [make_spoke(0.5) for _ in range(9)]
    w.set_spokes(spokes, False)
    # snap current to target so motion is already settled
    w._current = list(w._target)
    # manually add a trail entry
    n = len(w._current)
    radii = tuple(w.vertex_radius(w._current[i]) for i in range(n))
    w._trail = [(radii, 90)]

    # Advance many times to decay trail
    for _ in range(100):
        w._advance()
        if not w._trail and not w._timer.isActive():
            break

    assert len(w._trail) == 0, "trail must be empty after settling"
    assert not w._timer.isActive(), "timer must stop after settling"


def test_paintEvent_with_trail_no_crash(qapp):
    """paintEvent doesn't crash while a trail is populated."""
    from PySide6 import QtGui
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    w.resize(200, 200)

    zero_spokes = [make_spoke(0.0) for _ in range(9)]
    w.set_spokes(zero_spokes, False)

    high_spokes = [make_spoke(0.9)] + [make_spoke(0.1) for _ in range(8)]
    w.set_spokes(high_spokes, False)

    # Fill trail
    for _ in range(5):
        w._advance()

    assert len(w._trail) > 0, "trail must be populated before render"

    # Render — must not crash, must produce non-blank
    img = QtGui.QImage(200, 200, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    w.render(img)
    assert img.width() == 200


def test_set_spokes_count_change_clears_trail(qapp):
    """Zmiana liczby szprych czyści trail — stare radii innej długości nie zostają
    (inaczej radii[i] w paintEvent rzuciłoby IndexError)."""
    from PySide6 import QtGui
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    w.resize(200, 200)
    w.set_spokes([make_spoke(0.0) for _ in range(9)], False)
    w.set_spokes([make_spoke(0.9)] + [make_spoke(0.1) for _ in range(8)], False)
    for _ in range(5):
        w._advance()
    assert len(w._trail) > 0
    # 9 → 3 szprychy: trail musi zostać wyczyszczony przy snapowaniu _current
    w.set_spokes([make_spoke(0.5) for _ in range(3)], False)
    assert w._trail == []
    img = QtGui.QImage(200, 200, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    w.render(img)   # nie crashuje mimo niedawnego 9-szprychowego trailu
    assert img.width() == 200
