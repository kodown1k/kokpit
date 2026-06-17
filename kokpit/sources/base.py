from typing import Protocol

Sample = dict[str, float]


class Source(Protocol):
    name: str

    def sample(self, now_ms: int, dt_s: float) -> Sample: ...


class RateCounter:
    """Zamienia licznik kumulatywny na prędkość/s. Pierwszy odczyt -> None."""

    def __init__(self) -> None:
        self._last: float | None = None

    def update(self, value: float, dt_s: float) -> float | None:
        prev, self._last = self._last, value
        if prev is None or dt_s <= 0:
            return None
        return max(0.0, value - prev) / dt_s
