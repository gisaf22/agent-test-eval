# tests/test_blackmamba_open_source_r_vision.py
import math
import pytest

from blackmamba_open_source_r_vision import (
    RawDetection, Frame, SimulatedCamera, _wrap,
)


def cam(objs, **kw):
    kw.setdefault("miss_rate", 0.0)
    return SimulatedCamera(objs, **kw)


def test_wrap_range_and_values():
    assert _wrap(0.0) == pytest.approx(0.0)
    assert _wrap(2 * math.pi) == pytest.approx(0.0)
    assert _wrap(3 * math.pi / 2) == pytest.approx(-math.pi / 2)
    assert _wrap(-3 * math.pi / 2) == pytest.approx(math.pi / 2)
    for a in [-10, -3.2, 0.5, 3.2, 10, 100]:
        w = _wrap(a)
        assert -math.pi <= w < math.pi


def test_raw_detection_frozen():
    d = RawDetection("a", 1.0, 0.0, 0.9)
    with pytest.raises(Exception):
        d.label = "b"


def test_frame_default_detections_independent():
    f1 = Frame(0.0, (0, 0, 0))
    f2 = Frame(0.0, (0, 0, 0))
    f1.detections.append(RawDetection("a", 1, 0, 1))
    assert f2.detections == []


def test_capture_basic_fields():
    c = cam([("cup", 2.0, 0.0)])
    f = c.capture((0.0, 0.0, 0.0), timestamp_s=1.5)
    assert f.timestamp_s == 1.5
    assert f.pose == (0.0, 0.0, 0.0)
    assert len(f.detections) == 1
    d = f.detections[0]
    assert d.label == "cup"
    assert d.range_m == pytest.approx(2.0, abs=0.15)
    assert d.bearing_rad == pytest.approx(0.0, abs=0.06)
    assert 0.0 <= d.confidence <= 1.0


def test_default_timestamp():
    assert cam([]).capture((0, 0, 0)).timestamp_s == 0.0


def test_out_of_range_excluded():
    c = cam([("far", 6.0, 0.0)], max_range_m=5.0)
    assert c.capture((0, 0, 0)).detections == []
    assert c.capture((0, 0, 0), sweep=True).detections == []


def test_range_uses_pose_offset():
    c = cam([("o", 10.0, 10.0)], max_range_m=2.0)
    assert len(c.capture((9.0, 10.0, 0.0)).detections) == 1
    assert c.capture((0.0, 0.0, 0.0)).detections == []


def test_fov_filtering():
    c = cam([("side", 0.0, 2.0)], fov_deg=90.0)
    assert c.capture((0, 0, 0)).detections == []
    assert len(c.capture((0, 0, math.pi / 2)).detections) == 1


def test_fov_edges():
    c = cam([("o", 0.0, 2.0)], fov_deg=90.0)
    # bearing = pi/4 + 0.3 -> outside
    assert c.capture((0, 0, math.pi / 4 - 0.3)).detections == []
    # bearing = pi/4 - 0.3 -> inside
    assert len(c.capture((0, 0, math.pi / 4 + 0.3)).detections) == 1


def test_sweep_sees_behind():
    c = cam([("behind", -2.0, 0.0)])
    assert c.capture((0, 0, 0)).detections == []
    f = c.capture((0, 0, 0), sweep=True)
    assert len(f.detections) == 1
    assert abs(f.detections[0].bearing_rad) == pytest.approx(math.pi, abs=0.1)


def test_bearing_relative_to_heading():
    c = cam([("o", 0.0, 2.0)])
    f = c.capture((0, 0, math.pi / 2 - 0.2))
    assert f.detections[0].bearing_rad == pytest.approx(0.2, abs=0.06)
    f = c.capture((0, 0, math.pi / 2 + 0.2))
    assert f.detections[0].bearing_rad == pytest.approx(-0.2, abs=0.06)


def test_miss_rate_one_drops_all():
    c = SimulatedCamera([("a", 1.0, 0.0)], miss_rate=1.0)
    assert c.capture((0, 0, 0)).detections == []


def test_miss_rate_zero_keeps_all():
    c = cam([("a", 1.0, 0.0), ("b", 2.0, 0.5)])
    for _ in range(20):
        assert len(c.capture((0, 0, 0)).detections) == 2


def test_partial_miss_rate_drops_some():
    c = SimulatedCamera([("a", 1.0, 0.0)], miss_rate=0.5, seed=3)
    n = sum(len(c.capture((0, 0, 0)).detections) for _ in range(200))
    assert 40 < n < 160


def test_determinism_same_seed():
    objs = [("a", 1.0, 0.0), ("b", 2.0, 0.5), ("c", 3.0, -0.5)]
    a = SimulatedCamera(objs, miss_rate=0.3, seed=7)
    b = SimulatedCamera(objs, miss_rate=0.3, seed=7)
    for _ in range(5):
        assert a.capture((0, 0, 0)).detections == b.capture((0, 0, 0)).detections


def test_range_nonnegative_and_confidence_clamped():
    c = cam([("a", 0.0, 0.0)])
    for _ in range(50):
        for d in c.capture((0, 0, 0), sweep=True).detections:
            assert d.range_m >= 0.0
            assert 0.0 <= d.confidence <= 1.0


def test_confidence_decreases_with_distance_on_average():
    near = cam([("a", 0.5, 0.0)], seed=1)
    far = cam([("a", 4.5, 0.0)], seed=1)
    n = [near.capture((0, 0, 0)).detections[0].confidence for _ in range(100)]
    f = [far.capture((0, 0, 0)).detections[0].confidence for _ in range(100)]
    assert sum(n) / 100 > sum(f) / 100


def test_set_objects():
    c = cam([("a", 1.0, 0.0)])
    c.set_objects([("b", 1.0, 0.0), ("c", 1.5, 0.0)])
    labels = [d.label for d in c.capture((0, 0, 0)).detections]
    assert labels == ["b", "c"]
    c.set_objects([])
    assert c.capture((0, 0, 0)).detections == []


def test_constructor_copies_input():
    objs = [("a", 1.0, 0.0)]
    c = cam(objs)
    objs.append(("b", 1.0, 0.1))
    assert len(c.capture((0, 0, 0)).detections) == 1


def test_set_objects_copies_input():
    c = cam([])
    objs = [("a", 1.0, 0.0)]
    c.set_objects(objs)
    objs.append(("b", 1.0, 0.1))
    assert len(c.capture((0, 0, 0)).detections) == 1


def test_constructor_attributes():
    c = SimulatedCamera([], fov_deg=60.0, max_range_m=3.0, miss_rate=0.1)
    assert c.fov_rad == pytest.approx(math.radians(60))
    assert c.max_range_m == 3.0
    assert c.miss_rate == 0.1


def test_detection_order_follows_objects():
    c = cam([("x", 1, 0), ("y", 2, 0), ("z", 3, 0)])
    assert [d.label for d in c.capture((0, 0, 0)).detections] == ["x", "y", "z"]
