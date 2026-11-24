# tests/test_blackmamba_open_source_r_vision.py
import math

import pytest

from blackmamba_open_source_r_vision import (
    Frame,
    RawDetection,
    SimulatedCamera,
    _wrap,
)


def cam(objs, **kw):
    kw.setdefault("miss_rate", 0.0)
    return SimulatedCamera(objs, **kw)


def test_wrap_range_and_values():
    assert _wrap(0.0) == pytest.approx(0.0)
    assert _wrap(2 * math.pi) == pytest.approx(0.0)
    assert _wrap(3 * math.pi / 2) == pytest.approx(-math.pi / 2)
    assert _wrap(-3 * math.pi / 2) == pytest.approx(math.pi / 2)
    for a in [-10, -3.5, 0.3, 3.5, 10, 100]:
        assert -math.pi <= _wrap(a) < math.pi


def test_raw_detection_frozen():
    d = RawDetection("a", 1.0, 0.0, 0.9)
    with pytest.raises(Exception):
        d.label = "b"


def test_frame_default_detections_not_shared():
    f1 = Frame(0.0, (0, 0, 0))
    f2 = Frame(0.0, (0, 0, 0))
    f1.detections.append(RawDetection("a", 1, 0, 1))
    assert f2.detections == []


def test_capture_returns_frame_with_pose_and_timestamp():
    c = cam([])
    f = c.capture((1.0, 2.0, 0.5), timestamp_s=3.5)
    assert isinstance(f, Frame)
    assert f.pose == (1.0, 2.0, 0.5)
    assert f.timestamp_s == 3.5
    assert f.detections == []


def test_default_timestamp():
    assert cam([]).capture((0, 0, 0)).timestamp_s == 0.0


def test_detects_object_in_front():
    c = cam([("cup", 2.0, 0.0)])
    f = c.capture((0, 0, 0))
    assert len(f.detections) == 1
    d = f.detections[0]
    assert d.label == "cup"
    assert d.range_m == pytest.approx(2.0, abs=0.2)
    assert d.bearing_rad == pytest.approx(0.0, abs=0.1)
    assert 0.0 <= d.confidence <= 1.0


def test_out_of_range_excluded():
    c = cam([("far", 6.0, 0.0)], max_range_m=5.0)
    assert c.capture((0, 0, 0)).detections == []
    assert len(c.capture((0, 0, 0), sweep=True).detections) == 0


def test_custom_max_range():
    c = cam([("x", 8.0, 0.0)], max_range_m=10.0)
    assert len(c.capture((0, 0, 0)).detections) == 1


def test_outside_fov_excluded_but_sweep_sees():
    c = cam([("back", -2.0, 0.0)])
    assert c.capture((0, 0, 0)).detections == []
    f = c.capture((0, 0, 0), sweep=True)
    assert len(f.detections) == 1
    assert abs(abs(f.detections[0].bearing_rad) - math.pi) < 0.1


def test_fov_edges():
    c = cam([("in", 2.0, 2.0 * math.tan(math.radians(40)))], fov_deg=90)
    assert len(c.capture((0, 0, 0)).detections) == 1
    c = cam([("out", 2.0, 2.0 * math.tan(math.radians(50)))], fov_deg=90)
    assert c.capture((0, 0, 0)).detections == []


def test_heading_affects_bearing_and_visibility():
    c = cam([("o", 0.0, 2.0)])
    assert c.capture((0, 0, 0)).detections == []
    f = c.capture((0, 0, math.pi / 2))
    assert len(f.detections) == 1
    assert f.detections[0].bearing_rad == pytest.approx(0.0, abs=0.1)


def test_bearing_sign():
    c = cam([("l", 2.0, 1.0)])
    assert c.capture((0, 0, 0)).detections[0].bearing_rad > 0
    c = cam([("r", 2.0, -1.0)])
    assert c.capture((0, 0, 0)).detections[0].bearing_rad < 0


def test_miss_rate_one_drops_all():
    c = SimulatedCamera([("a", 1.0, 0.0)] * 5, miss_rate=1.0)
    assert c.capture((0, 0, 0)).detections == []


def test_miss_rate_zero_keeps_all():
    c = cam([("a", 1.0, 0.0), ("b", 2.0, 0.5), ("c", 1.0, -0.5)])
    f = c.capture((0, 0, 0))
    assert [d.label for d in f.detections] == ["a", "b", "c"]


def test_deterministic_with_seed():
    objs = [("a", 1.0, 0.2), ("b", 3.0, -1.0)]
    f1 = SimulatedCamera(objs, seed=5).capture((0, 0, 0))
    f2 = SimulatedCamera(objs, seed=5).capture((0, 0, 0))
    assert f1.detections == f2.detections


def test_different_seeds_differ():
    objs = [("a", 1.0, 0.2)]
    f1 = cam(objs, seed=1).capture((0, 0, 0))
    f2 = cam(objs, seed=2).capture((0, 0, 0))
    assert f1.detections != f2.detections


def test_confidence_decreases_with_distance_on_average():
    near = cam([("n", 0.5, 0.0)])
    far = cam([("f", 4.5, 0.0)])
    n = sum(near.capture((0, 0, 0)).detections[0].confidence for _ in range(50))
    f = sum(far.capture((0, 0, 0)).detections[0].confidence for _ in range(50))
    assert n > f


def test_confidence_and_range_bounds():
    c = cam([("a", 0.0, 0.0), ("b", 0.01, 0.0)])
    for _ in range(100):
        for d in c.capture((0, 0, 0), sweep=True).detections:
            assert d.range_m >= 0.0
            assert 0.0 <= d.confidence <= 1.0


def test_set_objects_replaces_world():
    c = cam([("a", 1.0, 0.0)])
    c.set_objects([("b", 2.0, 0.0), ("c", 1.0, 0.1)])
    assert [d.label for d in c.capture((0, 0, 0)).detections] == ["b", "c"]
    c.set_objects([])
    assert c.capture((0, 0, 0)).detections == []


def test_input_list_copied():
    objs = [("a", 1.0, 0.0)]
    c = cam(objs)
    objs.append(("b", 1.0, 0.0))
    assert len(c.capture((0, 0, 0)).detections) == 1


def test_fov_stored_in_radians():
    assert SimulatedCamera([], fov_deg=180).fov_rad == pytest.approx(math.pi)
