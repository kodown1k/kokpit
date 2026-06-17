from kokpit.ui.widgets.heatmap import thread_util_keys, sorted_thermal_keys


def test_thread_util_keys():
    keys = thread_util_keys(32)
    assert keys[0] == "cpu.thread.0.util"
    assert keys[31] == "cpu.thread.31.util"
    assert len(keys) == 32


def test_sorted_thermal_keys_noncontiguous():
    names = ["thermal.pkg", "thermal.core.12", "thermal.core.0",
             "thermal.core.4", "thermal.nvme.0"]
    assert sorted_thermal_keys(names) == [
        "thermal.core.0", "thermal.core.4", "thermal.core.12",
    ]
