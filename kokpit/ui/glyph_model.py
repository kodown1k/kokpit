"""Czysta logika Vital-Signs Glyph — BEZ importu Qt (testowalne bez QApplication).

z-score liczony z wygładzonej (EWMA) live, proximity z surowej. Score osi =
max(worst-of z-score po członkach rodziny, proximity). Spec 2026-06-18.
"""
import math

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
