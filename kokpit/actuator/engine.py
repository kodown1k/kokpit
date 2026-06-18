import logging

from kokpit.actuator.levers import LeverError

log = logging.getLogger("kokpit.actuator.engine")


class Actuator:
    def __init__(self, levers: dict, audit, now_fn) -> None:
        self._levers = levers
        self._audit = audit
        self._now = now_fn
        self._seq = 0
        self._active: dict[str, dict] = {}   # token -> {lever, target, params, state, deadline_ms}

    def apply(self, lever_id: str, target: dict, params: dict, ttl_s: float | None) -> str:
        lever = self._levers[lever_id]
        state = lever.apply(target, params)
        self._seq += 1
        token = f"{lever_id}-{self._seq}"
        deadline = None if ttl_s is None else self._now() + int(ttl_s * 1000)
        self._active[token] = {
            "lever": lever_id, "target": target, "params": params,
            "state": state, "deadline_ms": deadline,
        }
        self._audit.record("apply", {"token": token, "lever": lever_id,
                                     "target": target, "params": params, "ttl_s": ttl_s})
        return token

    def revert(self, token: str) -> None:
        entry = self._active.pop(token, None)
        if entry is None:
            return  # idempotent
        try:
            self._levers[entry["lever"]].revert(entry["state"])
        except LeverError:
            log.exception("revert failed for %s", token)
        self._audit.record("revert", {"token": token})

    def revert_all(self) -> int:
        count = 0
        for token in list(self._active):
            self.revert(token)
            count += 1
        return count

    def list_active(self) -> list[dict]:
        return [{"token": t, "lever": e["lever"], "target": e["target"],
                 "params": e["params"], "deadline_ms": e["deadline_ms"]}
                for t, e in self._active.items()]

    def tick(self, now_ms: int) -> None:
        for token, e in list(self._active.items()):
            dl = e["deadline_ms"]
            if dl is not None and now_ms >= dl:
                entry = self._active.pop(token, None)
                if entry is None:
                    continue
                try:
                    self._levers[entry["lever"]].revert(entry["state"])
                except LeverError:
                    log.exception("auto-revert failed for %s", token)
                self._audit.record("auto_revert", {"token": token})
