import math
from kokpit import config
from kokpit.ui import glyph_model as gm


def test_z_norm_positive_deviation():
    # mean=50, sigma=10 → value_sm=80 to +3σ = pełne ramię (Z_FULL=3)
    assert gm.z_norm(80.0, (50.0, 10.0, 12, "circadian")) == 1.0
    assert abs(gm.z_norm(65.0, (50.0, 10.0, 12, "circadian")) - 0.5) < 1e-9  # +1.5σ → 0.5


def test_z_norm_negative_deviation_clamped_to_zero():
    assert gm.z_norm(20.0, (50.0, 10.0, 12, "circadian")) == 0.0   # poniżej baseline = spokój


def test_z_norm_sigma_zero_is_calm():
    assert gm.z_norm(95.0, (95.0, 0.0, 12, "circadian")) == 0.0    # seria stała → brak zaskoczenia


def test_z_norm_none_baseline_is_zero():
    assert gm.z_norm(999.0, None) == 0.0


def test_spike_score_takes_max_of_z_and_proximity():
    # σ≈0 (z=0) ale proximity 0.95 → kolec z proximity (maszyna zawsze gorąca)
    assert gm.spike_score(95.0, (95.0, 0.0, 12, "circadian"), 0.95) == 0.95
    # z duże, proximity małe → z wygrywa
    assert gm.spike_score(80.0, (50.0, 10.0, 12, "circadian"), 0.1) == 1.0
    # proximity None (oś bez limitu) → sam z
    assert gm.spike_score(65.0, (50.0, 10.0, 12, "circadian"), None) == 0.5


def test_proximity_clamped():
    assert gm.spike_score(0.0, None, 1.5) == 1.0   # proximity > 1 → 1


def test_ewma_smooths_between_prev_and_new():
    a = gm.ewma_alpha()
    assert 0.0 < a < 1.0
    assert gm.ewma(None, 10.0, a) == 10.0          # brak stanu → wartość wprost
    sm = gm.ewma(10.0, 20.0, a)
    assert 10.0 < sm < 20.0                          # między starym a nowym
    assert abs(sm - (10.0 + a * 10.0)) < 1e-9


def test_disk_io_members_excludes_used_pct_and_partitions():
    keys = [
        "disk.nvme0n1.read_bps", "disk.nvme0n1.write_bps",   # cały dysk → IN
        "disk.nvme0n1p1.read_bps", "disk.nvme0n1p2.write_bps",  # partycje → OUT
        "disk.sda.read_bps", "disk.sda1.read_bps",           # sda IN, sda1 OUT
        "disk.root.used_pct", "disk.home.used_pct",          # used_pct → OUT
    ]
    assert sorted(gm.disk_io_members(keys)) == [
        "disk.nvme0n1.read_bps", "disk.nvme0n1.write_bps", "disk.sda.read_bps",
    ]


def test_ratio_handles_missing_and_zero():
    assert gm.ratio({"mem.used": 50.0, "mem.total": 200.0}, "mem.used", "mem.total") == 0.25
    assert gm.ratio({"mem.used": 50.0}, "mem.used", "mem.total") is None   # brak total
    assert gm.ratio({"mem.used": 50.0, "mem.total": 0.0}, "mem.used", "mem.total") is None


def test_gpu_vram_ratio_takes_worst_gpu():
    s = {"gpu.0.vram_used": 4.0, "gpu.0.vram_total": 8.0,
         "gpu.1.vram_used": 7.0, "gpu.1.vram_total": 8.0}
    assert gm.gpu_vram_ratio(s) == 0.875        # gpu.1 = 7/8
    assert gm.gpu_vram_ratio({"gpu.0.vram_used": 1.0}) is None   # brak total


def test_max_temp_ratio():
    s = {"thermal.coretemp.0.pkg": 76.0, "thermal.coretemp.1.pkg": 95.0,
         "cpu.thread.0.util": 10.0}
    pred = lambda k: k.startswith("thermal.coretemp.") and k.endswith(".pkg")
    assert gm.max_temp_ratio(s, pred, 95.0) == 1.0     # 95/95
    assert gm.max_temp_ratio({"x": 1.0}, pred, 95.0) is None
