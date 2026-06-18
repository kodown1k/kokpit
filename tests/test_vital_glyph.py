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


def test_set_spokes_spiked_geometry(qapp):
    from kokpit.ui.widgets.vital_glyph import VitalGlyph
    w = VitalGlyph()
    spokes = [SpokeScore(n, (1.0 if n == "CPU temp" else 0.0), None, "circadian")
              for n in SPOKE_NAMES]
    w.set_spokes(spokes, calibrating=False)
    radii = [w.vertex_radius(s.score) for s in w.current_spokes()]
    assert max(radii) == w.vertex_radius(1.0)          # CPU temp wydłużone
    assert radii.count(VitalGlyph.R_BASE) == 8         # reszta spokojna
