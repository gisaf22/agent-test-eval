# tests/test_databroker_pivot.py
import pytest

from databroker_pivot import pivot_timeseries, zip_events, reset_time


def make_desc(uid="d1", run_start="rs1", keys=None):
    if keys is None:
        keys = {
            "arr": {"shape": (3,), "dtype": "array", "source": "x"},
            "arr2": {"shape": (3,), "dtype": "array", "source": "x"},
            "stat": {"shape": (), "dtype": "number", "source": "y"},
        }
    return {"uid": uid, "run_start": run_start, "data_keys": keys}


def make_event(desc, uid, data, time=1.0, ts=None):
    if ts is None:
        ts = {k: 0.5 for k in data}
    return {"uid": uid, "time": time, "descriptor": desc,
            "data": data, "timestamps": ts, "seq_no": 0}


def test_pivot_basic():
    desc = make_desc()
    evs = [
        make_event(desc, "e1", {"arr": [1, 2, 3], "arr2": [4, 5, 6], "stat": 10}),
        make_event(desc, "e2", {"arr": [7, 8, 9], "arr2": [1, 1, 1], "stat": 20}),
    ]
    out = list(pivot_timeseries(evs, ["arr", "arr2"], ["stat"]))
    assert len(out) == 6
    assert [e["seq_no"] for e in out] == list(range(6))
    assert [e["data"]["arr"] for e in out] == [1, 2, 3, 7, 8, 9]
    assert [e["data"]["arr2"] for e in out] == [4, 5, 6, 1, 1, 1]
    assert [e["data"]["_ind"] for e in out] == [0, 1, 2] * 2
    assert [e["data"]["stat"] for e in out] == [10] * 3 + [20] * 3
    assert len({e["uid"] for e in out}) == 6
    for e in out:
        assert set(e["data"]) == {"arr", "arr2", "stat", "_ind"}
        assert set(e["timestamps"]) == {"arr", "arr2", "stat", "_ind"}
        assert e["time"] == 1.0


def test_pivot_descriptor():
    desc = make_desc()
    ev = make_event(desc, "e1", {"arr": [1, 2, 3], "arr2": [4, 5, 6], "stat": 1})
    out = list(pivot_timeseries([ev], ["arr"], ["stat"]))
    nd = out[0]["descriptor"]
    assert nd["run_start"] == "rs1"
    assert nd["uid"] != "d1"
    assert nd["data_keys"]["arr"] == {"shape": (), "dtype": "number",
                                      "source": "e1"}
    assert nd["data_keys"]["_ind"]["source"] == "pivot"
    assert nd["data_keys"]["stat"] == desc["data_keys"]["stat"]
    assert "arr2" not in nd["data_keys"]
    assert all(e["descriptor"]["uid"] == nd["uid"] for e in out)


def test_pivot_2d_stays_array():
    keys = {"img": {"shape": (2, 4, 4), "dtype": "array", "source": "x"}}
    desc = make_desc(keys=keys)
    ev = make_event(desc, "e1", {"img": ["a", "b"]})
    out = list(pivot_timeseries([ev], ["img"]))
    assert len(out) == 2
    d = out[0]["descriptor"]["data_keys"]["img"]
    assert d["shape"] == (4, 4) and d["dtype"] == "array"


def test_pivot_overlap():
    desc = make_desc()
    ev = make_event(desc, "e1", {"arr": [1, 2, 3]})
    with pytest.raises(RuntimeError):
        list(pivot_timeseries([ev], ["arr"], ["arr"]))


def test_pivot_non_array():
    desc = make_desc()
    ev = make_event(desc, "e1", {"stat": 1})
    with pytest.raises(RuntimeError):
        list(pivot_timeseries([ev], ["stat"]))


def test_pivot_length_mismatch():
    keys = {"a": {"shape": (3,), "dtype": "array", "source": "x"},
            "b": {"shape": (2,), "dtype": "array", "source": "x"}}
    desc = make_desc(keys=keys)
    ev = make_event(desc, "e1", {"a": [1, 2, 3], "b": [1, 2]})
    with pytest.raises(RuntimeError):
        list(pivot_timeseries([ev], ["a", "b"]))


def _stream(uid_prefix, key, n, run_start="rs1", desc_uid=None):
    desc = make_desc(uid=desc_uid or uid_prefix + "d", run_start=run_start,
                     keys={key: {"shape": (), "dtype": "number",
                                 "source": "s"}})
    return [make_event(desc, "%s%d" % (uid_prefix, i), {key: i})
            for i in range(n)]


def test_zip_basic():
    a = _stream("a", "x", 3)
    b = _stream("b", "y", 3)
    out = list(zip_events(a, b))
    assert len(out) == 3
    for i, e in enumerate(out):
        assert e["seq_no"] == i
        assert e["data"] == {"x": i, "y": i}
        assert set(e["timestamps"]) == {"x", "y"}
    assert set(out[0]["descriptor"]["data_keys"]) == {"x", "y"}
    assert out[0]["descriptor"]["run_start"] == "rs1"
    assert out[0]["descriptor"] is out[1]["descriptor"]


def test_zip_non_lazy_and_iterators():
    out = list(zip_events(iter(_stream("a", "x", 2)),
                          iter(_stream("b", "y", 2)), lazy=False))
    assert len(out) == 2


def test_zip_non_lazy_length_mismatch():
    with pytest.raises(RuntimeError):
        list(zip_events(_stream("a", "x", 2), _stream("b", "y", 3),
                        lazy=False))


def test_zip_lazy_length_mismatch():
    with pytest.raises(RuntimeError):
        list(zip_events(_stream("a", "x", 2), _stream("b", "y", 3)))
    with pytest.raises(RuntimeError):
        list(zip_events(_stream("a", "x", 3), _stream("b", "y", 2)))


def test_zip_unknown_kwarg():
    with pytest.raises(TypeError):
        list(zip_events(_stream("a", "x", 1), bogus=1))


def test_zip_different_run_start():
    with pytest.raises(RuntimeError):
        list(zip_events(_stream("a", "x", 1),
                        _stream("b", "y", 1, run_start="other")))


def test_zip_overlapping_keys():
    with pytest.raises(RuntimeError):
        list(zip_events(_stream("a", "x", 1), _stream("b", "x", 1)))


def test_zip_descriptor_change():
    a = _stream("a", "x", 2)
    other = make_desc(uid="changed", keys=a[0]["descriptor"]["data_keys"])
    a[1] = make_event(other, "a1", {"x": 1})
    with pytest.raises(RuntimeError):
        list(zip_events(a, _stream("b", "y", 2)))


def test_reset_time_timestamps():
    desc = make_desc()
    ev = make_event(desc, "e", {"stat": 1}, time=1.0, ts={"stat": 99.0})
    out = list(reset_time([ev], "stat"))
    assert out[0]["time"] == 99.0
    assert ev["time"] == 1.0
    assert out[0] is not ev


def test_reset_time_data():
    desc = make_desc()
    ev = make_event(desc, "e", {"stat": 5.5}, time=1.0)
    out = list(reset_time([ev], "stat", source="data"))
    assert out[0]["time"] == 5.5


def test_reset_time_missing_field():
    ev = make_event(make_desc(), "e", {"stat": 1})
    with pytest.raises(KeyError):
        list(reset_time([ev], "nope"))


def test_reset_time_empty():
    assert list(reset_time([], "x")) == []
