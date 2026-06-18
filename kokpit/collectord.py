import logging
import signal
import subprocess
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

# Axis name -> predicate matching real series keys stored in the Store.
# Mirrors the glyph_model spoke predicates so axis_baseline resolves correctly.
_AXIS_MATCH = {
    "GPU temp": lambda k: k.startswith("gpu.") and k.endswith(".temp"),
    "CPU temp": lambda k: k.startswith("thermal.coretemp.") and k.endswith(".pkg"),
}


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
        self._store = store
        self.baseline = BaselineCache(store, now_fn) if store is not None else None

    def axis_baseline(self, axis_name):
        """Resolve axis name to the best matching series baseline.

        Looks up _AXIS_MATCH predicate for the axis, iterates store series,
        and returns the baseline tuple with the highest mean (hottest series).
        Falls back to direct self.baseline.get(axis_name) for unknown axes.
        """
        if self.baseline is None:
            return None
        pred = _AXIS_MATCH.get(axis_name)
        if pred is None:
            # Unknown axis: fall back to direct cache lookup
            return self.baseline.get(axis_name)
        # Iterate all series, collect baselines for matching ones, return hottest
        best = None
        for series in self._store.list_series():
            if pred(series):
                b = self.baseline.get(series)
                if b is not None:
                    if best is None or b[0] > best[0]:
                        best = b
        return best


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


def _run_reset(argv: list[str]) -> None:
    """Run a privileged reset command; log on failure, never raise."""
    subprocess.run(argv, capture_output=True, check=False)


def safety_revert_on_startup(audit, now_fn, _runner=None) -> None:
    """Best-effort revert of privileged hardware levers on unclean startup.

    Reads the audit tail: if the last entry is a clean shutdown marker,
    no action is taken (previous run exited cleanly).  Otherwise resets GPU
    power caps and CPU governor to safe defaults, tolerating any failure.

    _runner: optional callable(argv) used for testing (no real pkexec).
    """
    runner = _runner if _runner is not None else _run_reset
    tail = audit.tail(50)
    # Empty log = first start, nothing was ever applied → no revert needed.
    # Last entry is a clean shutdown → previous run exited cleanly → no revert needed.
    if not tail:
        return
    last = tail[-1]
    if last.get("event") == "shutdown" and last.get("detail", {}).get("clean"):
        return
    # Unclean previous run — reset privileged levers best-effort
    log.warning("safety_revert_on_startup: previous run was not clean, reverting hardware levers")
    # Reset GPU power caps
    gpu_count = 0
    try:
        import pynvml  # optional
        pynvml.nvmlInit()
        gpu_count = pynvml.nvmlDeviceGetCount()
    except Exception:
        pass
    for idx in range(gpu_count):
        try:
            runner(["pkexec", "kokpit-actl-helper", "gpu-power-reset", str(idx)])
        except Exception:
            log.exception("safety_revert: gpu-power-reset %d failed", idx)
    # Reset CPU governor
    try:
        runner(["pkexec", "kokpit-actl-helper", "governor", config.STARTUP_GOVERNOR])
    except Exception:
        log.exception("safety_revert: governor reset failed")
    audit.record("safety_revert", {"gpu_count": gpu_count, "governor": config.STARTUP_GOVERNOR})


def run() -> None:
    global _shutdown_requested
    signal.signal(signal.SIGTERM, _handle_sigterm)
    logging.basicConfig(level=logging.INFO)
    store = Store(config.db_path())
    live = LiveServer(config.socket_path())
    live.start()
    audit = AuditLog(config.audit_path())
    # Safety-revert privileged levers if previous run crashed / was killed
    safety_revert_on_startup(audit, now_fn=lambda: int(time.time() * 1000))
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
                if config.ENVELOPE_ENABLED or config.PROPOSE_ENABLED:
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
        audit.record("shutdown", {"clean": True})
        live.stop()
        store.close()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
