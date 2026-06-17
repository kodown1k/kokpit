import os
import re
from pathlib import Path

SAMPLE_HZ = 1.0
RAW_RETENTION_S = 48 * 3600           # 48h surowych próbek
ROLLUP_RETENTION_S = 30 * 24 * 3600   # 30 dni rollupu 1-minutowego

# Rollup 1-minutowy. BUCKET_MS to szerokość bucketu (definiuje arytmetykę SQL
# (ts/BUCKET_MS)*BUCKET_MS); demon odpala rollup co INTERVAL_S; LOOKBACK_MS to
# okno wstecz przeliczane co przebieg (łapie próbki spóźnione / po restarcie).
# Trzymane razem, bo są sprzężone — zmiana szerokości bucketu musi być spójna.
ROLLUP_BUCKET_MS = 60_000
ROLLUP_INTERVAL_S = 60.0
ROLLUP_LOOKBACK_MS = 60 * ROLLUP_BUCKET_MS   # 1h = 60 bucketów wstecz


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "kokpit"


def db_path() -> Path:
    return data_dir() / "kokpit.db"


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path("/tmp")
    return base / "kokpit.sock"


# Interfejsy/urządzenia wirtualne pomijane w metrykach sieci/dysków
# Uses both re.match() for prefix filtering (^lo, ^docker) and re.search() for
# substring matching (warp in CloudflareWARP). See test_iface_disk_filters for examples.
IFACE_DENY = re.compile(r"^(lo|veth|br-|docker|tailscale|virbr|vmnet)|warp", re.IGNORECASE)
DISK_DENY = re.compile(r"^(loop|ram|dm-|sr|fd)\d*$", re.IGNORECASE)
