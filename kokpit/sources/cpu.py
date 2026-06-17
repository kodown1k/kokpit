import psutil
from kokpit.sources.base import Sample


class CpuSource:
    name = "cpu"

    def sample(self, now_ms: int, dt_s: float) -> Sample:
        out: Sample = {}
        for i, pct in enumerate(psutil.cpu_percent(percpu=True)):
            out[f"cpu.thread.{i}.util"] = float(pct)
        freqs = psutil.cpu_freq(percpu=True) or []
        for i, f in enumerate(freqs):
            out[f"cpu.thread.{i}.freq"] = float(f.current)
        try:
            la1 = psutil.getloadavg()[0]
            out["cpu.loadavg.1"] = float(la1)
        except (OSError, AttributeError):
            pass
        return out
