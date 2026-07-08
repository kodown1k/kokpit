from kokpit.ui.app import cpu_mb_rings, nvme_temp_keys


def test_nvme_temp_keys_numeric_sort():
    names = ["thermal.nvme.10", "thermal.nvme.2", "thermal.board", "net.eth0.rx_bps"]
    assert nvme_temp_keys(names) == ["thermal.nvme.2", "thermal.nvme.10"]


def test_nvme_temp_keys_empty():
    assert nvme_temp_keys(["thermal.board"]) == []


def test_cpu_mb_rings_single_socket_with_board():
    names = ["thermal.coretemp.3.pkg", "thermal.coretemp.3.core.0", "thermal.board"]
    assert cpu_mb_rings(names) == [("CPU", "thermal.coretemp.3.pkg"), ("MB", "thermal.board")]


def test_cpu_mb_rings_dual_socket_no_board():
    names = ["thermal.coretemp.5.pkg", "thermal.coretemp.3.pkg"]
    assert cpu_mb_rings(names) == [("CPU0", "thermal.coretemp.3.pkg"),
                                   ("CPU1", "thermal.coretemp.5.pkg")]


def test_cpu_mb_rings_nothing():
    assert cpu_mb_rings(["thermal.nvme.0"]) == []


def test_cpu_mb_rings_single_socket_no_board():
    assert cpu_mb_rings(["thermal.coretemp.3.pkg"]) == [("CPU", "thermal.coretemp.3.pkg")]


def test_cpu_mb_rings_dual_socket_with_board():
    names = ["thermal.coretemp.5.pkg", "thermal.coretemp.3.pkg", "thermal.board"]
    assert cpu_mb_rings(names) == [("CPU0", "thermal.coretemp.3.pkg"),
                                   ("CPU1", "thermal.coretemp.5.pkg"),
                                   ("MB", "thermal.board")]


def test_cpu_mb_rings_numeric_pkg_sort():
    names = ["thermal.coretemp.10.pkg", "thermal.coretemp.2.pkg"]
    assert cpu_mb_rings(names) == [("CPU0", "thermal.coretemp.2.pkg"),
                                   ("CPU1", "thermal.coretemp.10.pkg")]
