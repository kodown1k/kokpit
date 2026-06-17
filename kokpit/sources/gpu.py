import logging
from kokpit.sources.base import Sample

log = logging.getLogger("kokpit.gpu")


class GpuSource:
    name = "gpu"

    def __init__(self, nvml=None) -> None:
        if nvml is not None:
            self._nvml = nvml
            return
        try:
            import pynvml  # pakiet: nvidia-ml-py
            pynvml.nvmlInit()
            self._nvml = pynvml
        except Exception:
            log.warning("NVML niedostępne — GPU pominięte")
            self._nvml = None

    def sample(self, now_ms: int, dt_s: float) -> Sample:
        n = self._nvml
        if n is None:
            return {}
        out: Sample = {}
        try:
            count = n.nvmlDeviceGetCount()
        except Exception:
            return {}
        for i in range(count):
            try:
                h = n.nvmlDeviceGetHandleByIndex(i)
                util = n.nvmlDeviceGetUtilizationRates(h)
                mem = n.nvmlDeviceGetMemoryInfo(h)
                out[f"gpu.{i}.util"] = float(util.gpu)
                out[f"gpu.{i}.vram_used"] = float(mem.used)
                out[f"gpu.{i}.vram_total"] = float(mem.total)
                out[f"gpu.{i}.temp"] = float(n.nvmlDeviceGetTemperature(h, n.NVML_TEMPERATURE_GPU))
                out[f"gpu.{i}.power"] = float(n.nvmlDeviceGetPowerUsage(h)) / 1000.0
                out[f"gpu.{i}.clock_sm"] = float(n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_SM))
                try:
                    out[f"gpu.{i}.fan"] = float(n.nvmlDeviceGetFanSpeed(h))
                except Exception:
                    pass
            except Exception:
                log.exception("Odczyt GPU %d nieudany", i)
                continue
        return out
