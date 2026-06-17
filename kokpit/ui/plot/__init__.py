import pyqtgraph as pg

# Ustawione wg Task 0 (bench/SPIKE-W2-RESULTS.md). Domyślnie False — włącz tylko jeśli spike tego wymaga.
USE_OPENGL = False

pg.setConfigOptions(antialias=False, useOpenGL=USE_OPENGL, background="#07090f", foreground="#6ad7ff")


def make_live_plot() -> pg.PlotWidget:
    p = pg.PlotWidget()
    p.setMenuEnabled(False)
    p.hideButtons()
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
