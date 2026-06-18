"""Kolumna 4 hero-ringów (CPU·GPU·RAM·VRAM) — layout B (lewa strona bento).
Mapuje snapshot 1 Hz na ringi + sub-odczyty (temperatura / GB)."""
from PySide6 import QtWidgets

from kokpit.ui.theme.palette import NEON_CYAN, NEON_LIME
from kokpit.ui.widgets.heatmap import pkg_temp
from kokpit.ui.widgets.ring_gauge import RingGauge


def avg_util(series: dict) -> float | None:
    """Średnia utylizacja po wszystkich cpu.thread.<n>.util (None pomijane)."""
    vals = [v for k, v in series.items()
            if k.startswith("cpu.thread.") and k.endswith(".util") and v is not None]
    return sum(vals) / len(vals) if vals else None


def pct(used: float | None, total: float | None) -> float | None:
    if used is None or not total:
        return None
    return used / total * 100.0


def _fmt_temp(t: float | None) -> str:
    return "" if t is None else f"{t:.0f}°C"


def _fmt_gb(b: float | None) -> str:
    return "" if b is None else f"{b / 1e9:.1f}G"


class HeroColumn(QtWidgets.QWidget):
    def __init__(self, gpu_index: int = 0) -> None:
        super().__init__()
        self._gi = gpu_index
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(8)
        # util max to norma → high=crit=None (zawsze akcent); RAM/VRAM eskalują na alert
        self._cpu = RingGauge("CPU", NEON_CYAN, icon="cpu")
        self._gpu = RingGauge(f"GPU{gpu_index}", NEON_CYAN, icon="gpu")
        self._ram = RingGauge("RAM", NEON_CYAN, icon="ram", high=85, crit=95)
        self._vram = RingGauge("VRAM", NEON_LIME, icon="ram", high=85, crit=95)
        for g in (self._cpu, self._gpu, self._ram, self._vram):
            lay.addWidget(g)
        lay.addStretch(1)   # dociągnij ringi do góry (kolumna bywa wyższa niż treść)

    def update_snapshot(self, snapshot: dict) -> None:
        s = snapshot.get("series", {})
        gi = self._gi
        self._cpu.set_value(avg_util(s))
        self._cpu.set_sub(_fmt_temp(pkg_temp(s)))
        self._gpu.set_value(s.get(f"gpu.{gi}.util"))
        self._gpu.set_sub(_fmt_temp(s.get(f"gpu.{gi}.temp")))
        self._ram.set_value(pct(s.get("mem.used"), s.get("mem.total")))
        self._ram.set_sub(_fmt_gb(s.get("mem.used")))
        self._vram.set_value(pct(s.get(f"gpu.{gi}.vram_used"), s.get(f"gpu.{gi}.vram_total")))
        self._vram.set_sub(_fmt_gb(s.get(f"gpu.{gi}.vram_used")))
