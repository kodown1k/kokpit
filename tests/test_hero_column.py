from kokpit.ui.widgets.hero_column import avg_util, pct


def test_avg_util():
    assert avg_util({"cpu.thread.0.util": 10, "cpu.thread.1.util": 30}) == 20
    assert avg_util({}) is None
    # None pominięte, nie-thread klucze ignorowane
    assert avg_util({"cpu.thread.0.util": None, "cpu.thread.1.util": 40, "mem.used": 5}) == 40


def test_pct():
    assert pct(50, 100) == 50
    assert pct(None, 100) is None
    assert pct(5, 0) is None          # total 0 → None (brak dzielenia przez 0)
    assert pct(5, None) is None


def test_hero_column_updates(qapp):
    from kokpit.ui.widgets.hero_column import HeroColumn
    h = HeroColumn(gpu_index=0)
    h.update_snapshot({"series": {
        **{f"cpu.thread.{i}.util": 50 for i in range(4)},
        "gpu.0.util": 40, "mem.used": 4e9, "mem.total": 8e9,
        "gpu.0.vram_used": 2e9, "gpu.0.vram_total": 8e9,
        "thermal.coretemp.0.pkg": 61.0, "gpu.0.temp": 64.0,
    }})
    assert h._cpu._target == 50         # średnia thread util
    assert h._gpu._target == 40
    assert h._ram._target == 50         # 4e9/8e9*100
    assert h._vram._target == 25        # 2e9/8e9*100
    # snapshot bez danych — bez crasha, ringi w stanie „brak"
    h.update_snapshot({"series": {}})
    assert h._cpu._value is None
