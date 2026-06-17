import json
import subprocess
from kokpit.sources.base import Sample


def _first_input(vals) -> float | None:
    if not isinstance(vals, dict):
        return None
    for k, v in vals.items():
        if k.endswith("_input"):
            return float(v)
    return None


class ThermalSource:
    name = "thermal"

    def __init__(self, runner=None) -> None:
        self._runner = runner or self._run_sensors

    @staticmethod
    def _run_sensors() -> str:
        return subprocess.run(
            ["sensors", "-j"], capture_output=True, text=True, timeout=5
        ).stdout

    def sample(self, now_ms: int, dt_s: float) -> Sample:
        try:
            data = json.loads(self._runner() or "{}")
        except (json.JSONDecodeError, subprocess.SubprocessError, FileNotFoundError, OSError):
            return {}
        out: Sample = {}
        nvme_idx = 0
        for chip, feats in data.items():
            if not isinstance(feats, dict):
                continue
            if chip.startswith("coretemp"):
                for feat, vals in feats.items():
                    if feat.startswith("Package id"):
                        t = _first_input(vals)
                        if t is not None:
                            out["thermal.pkg"] = t
                    elif feat.startswith("Core "):
                        t = _first_input(vals)
                        if t is not None:
                            out[f"thermal.core.{feat.split()[1]}"] = t
            elif chip.startswith("nvme"):
                t = _first_input(feats.get("Composite"))
                if t is not None:
                    out[f"thermal.nvme.{nvme_idx}"] = t
                    nvme_idx += 1
            elif "iwlwifi" in chip or "wifi" in chip:
                for vals in feats.values():
                    t = _first_input(vals)
                    if t is not None:
                        out["thermal.wifi"] = t
                        break
        return out
