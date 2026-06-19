import math

from kokpit.ui.widgets import thread_star as ts


def test_arm_angle_first_is_top():
    assert abs(ts.arm_angle(0, 8) - (-math.pi / 2)) < 1e-9
    assert abs(ts.arm_angle(2, 8) - 0.0) < 1e-9            # quarter turn clockwise → +x


def test_arm_reach_maps_frac():
    assert ts.arm_reach(20, 10, 80, 0.0) == 30
    assert ts.arm_reach(20, 10, 80, 1.0) == 110
    assert ts.arm_reach(20, 10, 80, 2.0) == 110            # clamp high
    assert ts.arm_reach(20, 10, 80, -1.0) == 30            # clamp low


def test_ease_step_converges_and_settles():
    cur, tgt = [0.0, 0.0], [1.0, 0.5]
    moving = True
    for _ in range(500):
        cur, moving = ts.ease_step(cur, tgt)
    assert abs(cur[0] - 1.0) < 1e-3 and abs(cur[1] - 0.5) < 1e-3
    assert moving is False


def test_ease_step_at_target_not_moving():
    _cur, moving = ts.ease_step([0.5], [0.5])
    assert moving is False


def test_breath_offset_bounded():
    for ph in range(0, 240, 7):
        for i in range(4):
            dr, da = ts.breath_offset(ph, i, 4)
            assert abs(dr) <= ts.BREATH_AMP_R + 1e-9
            assert abs(da) <= ts.BREATH_AMP_A + 1e-9


def test_set_threads_maps_util_to_fraction(qapp):
    w = ts.ThreadStar()
    w.set_threads({f"cpu.thread.{i}.util": 50.0 for i in range(8)})
    assert len(w._target) == 8
    assert all(abs(t - 0.5) < 1e-9 for t in w._target)


def test_set_threads_missing_key_is_zero(qapp):
    w = ts.ThreadStar()
    w.set_threads({"cpu.thread.0.util": 100.0, "cpu.thread.3.util": 0.0})  # n=4, gaps→0
    assert len(w._target) == 4
    assert w._target[0] == 1.0 and w._target[1] == 0.0 and w._target[3] == 0.0


def test_thread_count_change_snaps_current(qapp):
    w = ts.ThreadStar()
    w.set_threads({f"cpu.thread.{i}.util": 80.0 for i in range(16)})
    w.set_threads({f"cpu.thread.{i}.util": 20.0 for i in range(8)})    # count drops 16→8
    assert len(w._current) == 8                                        # snapped, no stale length


def test_paint_smoke_16_threads(qapp):
    from PySide6 import QtGui
    w = ts.ThreadStar(); w.resize(240, 240)
    w.set_threads({f"cpu.thread.{i}.util": (i * 7) % 100 for i in range(16)})
    img = QtGui.QImage(240, 240, QtGui.QImage.Format_ARGB32)
    w.render(img)                                                      # paintEvent must not crash


def test_paint_smoke_zero_threads(qapp):
    from PySide6 import QtGui
    w = ts.ThreadStar(); w.resize(240, 240)
    w.set_threads({})
    img = QtGui.QImage(240, 240, QtGui.QImage.Format_ARGB32)
    w.render(img)                                                      # n==0 guard, no crash
    assert w._target == []
