import logging
import psutil

log = logging.getLogger("kokpit.proc")


def _type_str(types_set: set[str]) -> str:
    """Zamienia zbiór tagów na etykietę jak w nvidia-smi: C / G / C+G."""
    if "C" in types_set and "G" in types_set:
        return "C+G"
    if "C" in types_set:
        return "C"
    if "G" in types_set:
        return "G"
    return ""


class ProcCollector:
    def __init__(self, top_n: int = 8, nvml=None, gpu_top_n: int = 8) -> None:
        self.top_n = top_n
        self.gpu_top_n = gpu_top_n
        self._nvml = nvml
        self._util_ts: dict[int, int] = {}   # per-GPU timestamp ostatniej próbki util

    def _gpu_info_by_pid(self) -> dict[int, dict]:
        """Zbiera per-PID dane GPU z NVML (jak tabela Processes w nvidia-smi):
        VRAM (suma po kartach), indeksy GPU, typ (compute/graphics) i util SM/enc/dec."""
        n = self._nvml
        if n is None:
            return {}
        info: dict[int, dict] = {}
        try:
            count = n.nvmlDeviceGetCount()
        except Exception:
            return {}
        for i in range(count):
            try:
                h = n.nvmlDeviceGetHandleByIndex(i)
            except Exception:
                continue
            for fn, tag in ((n.nvmlDeviceGetComputeRunningProcesses, "C"),
                            (n.nvmlDeviceGetGraphicsRunningProcesses, "G")):
                try:
                    running = fn(h)
                except Exception:
                    continue
                for p in running:
                    rec = info.setdefault(p.pid, {
                        "vram": 0.0, "gpus": set(), "types": set(),
                        "sm": 0.0, "enc": 0.0, "dec": 0.0,
                    })
                    used = getattr(p, "usedGpuMemory", None)
                    if used:
                        rec["vram"] += float(used)
                    rec["gpus"].add(i)
                    rec["types"].add(tag)
            self._merge_utilization(n, h, i, info)
        return info

    def _merge_utilization(self, n, h, gpu_idx: int, info: dict[int, dict]) -> None:
        """Dokleja per-proces SM/enc/dec% z nvmlDeviceGetProcessUtilization (bywa puste/flaky)."""
        since = self._util_ts.get(gpu_idx, 0)
        try:
            samples = n.nvmlDeviceGetProcessUtilization(h, since)
        except Exception:
            return
        newest = since
        for s in samples or []:
            rec = info.get(s.pid)
            if rec is not None:
                rec["sm"] = max(rec["sm"], float(getattr(s, "smUtil", 0)))
                rec["enc"] = max(rec["enc"], float(getattr(s, "encUtil", 0)))
                rec["dec"] = max(rec["dec"], float(getattr(s, "decUtil", 0)))
            ts = int(getattr(s, "timeStamp", 0))
            if ts > newest:
                newest = ts
        self._util_ts[gpu_idx] = newest

    def _proc_name(self, pid: int) -> str:
        try:
            return psutil.Process(pid).name()
        except Exception:
            return ""

    def top(self, ginfo: dict[int, dict] | None = None) -> list[dict]:
        if ginfo is None:
            ginfo = self._gpu_info_by_pid()
        rows: list[dict] = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            info = p.info
            mi = info.get("memory_info")
            pid = info["pid"]
            rows.append({
                "pid": pid,
                "name": info.get("name") or "",
                "cpu": float(info.get("cpu_percent") or 0.0),
                "rss": float(mi.rss if mi else 0.0),
                "vram": float(ginfo.get(pid, {}).get("vram", 0.0)),
            })
        rows.sort(key=lambda d: d["cpu"], reverse=True)
        return rows[: self.top_n]

    def gpu_top(self, ginfo: dict[int, dict] | None = None) -> list[dict]:
        """Lista procesów GPU posortowana po VRAM malejąco (jak sekcja Processes w nvidia-smi)."""
        if ginfo is None:
            ginfo = self._gpu_info_by_pid()
        rows: list[dict] = []
        for pid, rec in ginfo.items():
            rows.append({
                "pid": pid,
                "name": self._proc_name(pid),
                "vram": float(rec["vram"]),
                "gpus": sorted(rec["gpus"]),
                "type": _type_str(rec["types"]),
                "sm": float(rec["sm"]),
                "enc": float(rec["enc"]),
                "dec": float(rec["dec"]),
            })
        rows.sort(key=lambda d: d["vram"], reverse=True)
        return rows[: self.gpu_top_n]

    def snapshot(self) -> tuple[list[dict], list[dict]]:
        """Jeden odczyt NVML na tick → (top procesów po CPU, top procesów GPU po VRAM)."""
        ginfo = self._gpu_info_by_pid()
        return self.top(ginfo), self.gpu_top(ginfo)
