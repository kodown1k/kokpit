import pyqtgraph as pg

# USE_OPENGL: wg Task 0 (SPIKE-W2-RESULTS.md) domyślnie False — włącz tylko jeśli spike tego wymaga.
USE_OPENGL = False

# antialias=True: gładkie linie neonu; addendum W2 — koszt AA ≈4% przy suficie (99→95 fps),
# próg ≥10 fps spełniony z ~10× zapasem.
pg.setConfigOptions(antialias=True, useOpenGL=USE_OPENGL, background="#04060d", foreground="#3df0ff")


def _rgb(color):
    if isinstance(color, str):
        c = pg.mkColor(color)
        return c.red(), c.green(), c.blue()
    return tuple(color[:3])


def make_live_plot() -> pg.PlotWidget:
    p = pg.PlotWidget()
    p.setMenuEnabled(False)
    p.hideButtons()
    p.setBackground("#04060d")
    vb = p.getViewBox()
    # X ustawia Sparkline.push (setXRange 0..window); Y autoranguje do danych
    # (chyba że Sparkline dostał stały y_range -> setYRange go wyłączy). Bez Y-autorange
    # sparkline NET/DISK (bps ~1e4..1e7) jest pusty — Y stoi na domyślnym (0,1).
    vb.setAutoVisible(y=True)
    vb.enableAutoRange(axis="y")   # X i tak nadpisywany ręcznie przez setXRange (okno follow)
    return p


def make_history_plot() -> pg.PlotWidget:
    p = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
    p.setMenuEnabled(False)
    p.setBackground("#04060d")
    vb = p.getViewBox()
    # X kontrolowany ręcznie (okno follow przez set_window/on_snapshot -> setXRange);
    # Y autoranguje do widocznych danych. Bez tego dane (loadavg ~20, mem ~1e10) leżą
    # nad domyślnym widokiem (0,1) i clipToView je ukrywa -> pusty wykres.
    vb.setAutoVisible(y=True)
    vb.enableAutoRange(axis="y")   # X i tak nadpisywany ręcznie przez setXRange (okno follow)
    return p


def configured_curve(plot: pg.PlotWidget, color=(0, 255, 200), width: int = 1):
    curve = plot.plot(pen=pg.mkPen(color, width=width))
    curve.setDownsampling(auto=True, method="peak")
    curve.setClipToView(True)
    return curve


class _GlowCurve:
    """Neonowa krzywa = jasny rdzeń + szeroki półprzezroczysty underlay (poświata).
    `setData` aktualizuje obie. UWAGA (spec §4.6): podwaja draw-calls — używać TYLKO
    na pojedynczych liniach agregatu (net/disk/loadavg/pkg), NIE na stosach 32×/24×."""

    def __init__(self, *curves):
        self._curves = curves

    def setData(self, xs, ys):
        for c in self._curves:
            c.setData(xs, ys)


def glow_curve(plot: pg.PlotWidget, color=(61, 240, 255), width: int = 2,
               glow_width: int = 9, glow_alpha: int = 60) -> _GlowCurve:
    r, g, b = _rgb(color)
    glow = plot.plot(pen=pg.mkPen((r, g, b, glow_alpha), width=glow_width))
    glow.setDownsampling(auto=True, method="peak")
    glow.setClipToView(True)
    core = plot.plot(pen=pg.mkPen((r, g, b), width=width))
    core.setDownsampling(auto=True, method="peak")
    core.setClipToView(True)
    return _GlowCurve(glow, core)
