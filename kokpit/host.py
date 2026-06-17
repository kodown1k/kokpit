import logging

log = logging.getLogger("kokpit.host")


class LocalHost:
    def __init__(self, sources: list) -> None:
        self.sources = sources

    def collect(self, now_ms: int, dt_s: float) -> dict:
        merged: dict = {}
        for s in self.sources:
            try:
                merged.update(s.sample(now_ms, dt_s))
            except Exception:
                log.exception("źródło %s nieudane", getattr(s, "name", s))
        return merged
