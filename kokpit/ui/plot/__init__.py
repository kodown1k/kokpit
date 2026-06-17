import pyqtgraph as pg

# Ustawione wg Task 0 (bench/SPIKE-W2-RESULTS.md). Domyślnie False — włącz tylko jeśli spike tego wymaga.
USE_OPENGL = False

pg.setConfigOptions(antialias=False, useOpenGL=USE_OPENGL, background="#07090f", foreground="#6ad7ff")


def make_live_plot() -> pg.PlotWidget:
    p = pg.PlotWidget()
    p.setMenuEnabled(False)
    p.hideButtons()
    p.disableAutoRange()
    return p


def make_history_plot() -> pg.PlotWidget:
    p = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
    p.setMenuEnabled(False)
    p.disableAutoRange()
    return p


def configured_curve(plot: pg.PlotWidget, color=(0, 255, 200), width: int = 1):
    curve = plot.plot(pen=pg.mkPen(color, width=width))
    curve.setDownsampling(auto=True, method="peak")
    curve.setClipToView(True)
    return curve
