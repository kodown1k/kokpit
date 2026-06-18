from dataclasses import dataclass

from kokpit import config


@dataclass
class EnvelopePolicy:
    axis: str
    z_trigger: float
    action: dict


def breach(policy: EnvelopePolicy, spoke, baseline) -> bool:
    if baseline is None or spoke.value is None:
        return False
    mean, sigma, _n, _tier = baseline
    if sigma < config.EPS_SIGMA:
        return False
    z = (spoke.value - mean) / sigma
    return z >= policy.z_trigger


DEFAULT_POLICIES = [
    EnvelopePolicy(
        axis="GPU temp", z_trigger=config.ENVELOPE_Z_TRIGGER,
        action={"lever": "gpu_power", "target": {"index": 0},
                "params": {"watts": config.GPU_POWER_FLOOR_W},
                "ttl_s": config.ENVELOPE_DEFAULT_TTL_S},
    ),
    EnvelopePolicy(
        axis="CPU temp", z_trigger=config.ENVELOPE_Z_TRIGGER,
        action={"lever": "governor", "target": {},
                "params": {"name": "powersave"},
                "ttl_s": config.ENVELOPE_DEFAULT_TTL_S},
    ),
]


# axis name -> series the baseline is keyed on (mirror glyph_model spokes)
_AXIS_SERIES = {
    "GPU temp": None,   # resolved by caller via baseline_for on the spoke's series
    "CPU temp": None,
}


class EnvelopeEvaluator:
    def __init__(self, policies, debounce_s, now_fn) -> None:
        self._policies = policies
        self._debounce_ms = debounce_s * 1000
        self._now = now_fn
        self._breach_since: dict[str, float] = {}   # axis -> first-breach ms
        self._fired: set[str] = set()               # axis episodes already actioned

    def evaluate(self, spokes, baseline_for) -> list[dict]:
        by_axis = {s.name: s for s in spokes}
        out = []
        for pol in self._policies:
            spoke = by_axis.get(pol.axis)
            base = baseline_for(pol.axis) if spoke is not None else None
            if spoke is not None and breach(pol, spoke, base):
                start = self._breach_since.setdefault(pol.axis, self._now())
                if pol.axis not in self._fired and self._now() - start >= self._debounce_ms:
                    out.append(pol.action)
                    self._fired.add(pol.axis)
            else:
                self._breach_since.pop(pol.axis, None)
                self._fired.discard(pol.axis)
        return out
