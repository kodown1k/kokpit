from PySide6 import QtWidgets

from kokpit.ui.theme.palette import NEON_CYAN, NEON_LIME, NEON_MAGENTA, apply_glow
from kokpit.ui.widgets.gauge import Gauge


def expected_gpu_indices(series_names) -> list[int]:
    idx = set()
    for n in series_names:
        if n.startswith("gpu."):
            try:
                idx.add(int(n.split(".")[1]))
            except (IndexError, ValueError):
                pass
    return sorted(idx)


def gpu_value(snapshot: dict, i: int, field: str) -> float | None:
    return snapshot.get("series", {}).get(f"gpu.{i}.{field}")


class GpuPanel(QtWidgets.QWidget):
    def __init__(self, gpu_indices: list[int]) -> None:
        super().__init__()
        lay = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel("GPU")
        title.setObjectName("tileTitle")
        lay.addWidget(title)
        self._tiles: dict[int, dict] = {}
        for i in gpu_indices:
            row = QtWidgets.QHBoxLayout()
            util = Gauge(f"GPU{i} UTIL", "%", accent=NEON_CYAN)   # high=crit=None → util max = norma
            temp = Gauge(f"GPU{i} TEMP", "°C", high=80, crit=95, accent=NEON_MAGENTA)
            vram = QtWidgets.QLabel("VRAM --")
            vram.setStyleSheet(f"color:{NEON_LIME};font-weight:bold;")
            apply_glow(vram, NEON_LIME, radius=12.0)
            row.addWidget(util)
            row.addWidget(temp)
            row.addWidget(vram)
            lay.addLayout(row)
            self._tiles[i] = {"util": util, "temp": temp, "vram": vram}

    def update_snapshot(self, snapshot: dict) -> None:
        for i, t in self._tiles.items():
            t["util"].set_value(gpu_value(snapshot, i, "util"))   # None → "--"/n/a
            t["temp"].set_value(gpu_value(snapshot, i, "temp"))
            used = gpu_value(snapshot, i, "vram_used")
            total = gpu_value(snapshot, i, "vram_total")
            if used is None or total is None or total == 0:
                t["vram"].setText("VRAM n/a")
            else:
                t["vram"].setText(f"VRAM {used / total * 100:.0f}%")
