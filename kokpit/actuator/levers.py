import logging
import subprocess
from abc import ABC, abstractmethod

import psutil

log = logging.getLogger("kokpit.actuator.levers")


class LeverError(Exception):
    pass


def run_argv(argv: list[str]) -> str:
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as e:
        raise LeverError(f"{argv[0]}: {e}") from e
    if cp.returncode != 0:
        raise LeverError(f"{' '.join(argv)} -> rc={cp.returncode}: {cp.stderr.strip()}")
    return cp.stdout


def _current_nice(pid: int) -> int:
    try:
        return int(psutil.Process(pid).nice())
    except Exception:
        return 0


class Lever(ABC):
    id: str = ""
    requires_privilege: bool = False

    def __init__(self, executor=run_argv) -> None:
        self._run = executor

    @abstractmethod
    def apply(self, target: dict, params: dict) -> dict: ...

    @abstractmethod
    def revert(self, token_state: dict) -> None: ...


class ReniceLever(Lever):
    id = "renice"

    def apply(self, target: dict, params: dict) -> dict:
        pid = int(target["pid"])
        prior = _current_nice(pid)
        self._run(["renice", "-n", str(int(params["value"])), "-p", str(pid)])
        return {"pid": pid, "prior_nice": prior}

    def revert(self, token_state: dict) -> None:
        self._run(["renice", "-n", str(token_state["prior_nice"]), "-p", str(token_state["pid"])])


class IoniceLever(Lever):
    id = "ionice"

    def apply(self, target: dict, params: dict) -> dict:
        pid = int(target["pid"])
        self._run(["ionice", "-c", "2", "-n", str(int(params["value"])), "-p", str(pid)])
        return {"pid": pid}

    def revert(self, token_state: dict) -> None:
        self._run(["ionice", "-c", "2", "-n", "4", "-p", str(token_state["pid"])])


def _current_governor() -> str:
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor") as f:
            return f.read().strip()
    except OSError:
        return ""


class GpuPowerLever(Lever):
    id = "gpu_power"
    requires_privilege = True

    def apply(self, target: dict, params: dict) -> dict:
        idx = int(target["index"])
        self._run(["pkexec", "kokpit-actl-helper", "gpu-power", str(idx), str(int(params["watts"]))])
        return {"index": idx}

    def revert(self, token_state: dict) -> None:
        self._run(["pkexec", "kokpit-actl-helper", "gpu-power-reset", str(token_state["index"])])


class GovernorLever(Lever):
    id = "governor"
    requires_privilege = True

    def apply(self, target: dict, params: dict) -> dict:
        prior = _current_governor()
        self._run(["pkexec", "kokpit-actl-helper", "governor", str(params["name"])])
        return {"prior": prior}

    def revert(self, token_state: dict) -> None:
        prior = token_state.get("prior")
        if prior is None:
            # 'prior' key missing entirely — nothing to restore
            return
        if not prior:
            log.warning("GovernorLever.revert: prior governor is empty string, cannot restore")
            return
        self._run(["pkexec", "kokpit-actl-helper", "governor", prior])


LEVERS: dict[str, Lever] = {
    "renice": ReniceLever(),
    "ionice": IoniceLever(),
    "gpu_power": GpuPowerLever(),
    "governor": GovernorLever(),
}
