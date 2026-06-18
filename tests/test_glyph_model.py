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
    assert gm.max_temp_ratio({"thermal.coretemp.0.pkg": 95.0}, pred, 0.0) is None  # limit=0 → None


def _const_provider(table):
    return lambda series: table.get(series)


def test_update_returns_nine_spokes_in_order():
    m = gm.GlyphModel()
    spokes = m.update({}, 1_700_000_000_000, _const_provider({}))
    assert [s.name for s in spokes] == gm.SPOKE_NAMES
    assert len(spokes) == 9


def test_update_cpu_uses_zscore_from_loadavg():
    m = gm.GlyphModel()
    prov = _const_provider({"cpu.loadavg.1": (2.0, 1.0, 12, "circadian")})
    # EWMA: pierwsza próbka = wartość wprost, więc value_sm=5.0 → z=(5-2)/1/3=1.0
    spokes = {s.name: s for s in m.update({"cpu.loadavg.1": 5.0}, 1_700_000_000_000, prov)}
    assert spokes["CPU"].score == 1.0
    assert spokes["CPU"].tier == "circadian"


def test_update_ram_proximity_without_baseline():
    m = gm.GlyphModel()
    series = {"mem.used": 95.0, "mem.total": 100.0}      # 95% pełne
    spokes = {s.name: s for s in m.update(series, 1_700_000_000_000, _const_provider({}))}
    assert spokes["RAM"].score == 0.95                    # proximity ratuje brak baseline
    assert spokes["RAM"].tier is None


def test_update_disk_worst_of_family():
    m = gm.GlyphModel()
    prov = _const_provider({
        "disk.nvme0n1.read_bps": (100.0, 10.0, 12, "circadian"),   # spokojny
        "disk.sda.read_bps":     (10.0, 5.0, 12, "circadian"),     # value 40 → z=(40-10)/5/3=2 → 1.0
    })
    series = {"disk.nvme0n1.read_bps": 100.0, "disk.sda.read_bps": 40.0,
              "disk.root.used_pct": 80.0}                  # used_pct NIE w rodzinie IO
    spokes = {s.name: s for s in m.update(series, 1_700_000_000_000, prov)}
    assert spokes["Disk IO"].score == 1.0                  # worst-of = sda


def test_update_tie_break_first_member_wins():
    """Przy równych z-score (remis) pierwsze ramię rodziny wygrywa — tier/value spójne."""
    m = gm.GlyphModel()
    # Oba dyski mają dokładnie takie same mean/sigma/value → identyczny z-score
    prov = _const_provider({
        "disk.nvme0n1.read_bps": (50.0, 10.0, 12, "circadian"),
        "disk.sda.read_bps":     (50.0, 10.0, 12, "hour"),
    })
    series = {"disk.nvme0n1.read_bps": 80.0, "disk.sda.read_bps": 80.0}
    spokes = {s.name: s for s in m.update(series, 1_700_000_000_000, prov)}
    disk = spokes["Disk IO"]
    # Przy remisie (z == best_z) pierwsza seria w z_members wygrywa
    # disk_io_members iteruje w kolejności keys() → nvme0n1 przed sda
    assert disk.tier == "circadian"   # tier pierwszego członka, nie drugiego


def test_update_cold_start_calibrating_flag():
    m = gm.GlyphModel()
    m.update({"cpu.loadavg.1": 1.0}, 1_700_000_000_000, _const_provider({}))  # provider zawsze None
    assert m.calibrating is True


def test_update_not_calibrating_when_any_baseline():
    m = gm.GlyphModel()
    prov = _const_provider({"cpu.loadavg.1": (2.0, 1.0, 12, "global")})
    m.update({"cpu.loadavg.1": 5.0}, 1_700_000_000_000, prov)
    assert m.calibrating is False


def test_baseline_cache_throttles_recompute():
    from kokpit.ui.glyph_model import BaselineCache

    class FakeStore:
        def __init__(self):
            self.calls = 0
        def baseline(self, series, now_ms):
            self.calls += 1
            return (1.0, 1.0, 12, "global")

    clock = {"t": 1_700_000_000_000}
    store = FakeStore()
    cache = BaselineCache(store, now_fn=lambda: clock["t"])
    assert cache.get("cpu.loadavg.1") == (1.0, 1.0, 12, "global")
    cache.get("cpu.loadavg.1")                 # ten sam czas → z cache
    assert store.calls == 1
    clock["t"] += int(config.BASELINE_REFRESH_S * 1000) + 1   # po oknie
    cache.get("cpu.loadavg.1")
    assert store.calls == 2


def test_display_ram_proximity():
    """RAM spoke with 71% proximity → display contains 'RAM 71%'."""
    m = gm.GlyphModel()
    series = {"mem.used": 71.0, "mem.total": 100.0}
    spokes = {s.name: s for s in m.update(series, 1_700_000_000_000, _const_provider({}))}
    assert "RAM" in spokes["RAM"].display
    assert "71%" in spokes["RAM"].display


def test_display_cpu_temp():
    """CPU temp spoke with best_val 87 → display is 'CPU° 87°'."""
    m = gm.GlyphModel()
    series = {"thermal.coretemp.0.pkg": 87.0}
    spokes = {s.name: s for s in m.update(series, 1_700_000_000_000, _const_provider({}))}
    assert spokes["CPU temp"].display == "CPU° 87°"


def test_display_cpu_loadavg():
    """CPU loadavg 2.3 → display contains 'CPU 2.3'."""
    m = gm.GlyphModel()
    series = {"cpu.loadavg.1": 2.3}
    spokes = {s.name: s for s in m.update(series, 1_700_000_000_000, _const_provider({}))}
    assert spokes["CPU"].display == "CPU 2.3"


def test_display_cold_start_just_code():
    """Cold-start (empty series) → every spoke display is just the axis code, no value."""
    m = gm.GlyphModel()
    spokes = {s.name: s for s in m.update({}, 1_700_000_000_000, _const_provider({}))}
    assert spokes["CPU"].display == "CPU"
    assert spokes["RAM"].display == "RAM"
    assert spokes["GPU"].display == "GPU"


def test_display_disk_io_mbs():
    """Disk IO 8 MB/s → display is 'DISK 8'."""
    m = gm.GlyphModel()
    series = {"disk.nvme0n1.read_bps": 8_000_000.0}
    spokes = {s.name: s for s in m.update(series, 1_700_000_000_000, _const_provider({}))}
    assert spokes["Disk IO"].display == "DISK 8"


def test_display_gpu_util():
    """GPU util 73 → display contains 'GPU 73%'."""
    m = gm.GlyphModel()
    series = {"gpu.0.util": 73.0}
    spokes = {s.name: s for s in m.update(series, 1_700_000_000_000, _const_provider({}))}
    assert spokes["GPU"].display == "GPU 73%"


def test_baseline_cache_does_not_cache_errors():
    """DB error must NOT be cached — next tick must retry (call count keeps growing)."""
    from kokpit.ui.glyph_model import BaselineCache

    class FakeStore:
        def __init__(self, fail=False):
            self.calls = 0
            self.fail = fail
        def baseline(self, series, now_ms):
            self.calls += 1
            if self.fail:
                raise RuntimeError("DB gone")
            return (5.0, 2.0, 12, "global")

    clock = {"t": 1_700_000_000_000}
    tick = int(config.BASELINE_REFRESH_S * 1000) + 1

    # Case 1: error on very first call → must return None (no prior value)
    store_err = FakeStore(fail=True)
    cache = BaselineCache(store_err, now_fn=lambda: clock["t"])
    assert cache.get("cpu.loadavg.1") is None
    assert store_err.calls == 1
    # Without advancing clock: error NOT cached → store is queried again on next call
    result2 = cache.get("cpu.loadavg.1")
    assert result2 is None
    assert store_err.calls == 2   # would be 1 if error were cached within TTL

    # Case 2: successful read, then error — must return last-known AND keep retrying
    clock["t"] = 1_700_000_000_000
    store_ok = FakeStore(fail=False)
    cache2 = BaselineCache(store_ok, now_fn=lambda: clock["t"])
    last_good = cache2.get("cpu.loadavg.1")
    assert last_good == (5.0, 2.0, 12, "global")
    assert store_ok.calls == 1

    # Switch store to failing mode, advance clock past TTL
    store_ok.fail = True
    clock["t"] += tick
    result = cache2.get("cpu.loadavg.1")
    assert result == (5.0, 2.0, 12, "global")   # returns last-known
    assert store_ok.calls == 2                   # store WAS queried (error not cached)

    # WITHOUT advancing clock: store must be queried again (error not cached within TTL)
    result3 = cache2.get("cpu.loadavg.1")
    assert result3 == (5.0, 2.0, 12, "global")   # still last-known
    assert store_ok.calls == 3                    # retried immediately, not cached
