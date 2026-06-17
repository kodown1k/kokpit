from kokpit.ui.widgets.gpu_panel import expected_gpu_indices, gpu_value
from kokpit.ui.widgets.proc_table import bytes_to_mb


def test_expected_gpu_indices():
    names = ["gpu.0.util", "gpu.0.temp", "gpu.1.util", "cpu.loadavg.1"]
    assert expected_gpu_indices(names) == [0, 1]


def test_gpu_value_missing_is_none():
    snap = {"series": {"gpu.0.util": 63.0}}
    assert gpu_value(snap, 0, "util") == 63.0
    assert gpu_value(snap, 0, "temp") is None     # absent → n/a
    assert gpu_value(snap, 1, "util") is None


def test_bytes_to_mb():
    assert bytes_to_mb(1024 * 1024) == 1.0
    assert bytes_to_mb(0) == 0.0


def test_widgets_smoke(qapp):
    from kokpit.ui.widgets.gpu_panel import GpuPanel
    from kokpit.ui.widgets.proc_table import ProcTable
    gp = GpuPanel([0])
    gp.update_snapshot({"series": {"gpu.0.util": 50.0, "gpu.0.temp": 60.0,
                                   "gpu.0.vram_used": 2e9, "gpu.0.vram_total": 16e9}})
    gp.update_snapshot({"series": {}})   # wszystko n/a — bez crasha
    pt = ProcTable()
    pt.set_rows([{"pid": 1, "name": "x", "cpu": 9.0, "rss": 2097152, "vram": 0.0}])
    assert pt._model.rowCount() == 1
