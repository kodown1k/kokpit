from dataclasses import dataclass

from kokpit.actuator.policy import breach


@dataclass
class Proposal:
    id: str
    text: str
    action: dict


_TEXT = {
    "gpu_power": "GPU grzeje się powyżej normy — ograniczyć moc do {watts} W?",
    "governor": "CPU grzeje się powyżej normy — przełączyć governor na {name}?",
}


class Proposer:
    def __init__(self, policies, now_fn) -> None:
        self._policies = policies
        self._now = now_fn
        self._seq = 0
        self._pending: dict[str, Proposal] = {}

    def propose(self, spokes, baseline_for) -> list[Proposal]:
        by_axis = {s.name: s for s in spokes}
        out = []
        for pol in self._policies:
            spoke = by_axis.get(pol.axis)
            base = baseline_for(pol.axis) if spoke is not None else None
            if spoke is not None and breach(pol, spoke, base):
                self._seq += 1
                pid = f"prop-{self._seq}"
                lever = pol.action["lever"]
                text = _TEXT.get(lever, "Zaproponowana akcja").format(**pol.action["params"])
                prop = Proposal(id=pid, text=text, action=pol.action)
                self._pending[pid] = prop
                out.append(prop)
        return out

    def pending(self) -> list[Proposal]:
        return list(self._pending.values())

    def take(self, pid: str):
        return self._pending.pop(pid, None)
