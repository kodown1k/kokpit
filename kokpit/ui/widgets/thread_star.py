"""ThreadStar — przyjazna animowana rozgwiazda: każde ramię = util jednego wątku CPU.
Czyste funkcje geometrii/animacji (testowalne bez Qt) oddzielone od paintEvent —
wzorzec jak w kokpit/ui/widgets/vital_glyph.py. Spec 2026-06-19."""
import math

from kokpit.ui.glyph_model import clamp01

EASE = 0.22
SETTLE_EPS = 0.002
TICK_MS = 25                # ~40 fps; timer biegnie ciągle (oddech), 1 paint/tick

R_BODY = 26.0               # promień centralnego dysku (przed skalą)
R_ARM_MIN = 16.0            # długość stubu przy 0% utilu (idle = wciąż rozgwiazda)
R_ARM_SPAN = 82.0           # dodatkowa długość przy 100% utilu
R_MAX = R_BODY + R_ARM_MIN + R_ARM_SPAN   # 124 — max zasięg czubka
MARGIN = 18.0              # margines do krawędzi widgetu
GLOW_THRESHOLD = 0.55      # próg bloomu dla zajętych ramion
BREATH_AMP_R = 3.0         # px (przed skalą) — puls promienia (oddech)
BREATH_AMP_A = 0.045       # rad — kołysanie kąta ramienia
BASE_HALF_ANG = 0.30       # rad — połowa kątowej szerokości bazy ramienia na ciele


def arm_angle(i: int, n: int) -> float:
    return -math.pi / 2 + 2 * math.pi * i / n


def arm_reach(body_r: float, arm_min: float, arm_span: float, frac: float) -> float:
    return body_r + arm_min + arm_span * clamp01(frac)


def ease_step(current, target, eps: float = SETTLE_EPS, ease: float = EASE):
    nxt, moving = [], False
    for c, t in zip(current, target):
        c2 = c + (t - c) * ease
        if abs(t - c2) >= eps:
            moving = True
        nxt.append(c2)
    return nxt, moving


def breath_offset(phase: int, i: int, n: int,
                  amp_r: float = BREATH_AMP_R, amp_a: float = BREATH_AMP_A):
    dr = amp_r * math.sin(phase * 0.06)
    da = amp_a * math.sin(phase * 0.05 + i * (2 * math.pi / max(1, n)))
    return dr, da
