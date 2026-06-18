"""Czysta logika Vital-Signs Glyph — BEZ importu Qt (testowalne bez QApplication).

z-score liczony z wygładzonej (EWMA) live, proximity z surowej. Score osi =
max(worst-of z-score po członkach rodziny, proximity). Spec 2026-06-18.
"""
import math
import re

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
