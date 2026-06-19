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
