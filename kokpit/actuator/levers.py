import subprocess
from abc import ABC, abstractmethod

import psutil


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


LEVERS: dict[str, Lever] = {
    "renice": ReniceLever(),
    "ionice": IoniceLever(),
}
