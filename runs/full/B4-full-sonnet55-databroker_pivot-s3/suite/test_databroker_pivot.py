# tests/test_databroker_pivot.py
import pytest

from databroker_pivot import pivot_timeseries, zip_events, reset_time


def make_desc(uid="d1", run_start="rs1", keys=None):
    if keys is None:
        keys = {
            "arr": {"shape": (3,), "dtype": "array", "source": "s"},
            "arr2": {"shape": (3,), "dtype": "array", "source": "s"},
            "img": {"shape": (3, 2), "dtype": "array", "source": "s"},
            "stat": {"shape": (), "dtype": "number", "source": "s"},
            "bad": {"shape": (), "dtype": "number", "source": "s"},
        }
    return {"uid": uid, "run_start": run_start, "data_keys": keys}


def make_event(desc, uid="e1", time=10.0, data=None, ts=None):
    data = data if data is not None else {
        "arr": [1, 2, 3], "arr2": [4, 5, 6],
        "img": [[1, 2], [3, 4], [5, 6]], "stat": 7, "bad": 0}
    ts = ts if ts is not None else {k: 1.0 + i for i, k in enumerate(data)}
    return {"uid": uid, "time": time, "descriptor": desc,
            "data": data, "timestamps": ts, "seq_no": 0}


# ---------- pivot_timeseries ----------

def test_pivot_basic():
    d = make_desc()
    evs = [make_event(d, "e1"), make_event(d, "e2", time=20.0)]
    out = list(pivot_timeseries(evs, ["arr", "arr2"], ["stat"]))
    assert len(out) == 6
    assert [e["seq_no"] for e in out] == list(range(6))
    assert [e["data"]["_ind"] for e in out] == [0, 1, 2, 0, 1, 2]
    assert [e["data"]["arr"] for e in out[:3]] == [1, 2, 3]
    assert [e["data"]["arr2"] for e in out[:3]] == [4, 5, 6]
    assert all(e["data"]["stat"] == 7 for e in out)
    assert all(e["time"] == 10.0 for e in out[:3])
    assert all(e["time"] == 20.0 for e in out[3:])
    assert len({e["uid"] for e in out}) == 6
    assert set(out[0]["data"]) == {"arr", "arr2", "stat", "_ind"}
    assert set(out[0]["timestamps"]) == {"arr", "arr2", "stat", "_ind"}


def test_pivot_descriptor():
    d = make_desc()
    out = list(pivot_timeseries([make_event(d, "e1")], ["arr", "img"]))
    nd = out[0]["descriptor"]
    assert nd["run_start"] == "rs1"
    assert nd["uid"] != "d1"
    dk = nd["data_keys"]
    assert dk["_ind"]["dtype"] == "number"
    assert dk["arr"] == {"shape": (), "dtype": "number", "source": "e1"}
    assert dk["img"] == {"shape": (2,), "dtype": "array", "source": "e1"}
    assert "stat" not in dk
    assert "stat" not in out[0]["data"]


def test_pivot_static_in_descriptor():
    d = make_desc()
    out = list(pivot_timeseries([make_event(d)], ["arr"], ["stat"]))
    assert out[0]["descriptor"]["data_keys"]["stat"] == d["data_keys"]["stat"]


def test_pivot_overlap():
    d = make_desc()
    with pytest.raises(RuntimeError):
        list(pivot_timeseries([make_event(d)], ["arr"], ["arr"]))


def test_pivot_non_array():
    d = make_desc()
    with pytest.raises(RuntimeError):
        list(pivot_timeseries([make_event(d)], ["bad"]))


def test_pivot_unequal_lengths():
    keys = {"a": {"shape": (3,), "dtype": "array", "source": "s"},
            "b": {"shape": (4,), "dtype": "array", "source": "s"}}
    d = make_desc(keys=keys)
    ev = make_event(d, data={"a": [1, 2, 3], "b": [1, 2, 3, 4]})
    with pytest.raises(RuntimeError):
        list(pivot_timeseries([ev], ["a", "b"]))


def test_pivot_empty_events():
    # StopIteration inside a generator becomes RuntimeError (PEP 479)
    with pytest.raises(RuntimeError):
        list(pivot_timeseries([], ["arr"]))


def test_pivot_accepts_iterator():
    d = make_desc()
    out = list(pivot_timeseries(iter([make_event(d)]), ["arr"]))
    assert len(out) == 3


def test_pivot_descriptor_per_source_event():
    d = make_desc()
    out = list(pivot_timeseries(
        [make_event(d, "e1"), make_event(d, "e2")], ["arr"]))
    # same source event -> same descriptor object
    assert out[0]["descriptor"] is out[2]["descriptor"]
    # different source events -> distinct descriptors, same uid
    assert out[0]["descriptor"] is not out[3]["descriptor"]
    assert out[0]["descriptor"]["data_keys"]["arr"]["source"] == "e1"
    assert out[3]["descriptor"]["data_keys"]["arr"]["source"] == "e2"
    assert out[0]["descriptor"]["uid"] == out[3]["descriptor"]["uid"]


# ---------- zip_events ----------

def two_streams(n=2, rs2="rs1"):
    d1 = make_desc("d1", "rs1", {"x": {"shape": (), "dtype": "number", "source": "a"}})
    d2 = make_desc("d2", rs2, {"y": {"shape": (), "dtype": "number", "source": "b"}})
    s1 = [make_event(d1, "a%d" % i, data={"x": i}, ts={"x": i + .5}) for i in range(n)]
    s2 = [make_event(d2, "b%d" % i, data={"y": -i}, ts={"y": i + .25}) for i in range(n)]
    return s1, s2


@pytest.mark.parametrize("lazy", [True, False])
def test_zip_basic(lazy):
    s1, s2 = two_streams(3)
    out = list(zip_events(s1, s2, lazy=lazy))
    assert len(out) == 3
    assert [e["seq_no"] for e in out] == [0, 1, 2]
    assert out[1]["data"] == {"x": 1, "y": -1}
    assert out[1]["timestamps"] == {"x": 1.5, "y": 1.25}
    dk = out[0]["descriptor"]["data_keys"]
    assert set(dk) == {"x", "y"}
    assert out[0]["descriptor"]["run_start"] == "rs1"
    assert out[0]["descriptor"] is out[1]["descriptor"]


def test_zip_unknown_kwarg():
    s1, s2 = two_streams()
    with pytest.raises(TypeError):
        list(zip_events(s1, s2, bogus=1))


def test_zip_different_runstart():
    s1, s2 = two_streams(rs2="other")
    with pytest.raises(RuntimeError):
        list(zip_events(s1, s2))


def test_zip_overlapping_keys():
    d1 = make_desc("d1", "rs", {"x": {}})
    d2 = make_desc("d2", "rs", {"x": {}})
    s1 = [make_event(d1, data={"x": 1}, ts={"x": 1})]
    s2 = [make_event(d2, data={"x": 1}, ts={"x": 1})]
    with pytest.raises(RuntimeError):
        list(zip_events(s1, s2))


def test_zip_unequal_lazy():
    s1, s2 = two_streams(3)
    with pytest.raises(RuntimeError):
        list(zip_events(s1, s2[:2]))
    with pytest.raises(RuntimeError):
        list(zip_events(s1[:2], s2))


def test_zip_unequal_not_lazy():
    s1, s2 = two_streams(3)
    with pytest.raises(RuntimeError):
        list(zip_events(s1, s2[:2], lazy=False))


def test_zip_descriptor_change():
    s1, s2 = two_streams(2)
    other = dict(s1[0]["descriptor"], uid="zzz")
    s1[1] = dict(s1[1], descriptor=other)
    with pytest.raises(RuntimeError):
        list(zip_events(s1, s2))


def test_zip_empty_stream():
    # next() on an empty stream raises StopIteration -> RuntimeError
    s1, _ = two_streams(1)
    with pytest.raises(RuntimeError):
        list(zip_events(s1, []))


def test_zip_single_stream():
    s1, _ = two_streams(2)
    out = list(zip_events(s1))
    assert [e["data"] for e in out] == [{"x": 0}, {"x": 1}]


# ---------- reset_time ----------

def test_reset_time_timestamps():
    d = make_desc()
    ev = make_event(d, time=1.0, data={"a": 5}, ts={"a": 99.0})
    out = list(reset_time([ev], "a"))
    assert out[0]["time"] == 99.0
    assert ev["time"] == 1.0


def test_reset_time_data():
    d = make_desc()
    ev = make_event(d, time=1.0, data={"a": 5}, ts={"a": 99.0})
    out = list(reset_time([ev], "a", source="data"))
    assert out[0]["time"] == 5


def test_reset_time_missing_field():
    d = make_desc()
    ev = make_event(d, data={"a": 5}, ts={"a": 1.0})
    with pytest.raises(KeyError):
        list(reset_time([ev], "nope"))


def test_reset_time_empty():
    assert list(reset_time([], "a")) == []
