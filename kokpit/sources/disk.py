import psutil
from kokpit.config import DISK_DENY
from kokpit.sources.base import RateCounter, Sample


class DiskSource:
    name = "disk"

    def __init__(self) -> None:
        self._r: dict[str, RateCounter] = {}
        self._w: dict[str, RateCounter] = {}

    def sample(self, now_ms: int, dt_s: float) -> Sample:
        out: Sample = {}
        for dev, c in (psutil.disk_io_counters(perdisk=True) or {}).items():
            if DISK_DENY.match(dev):
                continue
            r = self._r.setdefault(dev, RateCounter()).update(c.read_bytes, dt_s)
            w = self._w.setdefault(dev, RateCounter()).update(c.write_bytes, dt_s)
            if r is not None:
                out[f"disk.{dev}.read_bps"] = r
            if w is not None:
                out[f"disk.{dev}.write_bps"] = w
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            out[f"disk.{part.mountpoint}.used_pct"] = float(usage.percent)
        return out
