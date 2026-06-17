import re
from pathlib import Path

from kokpit.sources.base import Sample

HWMON_ROOT = Path("/sys/class/hwmon")


def _read_text(p: Path) -> str | None:
    try:
        return p.read_text().strip()
    except OSError:
        return None


def _read_temp(p: Path) -> float | None:
    """sysfs trzyma temperaturę w mili-°C; zwróć °C lub None."""
    try:
        return int(p.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def _label_path(temp_input: Path) -> Path:
    return temp_input.with_name(temp_input.name.replace("_input", "_label"))


def _hwmon_num(p: Path) -> int:
    m = re.search(r"(\d+)$", p.name)
    return int(m.group(1)) if m else 0


class ThermalSource:
    """Temperatury czytane wprost z sysfs (hwmon) — bez fork/exec `sensors` co tick.

    Klucze: `thermal.pkg`, `thermal.core.<n>`, `thermal.nvme.<idx>`, `thermal.wifi`.
    `root` wstrzykiwalny dla testów (domyślnie /sys/class/hwmon).
    """

    name = "thermal"

    def __init__(self, root: Path | str = HWMON_ROOT) -> None:
        self._root = Path(root)

    def sample(self, now_ms: int, dt_s: float) -> Sample:
        out: Sample = {}
        try:
            chips = sorted(self._root.glob("hwmon*"), key=_hwmon_num)
        except OSError:
            return out
        nvme_idx = 0
        for chip in chips:
            name = _read_text(chip / "name")
            if name is None:
                continue
            if name.startswith("coretemp"):
                self._read_coretemp(chip, out)
            elif name.startswith("nvme"):
                if self._read_nvme(chip, nvme_idx, out):
                    nvme_idx += 1
            elif "iwlwifi" in name or "wifi" in name:
                self._read_wifi(chip, out)
        return out

    @staticmethod
    def _read_coretemp(chip: Path, out: Sample) -> None:
        for inp in sorted(chip.glob("temp*_input")):
            label = _read_text(_label_path(inp)) or ""
            if label.startswith("Package id"):
                t = _read_temp(inp)
                if t is not None:
                    out["thermal.pkg"] = t
            elif label.startswith("Core "):
                t = _read_temp(inp)
                if t is not None:
                    out[f"thermal.core.{label.split()[1]}"] = t

    @staticmethod
    def _read_nvme(chip: Path, idx: int, out: Sample) -> bool:
        """Tylko czujnik 'Composite'. Zwraca True jeśli zapisał wartość."""
        for inp in sorted(chip.glob("temp*_input")):
            if (_read_text(_label_path(inp)) or "") == "Composite":
                t = _read_temp(inp)
                if t is not None:
                    out[f"thermal.nvme.{idx}"] = t
                    return True
                return False
        return False

    @staticmethod
    def _read_wifi(chip: Path, out: Sample) -> None:
        for inp in sorted(chip.glob("temp*_input")):
            t = _read_temp(inp)
            if t is not None:
                out["thermal.wifi"] = t
                return
