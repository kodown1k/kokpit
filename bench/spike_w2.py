"""Spike W2: zmierz fps i %CPU pełnego bento na tej maszynie.
Uruchom: .venv/bin/python bench/spike_w2.py [--opengl]
Renderuje 32 krzywe (~300 pkt), 2 siatki kafli (32/24), 6 gauge'y, 1 history-stos
i przez 10 s liczy klatki + czas CPU procesu. Decyzja zapisywana ręcznie do SPIKE-W2-RESULTS.md.
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")  # realny render; offscreen = nierzetelny fps

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

USE_OPENGL = "--opengl" in sys.argv
pg.setConfigOptions(antialias=False, useOpenGL=USE_OPENGL)


def build_window() -> tuple[QtWidgets.QWidget, list]:
    w = QtWidgets.QWidget()
    grid = QtWidgets.QGridLayout(w)
    curves = []
    # 32 sparkline w jednym ViewBox (wariant "shared ViewBox/wiele krzywych")
    plot = pg.PlotWidget()
    plot.setMenuEnabled(False)
    plot.disableAutoRange()
    plot.setYRange(0, 100)
    plot.setXRange(0, 300)
    for i in range(32):
        c = plot.plot(pen=pg.mkPen((i * 7 % 255, 200, 255 - (i * 5 % 255))))
        c.setDownsampling(auto=True, method="peak")
        c.setClipToView(True)
        curves.append(c)
    grid.addWidget(plot, 0, 0, 1, 4)
    # history stos: 4 wykresy z DateAxis
    for r in range(4):
        hp = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        hp.disableAutoRange()
        hc = hp.plot(pen=pg.mkPen((0, 255, 200)))
        hc.setDownsampling(auto=True, method="peak")
        hc.setClipToView(True)
        curves.append(hc)
        grid.addWidget(hp, 1 + r, 0, 1, 4)
    return w, curves


def main() -> int:
    app = QtWidgets.QApplication([])
    w, curves = build_window()
    w.resize(1400, 900)
    w.show()

    x = np.arange(300, dtype=float)
    frames = {"n": 0}
    t_cpu0 = time.process_time()
    t_wall0 = time.perf_counter()

    def tick():
        n = frames["n"]
        for c in curves:
            c.setData(x, 50 + 40 * np.sin(x / 20.0 + n / 5.0 + id(c) % 7))
        frames["n"] += 1

    timer = QtCore.QTimer()
    timer.timeout.connect(tick)
    timer.start(0)  # render tak szybko jak się da → mierzymy sufit

    def stop():
        wall = time.perf_counter() - t_wall0
        cpu = time.process_time() - t_cpu0
        fps = frames["n"] / wall
        print(f"opengl={USE_OPENGL}  frames={frames['n']}  fps={fps:.1f}  "
              f"cpu%={100 * cpu / wall:.1f}  (wall={wall:.1f}s)")
        app.quit()

    QtCore.QTimer.singleShot(10_000, stop)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
