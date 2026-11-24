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
    assert _wrap(2 * math.pi) == pytest.approx(0.0, abs=1e-9)
    assert _wrap(3 * math.pi / 2) == pytest.approx(-math.pi / 2)
    assert _wrap(-3 * math.pi / 2) == pytest.approx(math.pi / 2)
    for a in [-10, -3.5, 0.3, 3.5, 10, 100]:
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


def test_capture_returns_frame_with_pose_and_timestamp():
    c = cam([])
    f = c.capture((1.0, 2.0, 0.5), timestamp_s=3.5)
    assert f.timestamp_s == 3.5
    assert f.pose == (1.0, 2.0, 0.5)
    assert f.detections == []


def test_detects_object_ahead():
    c = cam([("cup", 2.0, 0.0)])
    f = c.capture((0, 0, 0))
    assert len(f.detections) == 1
    d = f.detections[0]
    assert d.label == "cup"
    assert d.range_m == pytest.approx(2.0, abs=0.2)
    assert d.bearing_rad == pytest.approx(0.0, abs=0.1)
    assert 0.0 <= d.confidence <= 1.0


def test_out_of_range_not_detected():
    c = cam([("far", 6.0, 0.0)], max_range_m=5.0)
    assert c.capture((0, 0, 0), sweep=True).detections == []


def test_outside_fov_not_detected_but_sweep_detects():
    c = cam([("behind", -2.0, 0.0)])
    assert c.capture((0, 0, 0)).detections == []
    f = c.capture((0, 0, 0), sweep=True)
    assert len(f.detections) == 1
    assert abs(abs(f.detections[0].bearing_rad) - math.pi) < 0.1


def test_fov_boundary():
    c = cam([("o", math.cos(math.radians(60)), math.sin(math.radians(60)))],
            fov_deg=90.0)
    assert c.capture((0, 0, 0)).detections == []
    c2 = cam([("o", math.cos(math.radians(30)), math.sin(math.radians(30)))],
             fov_deg=90.0)
    assert len(c2.capture((0, 0, 0)).detections) == 1


def test_heading_affects_bearing():
    c = cam([("o", 0.0, 2.0)])
    assert c.capture((0, 0, 0)).detections == []
    f = c.capture((0, 0, math.pi / 2))
    assert len(f.detections) == 1
    assert f.detections[0].bearing_rad == pytest.approx(0.0, abs=0.1)


def test_bearing_sign():
    c = cam([("o", 2.0, 1.0)])
    assert c.capture((0, 0, 0)).detections[0].bearing_rad > 0
    c = cam([("o", 2.0, -1.0)])
    assert c.capture((0, 0, 0)).detections[0].bearing_rad < 0


def test_miss_rate_one_drops_all():
    c = SimulatedCamera([("a", 1.0, 0.0)], miss_rate=1.0)
    for _ in range(10):
        assert c.capture((0, 0, 0)).detections == []


def test_miss_rate_zero_keeps_all():
    c = cam([("a", 1.0, 0.0), ("b", 2.0, 0.5)])
    for _ in range(20):
        assert len(c.capture((0, 0, 0)).detections) == 2


def test_deterministic_with_seed():
    objs = [("a", 1.0, 0.0), ("b", 2.0, 0.5)]
    a = SimulatedCamera(objs, seed=5, miss_rate=0.3)
    b = SimulatedCamera(objs, seed=5, miss_rate=0.3)
    for _ in range(5):
        assert a.capture((0, 0, 0)).detections == b.capture((0, 0, 0)).detections


def test_set_objects_replaces():
    c = cam([("a", 1.0, 0.0)])
    c.set_objects([("b", 1.5, 0.0)])
    f = c.capture((0, 0, 0))
    assert [d.label for d in f.detections] == ["b"]
    c.set_objects([])
    assert c.capture((0, 0, 0)).detections == []


def test_input_list_copied():
    objs = [("a", 1.0, 0.0)]
    c = cam(objs)
    objs.clear()
    assert len(c.capture((0, 0, 0)).detections) == 1


def test_confidence_decreases_with_distance_on_average():
    near = cam([("a", 0.5, 0.0)])
    far = cam([("a", 4.5, 0.0)])
    n = sum(near.capture((0, 0, 0)).detections[0].confidence for _ in range(50))
    f = sum(far.capture((0, 0, 0)).detections[0].confidence for _ in range(50))
    assert n > f


def test_values_clamped():
    c = cam([("a", 0.0, 0.0)], seed=1)
    for _ in range(50):
        d = c.capture((0, 0, 0), sweep=True).detections[0]
        assert d.range_m >= 0.0
        assert 0.0 <= d.confidence <= 1.0


def test_fov_rad_conversion():
    c = cam([], fov_deg=180.0)
    assert c.fov_rad == pytest.approx(math.pi)


def test_detection_order_matches_objects():
    c = cam([("a", 1.0, 0.0), ("b", 2.0, 0.0), ("c", 3.0, 0.0)])
    assert [d.label for d in c.capture((0, 0, 0)).detections] == ["a", "b", "c"]
