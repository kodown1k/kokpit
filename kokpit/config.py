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

# --- Vital-Signs Glyph (spec 2026-06-18) ---
BASELINE_MIN_SAMPLES = 10      # min bucketów w tierze, by uznać baseline za użyteczny
FALLBACK_GLOBAL_DAYS = 7       # okno tieru 'global'
BASELINE_REFRESH_S = 60.0      # UI recompute baseline nie częściej niż co tyle
Z_FULL = 3.0                   # z-score dający ramię pełnej długości
EPS_SIGMA = 1e-9               # σ poniżej → seria stała, z=0 (guard dzielenia)
LIVE_EWMA_S = 45.0             # okno wygładzania live (licznik z-score, §3)
FAST_EWMA_S = 4.0              # krótkie okno dla bursty liczników IO (net/disk) — ramię nie zostaje rozgrzane po spike'u


def control_socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path("/tmp")
    return base / "kokpit-ctl.sock"


def audit_path() -> Path:
    return data_dir() / "actuator-audit.jsonl"


# --- Actuator / Envelope (spec 2026-06-18) ---
ENVELOPE_ENABLED = False         # opt-in; auto-actions only when True
PROPOSE_ENABLED = False          # opt-in; accumulate proposals for UI to poll
ENVELOPE_Z_TRIGGER = 2.5         # z-score (in σ) above baseline to fire envelope
ENVELOPE_DEBOUNCE_S = 15.0       # sustained breach before acting (anti-flap)
ENVELOPE_DEFAULT_TTL_S = 1800.0  # auto-revert window for envelope actions
GPU_POWER_FLOOR_W = 100          # never cap GPU below this
RENICE_BACKGROUND = 15           # default nice for "make it quiet" demotions
STARTUP_GOVERNOR = "schedutil"   # safe governor for startup safety-revert
