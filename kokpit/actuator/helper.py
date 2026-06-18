import glob
import sys

GOVERNOR_GLOB = "/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor"


def _write(path: str, val: str) -> None:
    with open(path, "w") as f:
        f.write(val)


def _governor_paths() -> list[str]:
    return sorted(glob.glob(GOVERNOR_GLOB))


def _available_governors() -> list[str]:
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors") as f:
            return f.read().split()
    except OSError:
        return []


def _nvml_power_bounds_mw(index: int) -> tuple[int, int]:
    import pynvml as n
    n.nvmlInit()
    h = n.nvmlDeviceGetHandleByIndex(index)
    lo, hi = n.nvmlDeviceGetPowerManagementLimitConstraints(h)
    return int(lo), int(hi)


def _nvml_set_power(index: int, milliwatts: int) -> None:
    import pynvml as n
    n.nvmlInit()
    h = n.nvmlDeviceGetHandleByIndex(index)
    n.nvmlDeviceSetPowerManagementLimit(h, milliwatts)


def _nvml_default_power_mw(index: int) -> int:
    import pynvml as n
    n.nvmlInit()
    h = n.nvmlDeviceGetHandleByIndex(index)
    return int(n.nvmlDeviceGetPowerManagementDefaultLimit(h))


def set_governor(name: str) -> int:
    if name not in _available_governors():
        print(f"unknown governor: {name!r}", file=sys.stderr)
        return 2
    for path in _governor_paths():
        _write(path, name)
    return 0


def set_gpu_power(index: int, watts: int) -> int:
    lo, hi = _nvml_power_bounds_mw(index)
    mw = max(lo, min(hi, watts * 1000))
    _nvml_set_power(index, mw)
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return 2
    verb, rest = argv[0], argv[1:]
    try:
        if verb == "governor" and len(rest) == 1:
            return set_governor(rest[0])
        if verb == "gpu-power" and len(rest) == 2:
            return set_gpu_power(int(rest[0]), int(rest[1]))
        if verb == "gpu-power-reset" and len(rest) == 1:
            idx = int(rest[0])
            _nvml_set_power(idx, _nvml_default_power_mw(idx))
            return 0
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 2


def cli() -> None:
    sys.exit(main(sys.argv[1:]))


if __name__ == "__main__":
    cli()
