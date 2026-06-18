import re

from kokpit import config

_MIN_RE = re.compile(r"(\d+)\s*min")
_GPU_RE = re.compile(r"(\d+)\s*w?\b", re.IGNORECASE)


def _ttl_from(text: str, default_s: float) -> float:
    m = _MIN_RE.search(text)
    return int(m.group(1)) * 60 if m else default_s


def parse_intent(text: str) -> dict | None:
    t = text.lower().strip()
    if any(k in t for k in ("zwolnij wszystko", "release all", "odblokuj")):
        return {"verb": "revert_all"}
    if "cicho" in t or "quiet" in t:
        return {"verb": "apply", "lever": "governor", "target": {},
                "params": {"name": "powersave"}, "ttl_s": _ttl_from(t, 1800)}
    if "max" in t or "performance" in t:
        return {"verb": "apply", "lever": "governor", "target": {},
                "params": {"name": "performance"}, "ttl_s": config.ENVELOPE_DEFAULT_TTL_S}
    if "gpu" in t and ("cap" in t or "limit" in t):
        m = _GPU_RE.search(t.split("gpu", 1)[1])
        if m:
            return {"verb": "apply", "lever": "gpu_power", "target": {"index": 0},
                    "params": {"watts": int(m.group(1))}, "ttl_s": config.ENVELOPE_DEFAULT_TTL_S}
    return None
