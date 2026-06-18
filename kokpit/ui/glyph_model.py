"""Czysta logika Vital-Signs Glyph — BEZ importu Qt (testowalne bez QApplication).

z-score liczony z wygładzonej (EWMA) live, proximity z surowej. Score osi =
max(worst-of z-score po członkach rodziny, proximity). Spec 2026-06-18.
"""
import math
import re
from dataclasses import dataclass
from typing import Optional

from kokpit import config


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def z_norm(value_sm: float, baseline) -> float:
    """Znormalizowany z-score (0..1). Tylko odchylenia w GÓRĘ (ujemne → 0).
    baseline = (mean, sigma, n, tier) lub None. σ<EPS → 0 (seria stała)."""
    if baseline is None:
        return 0.0
    mean, sigma, _n, _tier = baseline
    if sigma < config.EPS_SIGMA:
        return 0.0
    return clamp01((value_sm - mean) / sigma / config.Z_FULL)


def spike_score(value_sm: float, baseline, proximity) -> float:
    """Długość ramienia 0..1 = max(z-score, proximity). proximity None/0 dla osi
    bez twardego limitu."""
    pp = 0.0 if proximity is None else clamp01(proximity)
    return max(z_norm(value_sm, baseline), pp)


def ewma_alpha() -> float:
    """α dla EWMA przy próbkowaniu 1 Hz i oknie LIVE_EWMA_S (half-life ≈ okno)."""
    return 1.0 - math.exp(-1.0 / config.LIVE_EWMA_S)


def ewma(prev, x: float, alpha: float) -> float:
    return x if prev is None else prev + alpha * (x - prev)


# Partycja: nvme0n1p3 / mmcblk0p2 / sda1 / vdb2. Cały dysk (nvme0n1, sda) → NIE.
_PARTITION_RE = re.compile(r"(nvme\d+n\d+p\d+|mmcblk\d+p\d+|(sd|vd|hd)[a-z]+\d+)$")
_DISK_IO_SUFFIXES = (".read_bps", ".write_bps")


def disk_io_members(keys) -> list:
    out = []
    for k in keys:
        if not k.startswith("disk.") or not k.endswith(_DISK_IO_SUFFIXES):
            continue
        dev = k.split(".", 1)[1].rsplit(".", 1)[0]   # "disk.<dev>.read_bps" → "<dev>"
        if _PARTITION_RE.search(dev):
            continue
        out.append(k)
    return out


def ratio(series: dict, num_key: str, den_key: str):
    num, den = series.get(num_key), series.get(den_key)
    if num is None or not den:        # brak licznika / mianownik None lub 0
        return None
    return num / den


def gpu_vram_ratio(series: dict):
    used = {k[:-len("_used")]: v for k, v in series.items() if k.endswith(".vram_used")}
    best = None
    for base, u in used.items():
        total = series.get(base + "_total")
        if total:
            r = u / total
            best = r if best is None else max(best, r)
    return best


def max_temp_ratio(series: dict, pred, limit: float):
    if not limit:
        return None
    vals = [v / limit for k, v in series.items() if pred(k) and v is not None]
    return max(vals) if vals else None


CPU_TEMP_LIMIT = 95.0
GPU_TEMP_LIMIT = 90.0


@dataclass
class SpokeScore:
    name: str
    score: float
    value: Optional[float]
    tier: Optional[str]
    display: str = ""


_AXIS_CODE: dict = {
    "CPU":      "CPU",
    "RAM":      "RAM",
    "Swap":     "SWP",
    "GPU":      "GPU",
    "VRAM":     "VRAM",
    "CPU temp": "CPU°",
    "GPU temp": "GPU°",
    "Disk IO":  "DISK",
    "Net IO":   "NET",
}


def _fmt_display(name: str, best_val: Optional[float], prox: Optional[float]) -> str:
    code = _AXIS_CODE.get(name, name)
    if name in ("RAM", "VRAM"):
        if prox is None:
            return code
        return f"{code} {round(prox * 100)}%"
    if best_val is None:
        return code
    if name == "GPU":
        return f"{code} {round(best_val)}%"
    if name in ("CPU temp", "GPU temp"):
        return f"{code} {round(best_val)}°"
    if name in ("Disk IO", "Net IO"):
        mb = round(best_val / 1e6)
        return f"{code} {mb}"
    if name == "Swap":
        return f"{code} {round(best_val / 1048576)}M"
    if name == "CPU":
        return f"{code} {best_val:.1f}"
    return code


def _members_suffix(prefix: str, suffix: str):
    return lambda keys: [k for k in keys if k.startswith(prefix) and k.endswith(suffix)]


def _coretemp_pkg(k: str) -> bool:
    return k.startswith("thermal.coretemp.") and k.endswith(".pkg")


def _gpu_temp(k: str) -> bool:
    return k.startswith("gpu.") and k.endswith(".temp")


# (nazwa, z_members(keys)->list, proximity(series)->float|None)
_SPOKES = (
    ("CPU",      lambda keys: [k for k in keys if k == "cpu.loadavg.1"], lambda s: None),
    ("RAM",      lambda keys: [k for k in keys if k == "mem.used"],
                 lambda s: ratio(s, "mem.used", "mem.total")),
    ("Swap",     lambda keys: [k for k in keys if k == "swap.used"], lambda s: None),
    ("GPU",      _members_suffix("gpu.", ".util"), lambda s: None),
    ("VRAM",     _members_suffix("gpu.", ".vram_used"), lambda s: gpu_vram_ratio(s)),
    ("CPU temp", lambda keys: [k for k in keys if _coretemp_pkg(k)],
                 lambda s: max_temp_ratio(s, _coretemp_pkg, CPU_TEMP_LIMIT)),
    ("GPU temp", lambda keys: [k for k in keys if _gpu_temp(k)],
                 lambda s: max_temp_ratio(s, _gpu_temp, GPU_TEMP_LIMIT)),
    ("Disk IO",  lambda keys: disk_io_members(keys), lambda s: None),
    ("Net IO",   lambda keys: [k for k in keys
                               if k.startswith("net.") and k.endswith((".rx_bps", ".tx_bps"))],
                 lambda s: None),
)

SPOKE_NAMES = [name for name, _z, _p in _SPOKES]


class GlyphModel:
    """Stanowy (EWMA per-seria) builder ramion glifu. Zero Qt."""

    def __init__(self) -> None:
        self._sm: dict = {}                 # seria → wygładzona live
        self._alpha = ewma_alpha()
        self.calibrating = True

    def update(self, series: dict, _now_ms: int, provider) -> list:
        keys = list(series.keys())
        any_baseline = False
        spokes = []
        for name, z_members, proximity in _SPOKES:
            best_z = 0.0
            best_val = None
            best_tier = None
            for m in z_members(keys):
                v = series.get(m)
                if v is None:
                    continue
                self._sm[m] = ewma(self._sm.get(m), v, self._alpha)
                base = provider(m)
                if base is not None:
                    any_baseline = True
                z = z_norm(self._sm[m], base)
                if z > best_z or best_val is None:
                    best_z, best_val = z, v
                    best_tier = base[3] if base is not None else best_tier
            prox = proximity(series)
            score = max(best_z, 0.0 if prox is None else clamp01(prox))
            display = _fmt_display(name, best_val, prox)
            spokes.append(SpokeScore(name=name, score=score, value=best_val, tier=best_tier, display=display))
        self.calibrating = not any_baseline
        return spokes


class BaselineCache:
    """Throttluje Store.baseline() — recompute per-seria nie częściej niż
    BASELINE_REFRESH_S. Zwraca (mean,σ,n,tier)|None. Bez Qt."""

    def __init__(self, store, now_fn) -> None:
        self._store = store
        self._now = now_fn
        self._cache: dict = {}     # series → (ts_ms, value)

    def get(self, series: str):
        now = self._now()
        hit = self._cache.get(series)
        if hit is not None and now - hit[0] < config.BASELINE_REFRESH_S * 1000:
            return hit[1]
        try:
            val = self._store.baseline(series, now)
        except Exception:
            return hit[1] if hit is not None else None   # transient error → keep stale cache, retry next tick
        self._cache[series] = (now, val)
        return val
