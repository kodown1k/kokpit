import logging
import signal
import time

from kokpit import config
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

log = logging.getLogger("kokpit.collectord")

_shutdown_requested = False


def _handle_sigterm(signum, frame) -> None:
    global _shutdown_requested
    log.info("SIGTERM received, initiating graceful shutdown")
    _shutdown_requested = True


def build_host() -> LocalHost:
    return LocalHost([
        CpuSource(), MemorySource(), NetSource(),
        DiskSource(), ThermalSource(), GpuSource(),
    ])


def tick(host, store, live, procs, now_ms: int, dt_s: float) -> None:
    series = host.collect(now_ms, dt_s)
    store.write(now_ms, series)
    live.publish({"ts": now_ms, "series": series, "procs": procs.top()})


def run() -> None:
    global _shutdown_requested
    signal.signal(signal.SIGTERM, _handle_sigterm)
    logging.basicConfig(level=logging.INFO)
    store = Store(config.db_path())
    live = LiveServer(config.socket_path())
    live.start()
    host = build_host()
    procs = ProcCollector()
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
                tick(host, store, live, procs, now_ms, dt_s)
            except Exception:
                log.exception("tick nieudany")
            if start - last_rollup >= 60.0:
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
        live.stop()
        store.close()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
