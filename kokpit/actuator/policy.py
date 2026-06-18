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
