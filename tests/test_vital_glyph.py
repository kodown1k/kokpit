from kokpit.ui.glyph_model import SpokeScore, SPOKE_NAMES


def test_vertex_radius_monotonic(qapp):
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    assert w.vertex_radius(0.0) == VitalGlyph.R_BASE
    assert w.vertex_radius(1.0) == VitalGlyph.R_BASE + VitalGlyph.R_SPAN
    assert w.vertex_radius(0.0) < w.vertex_radius(0.5) < w.vertex_radius(1.0)


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
        SpokeScore("VRAM", 0.4, None, None, "VRAM 40%"),
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
