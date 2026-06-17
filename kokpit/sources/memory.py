import psutil
from kokpit.sources.base import Sample


class MemorySource:
    name = "memory"

    def sample(self, now_ms: int, dt_s: float) -> Sample:
        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        return {
            "mem.used": float(vm.used),
            "mem.total": float(vm.total),
            "swap.used": float(sm.used),
        }
