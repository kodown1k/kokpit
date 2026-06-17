from kokpit.ui.widgets.heatmap import thread_util_keys, sorted_thermal_keys, pkg_temp


def test_thread_util_keys():
    keys = thread_util_keys(32)
    assert keys[0] == "cpu.thread.0.util"
    assert keys[31] == "cpu.thread.31.util"
    assert len(keys) == 32


def test_sorted_thermal_keys_noncontiguous():
    names = ["thermal.coretemp.3.pkg", "thermal.coretemp.3.core.12",
             "thermal.coretemp.3.core.0", "thermal.coretemp.3.core.4",
             "thermal.nvme.0"]
    assert sorted_thermal_keys(names) == [
        "thermal.coretemp.3.core.0", "thermal.coretemp.3.core.4",
        "thermal.coretemp.3.core.12",
    ]


def test_sorted_thermal_keys_dual_socket():
    # dwa chipy coretemp (cid 3 i 5) — sort po (cid, n), bez kolizji
    names = ["thermal.coretemp.5.core.0", "thermal.coretemp.3.core.0",
             "thermal.coretemp.3.core.4"]
    assert sorted_thermal_keys(names) == [
        "thermal.coretemp.3.core.0", "thermal.coretemp.3.core.4",
        "thermal.coretemp.5.core.0",
    ]


def test_sorted_thermal_keys_skips_malformed():
    # non-numeric cid or core index must be skipped without crashing
    names = ["thermal.coretemp.x.core.0", "thermal.coretemp.3.core.max",
             "thermal.coretemp.3.core.4"]
    assert sorted_thermal_keys(names) == ["thermal.coretemp.3.core.4"]


def test_pkg_temp_picks_hottest_socket():
    assert pkg_temp({"thermal.coretemp.3.pkg": 55.0,
                     "thermal.coretemp.5.pkg": 71.0,
                     "thermal.coretemp.3.core.0": 90.0}) == 71.0
    assert pkg_temp({"cpu.thread.0.util": 10.0}) is None   # brak pkg → None
