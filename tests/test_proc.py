import types
from kokpit.proc import ProcCollector
from kokpit import proc as proc_mod


def test_top_sorts_and_merges_vram(monkeypatch):
    procs = [
        types.SimpleNamespace(info={"pid": 1, "name": "a", "cpu_percent": 5.0,
                                    "memory_info": types.SimpleNamespace(rss=100)}),
        types.SimpleNamespace(info={"pid": 2, "name": "b", "cpu_percent": 50.0,
                                    "memory_info": types.SimpleNamespace(rss=200)}),
    ]
    monkeypatch.setattr(proc_mod.psutil, "process_iter", lambda attrs: procs)
    n = types.SimpleNamespace()
    n.nvmlDeviceGetCount = lambda: 1
    n.nvmlDeviceGetHandleByIndex = lambda i: "h"
    n.nvmlDeviceGetComputeRunningProcesses = lambda h: [types.SimpleNamespace(pid=2, usedGpuMemory=4096)]
    n.nvmlDeviceGetGraphicsRunningProcesses = lambda h: []
    out = ProcCollector(top_n=2, nvml=n).top()
    assert [p["pid"] for p in out] == [2, 1]      # sort po cpu malejąco
    assert out[0]["vram"] == 4096.0               # zmergowane po PID
    assert out[1]["vram"] == 0.0
