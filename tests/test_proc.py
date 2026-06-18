import types
from kokpit.proc import ProcCollector
from kokpit import proc as proc_mod


def _nvml_two_gpus():
    """Fake NVML: pid 2 trzyma compute na GPU0 i GPU1, pid 3 tylko graphics na GPU1."""
    n = types.SimpleNamespace()
    n.nvmlDeviceGetCount = lambda: 2
    n.nvmlDeviceGetHandleByIndex = lambda i: f"h{i}"

    def compute(h):
        if h == "h0":
            return [types.SimpleNamespace(pid=2, usedGpuMemory=4096)]
        return [types.SimpleNamespace(pid=2, usedGpuMemory=1024)]

    def graphics(h):
        if h == "h1":
            return [types.SimpleNamespace(pid=3, usedGpuMemory=8192)]
        return []

    n.nvmlDeviceGetComputeRunningProcesses = compute
    n.nvmlDeviceGetGraphicsRunningProcesses = graphics
    return n


def test_gpu_top_aggregates_vram_type_and_gpu_indices(monkeypatch):
    monkeypatch.setattr(proc_mod.psutil, "Process",
                        lambda pid: types.SimpleNamespace(name=lambda: f"proc{pid}"))
    rows = ProcCollector(nvml=_nvml_two_gpus()).gpu_top()
    # sort po VRAM malejąco: pid2 ma 4096+1024=5120, pid3 ma 8192
    assert [r["pid"] for r in rows] == [3, 2]
    pid2 = next(r for r in rows if r["pid"] == 2)
    pid3 = next(r for r in rows if r["pid"] == 3)
    assert pid2["vram"] == 5120.0          # zsumowane po obu GPU
    assert pid2["gpus"] == [0, 1]          # na obu kartach
    assert pid2["type"] == "C"             # tylko compute
    assert pid3["gpus"] == [1]
    assert pid3["type"] == "G"             # tylko graphics
    assert pid3["name"] == "proc3"


def test_gpu_top_marks_compute_and_graphics_as_cplusg(monkeypatch):
    monkeypatch.setattr(proc_mod.psutil, "Process",
                        lambda pid: types.SimpleNamespace(name=lambda: ""))
    n = types.SimpleNamespace()
    n.nvmlDeviceGetCount = lambda: 1
    n.nvmlDeviceGetHandleByIndex = lambda i: "h"
    n.nvmlDeviceGetComputeRunningProcesses = lambda h: [types.SimpleNamespace(pid=7, usedGpuMemory=10)]
    n.nvmlDeviceGetGraphicsRunningProcesses = lambda h: [types.SimpleNamespace(pid=7, usedGpuMemory=20)]
    rows = ProcCollector(nvml=n).gpu_top()
    assert rows[0]["type"] == "C+G"
    assert rows[0]["vram"] == 30.0


def test_gpu_top_merges_per_process_utilization(monkeypatch):
    monkeypatch.setattr(proc_mod.psutil, "Process",
                        lambda pid: types.SimpleNamespace(name=lambda: ""))
    n = _nvml_two_gpus()
    n.nvmlDeviceGetProcessUtilization = lambda h, since: [
        types.SimpleNamespace(pid=2, timeStamp=1000, smUtil=30, memUtil=12, encUtil=5, decUtil=0),
    ]
    rows = ProcCollector(nvml=n).gpu_top()
    pid2 = next(r for r in rows if r["pid"] == 2)
    assert pid2["sm"] == 30.0
    assert pid2["enc"] == 5.0
    assert pid2["dec"] == 0.0


def test_gpu_top_no_nvml_is_empty():
    assert ProcCollector(nvml=None).gpu_top() == []


def test_snapshot_returns_both_lists_computing_gpu_info_once(monkeypatch):
    monkeypatch.setattr(proc_mod.psutil, "process_iter", lambda attrs: [])
    monkeypatch.setattr(proc_mod.psutil, "Process",
                        lambda pid: types.SimpleNamespace(name=lambda: ""))
    calls = {"n": 0}
    n = _nvml_two_gpus()
    orig_count = n.nvmlDeviceGetCount

    def counting():
        calls["n"] += 1
        return orig_count()

    n.nvmlDeviceGetCount = counting
    procs, gpu_procs = ProcCollector(nvml=n).snapshot()
    assert procs == []
    assert [r["pid"] for r in gpu_procs] == [3, 2]
    assert calls["n"] == 1                  # GPU info policzone raz na tick


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
