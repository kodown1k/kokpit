import logging
import signal
import time

from kokpit import config
from kokpit.actuator.audit import AuditLog
from kokpit.actuator.control_server import ControlServer, build_dispatch
from kokpit.actuator.engine import Actuator
from kokpit.actuator.levers import LEVERS
from kokpit.actuator.policy import DEFAULT_POLICIES, EnvelopeEvaluator
from kokpit.actuator.proposer import Proposer
from kokpit.host import LocalHost
from kokpit.live import LiveServer
from kokpit.proc import ProcCollector
from kokpit.sources.cpu import CpuSource
from kokpit.sources.disk import DiskSource
from kokpit.sources.gpu import GpuSource
from kokpit.sources.memory import MemorySource
from kokpit.sources.net import NetSource
from kokpit.sources.thermal import ThermalSource
from kokpit.store import Store
from kokpit.ui.glyph_model import GlyphModel, BaselineCache

log = logging.getLogger("kokpit.collectord")

_shutdown_requested = False


def _handle_sigterm(signum, frame) -> None:
    global _shutdown_requested
    log.info("SIGTERM received, initiating graceful shutdown")
    _shutdown_requested = True


def build_host() -> tuple[LocalHost, GpuSource]:
    gpu = GpuSource()
    host = LocalHost([
        CpuSource(), MemorySource(), NetSource(),
        DiskSource(), ThermalSource(), gpu,
    ])
    return host, gpu


class _GlyphState:
    """Holds the daemon-side GlyphModel + BaselineCache between ticks."""
    def __init__(self, store=None, now_fn=None):
        self.model = GlyphModel()
        self.baseline = BaselineCache(store, now_fn) if store is not None else None

    def axis_baseline(self, axis_name):
        # Map axis -> representative series baseline. Minimal: reuse cache by axis.
        if self.baseline is None:
            return None
        return self.baseline.get(axis_name)


def tick_envelope(host, store, live, procs, actuator, envelope, glyph, now_ms, dt_s, proposer=None):
    series = host.collect(now_ms, dt_s)
    store.write(now_ms, series)
    proc_rows, gpu_rows = procs.snapshot()
    live.publish({"ts": now_ms, "series": series, "procs": proc_rows, "gpu_procs": gpu_rows})
    actuator.tick(now_ms)
    spokes = glyph.model.update(series, now_ms,
                               glyph.baseline.get if glyph.baseline else (lambda _s: None))
    for action in envelope.evaluate(spokes, glyph.axis_baseline):
        actuator.apply(action["lever"], action["target"], action["params"], action["ttl_s"])
    if proposer is not None:
        proposer.propose(spokes, glyph.axis_baseline)


def tick(host, store, live, procs, actuator, now_ms: int, dt_s: float) -> None:
    series = host.collect(now_ms, dt_s)
    store.write(now_ms, series)
    proc_rows, gpu_rows = procs.snapshot()
    live.publish({"ts": now_ms, "series": series,
                  "procs": proc_rows, "gpu_procs": gpu_rows})
    actuator.tick(now_ms)


def run() -> None:
    global _shutdown_requested
    signal.signal(signal.SIGTERM, _handle_sigterm)
    logging.basicConfig(level=logging.INFO)
    store = Store(config.db_path())
    live = LiveServer(config.socket_path())
    live.start()
    audit = AuditLog(config.audit_path())
    actuator = Actuator(LEVERS, audit, now_fn=lambda: int(time.time() * 1000))
    proposer = Proposer(DEFAULT_POLICIES, now_fn=lambda: int(time.time() * 1000))
    control = ControlServer(config.control_socket_path(), build_dispatch(actuator, proposer))
    control.start()
    host, gpu = build_host()
    procs = ProcCollector(nvml=gpu.nvml)   # ten sam uchwyt NVML co GpuSource
    glyph = _GlyphState(store, now_fn=lambda: int(time.time() * 1000))
    envelope = EnvelopeEvaluator(DEFAULT_POLICIES, config.ENVELOPE_DEBOUNCE_S,
                                 now_fn=lambda: int(time.time() * 1000))
    period = 1.0 / config.SAMPLE_HZ
    last_mono: float | None = None
    last_rollup = 0.0
    log.info("kokpit-collectord wystartował (db=%s sock=%s)", config.db_path(), config.socket_path())
    try:
        while not _shutdown_requested:
            start = time.monotonic()
            now_ms = int(time.time() * 1000)
            dt_s = (start - last_mono) if last_mono is not None else 0.0
            last_mono = start
            try:
                if config.ENVELOPE_ENABLED:
                    tick_envelope(host, store, live, procs, actuator, envelope, glyph, now_ms, dt_s,
                                  proposer=proposer)
                elif config.PROPOSE_ENABLED:
                    tick_envelope(host, store, live, procs, actuator, envelope, glyph, now_ms, dt_s,
                                  proposer=proposer)
                else:
                    tick(host, store, live, procs, actuator, now_ms, dt_s)
            except Exception:
                log.exception("tick nieudany")
            if start - last_rollup >= config.ROLLUP_INTERVAL_S:
                try:
                    with store.conn:
                        store.rollup_1m(now_ms)
                        store.prune(now_ms)
                    store.checkpoint()
                except Exception:
                    log.exception("rollup/prune/checkpoint nieudany")
                last_rollup = start
            time.sleep(max(0.0, period - (time.monotonic() - start)))
    except KeyboardInterrupt:
        log.info("zatrzymywanie")
    finally:
        control.stop()
        actuator.revert_all()
        live.stop()
        store.close()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
