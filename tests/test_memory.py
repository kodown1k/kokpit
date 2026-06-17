import types
from kokpit.sources import memory as mem_mod
from kokpit.sources.memory import MemorySource


def test_memory_sample(monkeypatch):
    monkeypatch.setattr(mem_mod.psutil, "virtual_memory",
                        lambda: types.SimpleNamespace(used=100.0, total=200.0))
    monkeypatch.setattr(mem_mod.psutil, "swap_memory",
                        lambda: types.SimpleNamespace(used=5.0))
    out = MemorySource().sample(now_ms=0, dt_s=1.0)
    assert out == {"mem.used": 100.0, "mem.total": 200.0, "swap.used": 5.0}
