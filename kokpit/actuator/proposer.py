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
        # axis -> proposal id: prevents duplicate proposals for the same axis
        self._axis_pending: dict[str, str] = {}

    def propose(self, spokes, baseline_for) -> list[Proposal]:
        by_axis = {s.name: s for s in spokes}
        out = []
        for pol in self._policies:
            spoke = by_axis.get(pol.axis)
            base = baseline_for(pol.axis) if spoke is not None else None
            if spoke is not None and breach(pol, spoke, base):
                # Skip if there is already a pending proposal for this axis.
                if pol.axis in self._axis_pending:
                    continue
                self._seq += 1
                pid = f"prop-{self._seq}"
                lever = pol.action["lever"]
                text = _TEXT.get(lever, "Zaproponowana akcja").format(**pol.action["params"])
                prop = Proposal(id=pid, text=text, action=pol.action)
                self._pending[pid] = prop
                self._axis_pending[pol.axis] = pid
                out.append(prop)
        return out

    def pending(self) -> list[Proposal]:
        return list(self._pending.values())

    def take(self, pid: str):
        prop = self._pending.pop(pid, None)
        if prop is not None:
            # Clear axis dedup entry so a new proposal can be created after this one is consumed.
            axis_keys = [ax for ax, apid in self._axis_pending.items() if apid == pid]
            for ax in axis_keys:
                del self._axis_pending[ax]
        return prop
