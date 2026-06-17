"""Wyprowadzanie kluczy metryk CPU (thread-util / coretemp) — współdzielone przez
CoreRingGrid i HeroColumn. Widget siatki: kokpit/ui/widgets/core_ring_grid.py."""


def thread_util_keys(n: int = 32) -> list[str]:
    return [f"cpu.thread.{i}.util" for i in range(n)]


def sorted_thermal_keys(names) -> list[str]:
    # klucze coretemp: thermal.coretemp.<cid>.core.<n> (cid = chip hwmon —
    # wielo-socket safe; n = nieciągły numer rdzenia). Sortuj po (cid, n).
    def _valid(name: str) -> bool:
        if not (name.startswith("thermal.coretemp.") and ".core." in name):
            return False
        parts = name.split(".")  # ["thermal","coretemp",<cid>,"core",<n>]
        return len(parts) == 5 and parts[2].isdigit() and parts[4].isdigit()

    def _key(name: str) -> tuple[int, int]:
        parts = name.split(".")
        return (int(parts[2]), int(parts[4]))

    return sorted((n for n in names if _valid(n)), key=_key)


def pkg_temp(series: dict) -> float | None:
    vals = [v for k, v in series.items()
            if k.startswith("thermal.coretemp.") and k.endswith(".pkg") and v is not None]
    return max(vals) if vals else None
