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


def pivot_events(n=2):
    desc = make_desc()
    return desc, [
        make_event(desc, "e%d" % i,
                   {"arr": [i * 10 + j for j in range(3)],
                    "arr2": [-(i * 10 + j) for j in range(3)],
                    "stat": i})
        for i in range(n)
    ]


# ---------- pivot_timeseries ----------

def test_pivot_basic_count_and_values():
    desc, evs = pivot_events(2)
    out = list(pivot_timeseries(evs, ["arr"], ["stat"]))
    assert len(out) == 6
    assert [e["seq_no"] for e in out] == list(range(6))
    assert [e["data"]["arr"] for e in out] == [0, 1, 2, 10, 11, 12]
    assert [e["data"]["_ind"] for e in out] == [0, 1, 2, 0, 1, 2]
    assert [e["data"]["stat"] for e in out] == [0, 0, 0, 1, 1, 1]
    assert out[0]["time"] == 1.0
    assert len({e["uid"] for e in out}) == 6


def test_pivot_multiple_keys():
    desc, evs = pivot_events(1)
    out = list(pivot_timeseries(evs, ["arr", "arr2"]))
    assert [(e["data"]["arr"], e["data"]["arr2"]) for e in out] == [
        (0, 0), (1, -1), (2, -2)]
    assert "stat" not in out[0]["data"]


def test_pivot_descriptor():
    desc, evs = pivot_events(1)
    out = list(pivot_timeseries(evs, ["arr"], ["stat"]))
    nd = out[0]["descriptor"]
    assert nd["uid"] != desc["uid"]
    assert nd["run_start"] == "rs1"
    assert nd["data_keys"]["_ind"]["dtype"] == "number"
    assert nd["data_keys"]["stat"] == desc["data_keys"]["stat"]
    assert nd["data_keys"]["arr"]["dtype"] == "number"
    assert nd["data_keys"]["arr"]["shape"] == ()
    assert nd["data_keys"]["arr"]["source"] == "e0"


def test_pivot_nd_shape_stays_array():
    keys = {"img": {"shape": (2, 4, 4), "dtype": "array", "source": "s"}}
    desc = make_desc(keys=keys)
    ev = make_event(desc, "e", {"img": ["a", "b"]})
    out = list(pivot_timeseries([ev], ["img"]))
    assert len(out) == 2
    k = out[0]["descriptor"]["data_keys"]["img"]
    assert k["dtype"] == "array" and k["shape"] == (4, 4)


def test_pivot_timestamps():
    desc, evs = pivot_events(1)
    out = list(pivot_timeseries(evs, ["arr"], ["stat"]))
    ts = out[0]["timestamps"]
    assert set(ts) == {"arr", "stat", "_ind"}
    assert ts["arr"] == 0.5


def test_pivot_overlap_raises():
    desc, evs = pivot_events(1)
    with pytest.raises(RuntimeError):
        list(pivot_timeseries(evs, ["arr"], ["arr"]))


def test_pivot_non_array_raises():
    desc, evs = pivot_events(1)
    with pytest.raises(RuntimeError):
        list(pivot_timeseries(evs, ["stat"]))


def test_pivot_length_mismatch_raises():
    keys = {
        "a": {"shape": (3,), "dtype": "array", "source": "s"},
        "b": {"shape": (4,), "dtype": "array", "source": "s"},
    }
    desc = make_desc(keys=keys)
    ev = make_event(desc, "e", {"a": [1, 2, 3], "b": [1, 2, 3, 4]})
    with pytest.raises(RuntimeError):
        list(pivot_timeseries([ev], ["a", "b"]))


def test_pivot_empty_events_raises():
    # StopIteration inside a generator becomes RuntimeError (PEP 479)
    with pytest.raises(RuntimeError):
        list(pivot_timeseries([], ["arr"]))


def test_pivot_accepts_iterator():
    desc, evs = pivot_events(2)
    out = list(pivot_timeseries(iter(evs), ["arr"]))
    assert len(out) == 6


# ---------- zip_events ----------

def stream(desc, prefix, n, key):
    return [make_event(desc, "%s%d" % (prefix, i), {key: i},
                       ts={key: float(i)}) for i in range(n)]


def two_streams(n=3):
    d1 = make_desc("d1", keys={"a": {"shape": (), "dtype": "number", "source": "s"}})
    d2 = make_desc("d2", keys={"b": {"shape": (), "dtype": "number", "source": "s"}})
    return d1, d2, stream(d1, "x", n, "a"), stream(d2, "y", n, "b")


def test_zip_basic():
    d1, d2, s1, s2 = two_streams()
    out = list(zip_events(s1, s2))
    assert len(out) == 3
    for i, e in enumerate(out):
        assert e["seq_no"] == i
        assert e["data"] == {"a": i, "b": i}
        assert e["timestamps"] == {"a": float(i), "b": float(i)}
    desc = out[0]["descriptor"]
    assert set(desc["data_keys"]) == {"a", "b"}
    assert desc["run_start"] == "rs1"
    assert desc["uid"] not in ("d1", "d2")
    assert all(e["descriptor"] is desc for e in out)


def test_zip_not_lazy():
    d1, d2, s1, s2 = two_streams()
    out = list(zip_events(iter(s1), iter(s2), lazy=False))
    assert len(out) == 3


def test_zip_not_lazy_length_mismatch():
    d1, d2, s1, s2 = two_streams()
    with pytest.raises(RuntimeError):
        list(zip_events(s1, s2[:2], lazy=False))


def test_zip_lazy_length_mismatch():
    d1, d2, s1, s2 = two_streams()
    with pytest.raises(RuntimeError):
        list(zip_events(s1, s2[:2]))


def test_zip_unknown_kwarg():
    d1, d2, s1, s2 = two_streams()
    with pytest.raises(TypeError):
        list(zip_events(s1, s2, bogus=1))


def test_zip_different_run_start():
    d1 = make_desc("d1", "r1", {"a": {}})
    d2 = make_desc("d2", "r2", {"b": {}})
    with pytest.raises(RuntimeError):
        list(zip_events(stream(d1, "x", 1, "a"), stream(d2, "y", 1, "b")))


def test_zip_overlapping_keys():
    d1 = make_desc("d1", keys={"a": {}})
    d2 = make_desc("d2", keys={"a": {}})
    with pytest.raises(RuntimeError):
        list(zip_events(stream(d1, "x", 1, "a"), stream(d2, "y", 1, "a")))


def test_zip_descriptor_change():
    d1, d2, s1, s2 = two_streams(2)
    other = make_desc("d1b", keys=d1["data_keys"])
    s1[1] = make_event(other, "x1", {"a": 1}, ts={"a": 1.0})
    with pytest.raises(RuntimeError):
        list(zip_events(s1, s2))


def test_zip_single_stream():
    d1, d2, s1, s2 = two_streams(2)
    out = list(zip_events(s1))
    assert [e["data"] for e in out] == [{"a": 0}, {"a": 1}]


# ---------- reset_time ----------

def test_reset_time_timestamps():
    desc = make_desc()
    ev = make_event(desc, "e", {"a": 1}, time=1.0, ts={"a": 99.0})
    out = list(reset_time([ev], "a"))
    assert out[0]["time"] == 99.0
    assert ev["time"] == 1.0


def test_reset_time_data_source():
    desc = make_desc()
    evs = [make_event(desc, "e%d" % i, {"a": 10 + i}, ts={"a": 0.0})
           for i in range(3)]
    out = list(reset_time(evs, "a", source="data"))
    assert [e["time"] for e in out] == [10, 11, 12]
    assert out[0]["uid"] == "e0"


def test_reset_time_missing_field():
    desc = make_desc()
    ev = make_event(desc, "e", {"a": 1})
    with pytest.raises(KeyError):
        list(reset_time([ev], "zzz"))


def test_reset_time_is_lazy_and_empty():
    assert list(reset_time([], "a")) == []
