from pathlib import Path

from kokpit.sources.thermal import ThermalSource


def _mkchip(root: Path, idx: int, name: str, temps: dict[str, tuple[str, int]]) -> None:
    """Tworzy fałszywy chip hwmon. temps: {tempN: (label, milli_celsius)}.

    Pusty label => brak pliku _label (jak iwlwifi).
    """
    chip = root / f"hwmon{idx}"
    chip.mkdir(parents=True)
    (chip / "name").write_text(name + "\n")
    for tname, (label, milli) in temps.items():
        (chip / f"{tname}_input").write_text(f"{milli}\n")
        if label:
            (chip / f"{tname}_label").write_text(label + "\n")


def test_thermal_parses_sysfs(tmp_path):
    # numery plików temp* celowo NIE pokrywają się z numerami rdzeni
    _mkchip(tmp_path, 3, "coretemp", {
        "temp1": ("Package id 0", 97000),
        "temp2": ("Core 0", 91000),
        "temp6": ("Core 4", 90000),
    })
    _mkchip(tmp_path, 0, "nvme", {
        "temp1": ("Composite", 53900),
        "temp3": ("Sensor 2", 65000),   # ignorowane — bierzemy tylko Composite
    })
    _mkchip(tmp_path, 4, "iwlwifi_1", {
        "temp1": ("", 55000),           # brak label
    })
    out = ThermalSource(root=tmp_path).sample(now_ms=0, dt_s=1.0)
    assert out == {
        "thermal.coretemp.3.pkg": 97.0,
        "thermal.coretemp.3.core.0": 91.0,
        "thermal.coretemp.3.core.4": 90.0,
        "thermal.nvme.0": 53.9,
        "thermal.wifi": 55.0,
    }


def test_thermal_dual_socket_no_collision(tmp_path):
    # dwa chipy coretemp z IDENTYCZNYMI etykietami (Package id 0 / Core 0)
    _mkchip(tmp_path, 3, "coretemp", {
        "temp1": ("Package id 0", 60000),
        "temp2": ("Core 0", 61000),
    })
    _mkchip(tmp_path, 5, "coretemp", {
        "temp1": ("Package id 0", 70000),
        "temp2": ("Core 0", 71000),
    })
    out = ThermalSource(root=tmp_path).sample(now_ms=0, dt_s=1.0)
    # bez kolizji — numer hwmon rozróżnia gniazda
    assert out == {
        "thermal.coretemp.3.pkg": 60.0,
        "thermal.coretemp.3.core.0": 61.0,
        "thermal.coretemp.5.pkg": 70.0,
        "thermal.coretemp.5.core.0": 71.0,
    }


def test_thermal_multi_nvme_indexed_by_hwmon_order(tmp_path):
    # hwmon10 musi sortować się PO hwmon2 (numerycznie, nie leksykalnie)
    _mkchip(tmp_path, 2, "nvme", {"temp1": ("Composite", 50000)})
    _mkchip(tmp_path, 10, "nvme", {"temp1": ("Composite", 60000)})
    out = ThermalSource(root=tmp_path).sample(now_ms=0, dt_s=1.0)
    assert out == {"thermal.nvme.0": 50.0, "thermal.nvme.1": 60.0}


def test_thermal_missing_root_returns_empty(tmp_path):
    assert ThermalSource(root=tmp_path / "nope").sample(now_ms=0, dt_s=1.0) == {}


def test_thermal_unreadable_temp_skipped(tmp_path):
    _mkchip(tmp_path, 0, "coretemp", {"temp1": ("Package id 0", 0)})
    (tmp_path / "hwmon0" / "temp1_input").write_text("not_a_number\n")
    assert ThermalSource(root=tmp_path).sample(now_ms=0, dt_s=1.0) == {}
