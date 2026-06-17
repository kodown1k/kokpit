import psutil
from kokpit.config import IFACE_DENY
from kokpit.sources.base import RateCounter, Sample


class NetSource:
    name = "net"

    def __init__(self) -> None:
        self._rx: dict[str, RateCounter] = {}
        self._tx: dict[str, RateCounter] = {}

    def sample(self, now_ms: int, dt_s: float) -> Sample:
        out: Sample = {}
        for iface, c in psutil.net_io_counters(pernic=True).items():
            if IFACE_DENY.search(iface):
                continue
            rx = self._rx.setdefault(iface, RateCounter()).update(c.bytes_recv, dt_s)
            tx = self._tx.setdefault(iface, RateCounter()).update(c.bytes_sent, dt_s)
            if rx is not None:
                out[f"net.{iface}.rx_bps"] = rx
            if tx is not None:
                out[f"net.{iface}.tx_bps"] = tx
        return out
