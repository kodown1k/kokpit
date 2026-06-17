import logging
import psutil

log = logging.getLogger("kokpit.proc")


class ProcCollector:
    def __init__(self, top_n: int = 8, nvml=None) -> None:
        self.top_n = top_n
        self._nvml = nvml

    def _vram_by_pid(self) -> dict[int, float]:
        n = self._nvml
        if n is None:
            return {}
        out: dict[int, float] = {}
        try:
            for i in range(n.nvmlDeviceGetCount()):
                h = n.nvmlDeviceGetHandleByIndex(i)
                for fn in (n.nvmlDeviceGetComputeRunningProcesses,
                           n.nvmlDeviceGetGraphicsRunningProcesses):
                    try:
                        for p in fn(h):
                            used = getattr(p, "usedGpuMemory", None)
                            if used:
                                out[p.pid] = out.get(p.pid, 0.0) + float(used)
                    except Exception:
                        continue
        except Exception:
            return {}
        return out

    def top(self) -> list[dict]:
        vram = self._vram_by_pid()
        rows: list[dict] = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            info = p.info
            mi = info.get("memory_info")
            rows.append({
                "pid": info["pid"],
                "name": info.get("name") or "",
                "cpu": float(info.get("cpu_percent") or 0.0),
                "rss": float(mi.rss if mi else 0.0),
                "vram": float(vram.get(info["pid"], 0.0)),
            })
        rows.sort(key=lambda d: d["cpu"], reverse=True)
        return rows[: self.top_n]
