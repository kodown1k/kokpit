from dataclasses import dataclass

RAW_WINDOW_MAX_S = 3600  # ≤1h → raw sample; powyżej → rollup_1m


@dataclass
class HistoryResult:
    line: list[tuple[float, float]]                 # (t_sekundy, wartość)
    band: list[tuple[float, float, float]] | None   # (t_sekundy, vmin, vmax) — tylko rollup
    is_rollup: bool


class HistoryModel:
    def __init__(self, store) -> None:
        self._store = store

    @property
    def store(self):
        return self._store

    def window(self, name: str, window_s: int, now_ms: int) -> HistoryResult:
        since_ms = now_ms - window_s * 1000
        if window_s <= RAW_WINDOW_MAX_S:
            rows = self._store.query(name, since_ms, now_ms)
            line = [(ts / 1000.0, v) for ts, v in rows]
            return HistoryResult(line=line, band=None, is_rollup=False)
        rows = self._store.query_rollup(name, since_ms, now_ms)
        line = [(b / 1000.0, vavg) for b, _vmin, _vmax, vavg, _vlast in rows]
        band = [(b / 1000.0, vmin, vmax) for b, vmin, vmax, _vavg, _vlast in rows]
        return HistoryResult(line=line, band=band, is_rollup=True)

    def available_series(self, prefix: str | None = None) -> list[str]:
        return self._store.list_series(prefix)
