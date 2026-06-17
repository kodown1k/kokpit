import json
from kokpit.sources.thermal import ThermalSource

FIXTURE = json.dumps({
    "coretemp-isa-0000": {
        "Adapter": "ISA adapter",
        "Package id 0": {"temp1_input": 97.0, "temp1_crit": 100.0},
        "Core 0": {"temp2_input": 91.0},
        "Core 4": {"temp3_input": 90.0},
    },
    "nvme-pci-e200": {"Composite": {"temp1_input": 53.9}},
    "iwlwifi_1-virtual-0": {"temp1": {"temp1_input": 55.0}},
})


def test_thermal_parses_sensors_json():
    out = ThermalSource(runner=lambda: FIXTURE).sample(now_ms=0, dt_s=1.0)
    assert out["thermal.pkg"] == 97.0
    assert out["thermal.core.0"] == 91.0
    assert out["thermal.core.4"] == 90.0
    assert out["thermal.nvme.0"] == 53.9
    assert out["thermal.wifi"] == 55.0


def test_thermal_bad_output_returns_empty():
    assert ThermalSource(runner=lambda: "not json").sample(now_ms=0, dt_s=1.0) == {}
