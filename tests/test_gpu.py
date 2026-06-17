import types
from kokpit.sources.gpu import GpuSource


def _fake_nvml():
    n = types.SimpleNamespace()
    n.NVML_TEMPERATURE_GPU = 0
    n.NVML_CLOCK_SM = 1
    n.nvmlDeviceGetCount = lambda: 1
    n.nvmlDeviceGetHandleByIndex = lambda i: f"h{i}"
    n.nvmlDeviceGetUtilizationRates = lambda h: types.SimpleNamespace(gpu=63)
    n.nvmlDeviceGetMemoryInfo = lambda h: types.SimpleNamespace(used=11.2e9, total=16e9)
    n.nvmlDeviceGetTemperature = lambda h, kind: 71
    n.nvmlDeviceGetPowerUsage = lambda h: 120000      # mW -> 120 W
    n.nvmlDeviceGetClockInfo = lambda h, kind: 2400
    n.nvmlDeviceGetFanSpeed = lambda h: 45
    return n


def test_gpu_sample():
    out = GpuSource(nvml=_fake_nvml()).sample(now_ms=0, dt_s=1.0)
    assert out["gpu.0.util"] == 63.0
    assert out["gpu.0.vram_used"] == 11.2e9
    assert out["gpu.0.temp"] == 71.0
    assert out["gpu.0.power"] == 120.0
    assert out["gpu.0.clock_sm"] == 2400.0
    assert out["gpu.0.fan"] == 45.0


def test_gpu_zero_devices_returns_empty():
    n = _fake_nvml()
    n.nvmlDeviceGetCount = lambda: 0
    assert GpuSource(nvml=n).sample(now_ms=0, dt_s=1.0) == {}


def test_gpu_no_nvml_returns_empty():
    src = GpuSource.__new__(GpuSource)   # pomiń __init__/import
    src._nvml = None
    assert src.sample(now_ms=0, dt_s=1.0) == {}
