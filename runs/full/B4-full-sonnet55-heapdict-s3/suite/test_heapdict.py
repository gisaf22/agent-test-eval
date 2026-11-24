# tests/test_heapdict.py
import random
import pytest
from heapdict import heapdict


def drain(h):
    out = []
    while len(h):
        out.append(h.popitem())
    return out


def check_invariant(h):
    for i, w in enumerate(h.heap):
        assert w[2] == i
        assert h.d[w[1]] is w
        if i:
            assert h.heap[(i - 1) >> 1][0] <= w[0]
    assert len(h.heap) == len(h.d)


def test_empty():
    h = heapdict()
    assert len(h) == 0
    assert list(h) == []
    assert not h


def test_init_from_dict_and_kwargs():
    h = heapdict({"a": 3, "b": 1}, c=2)
    assert len(h) == 3
    assert h["a"] == 3
    assert drain(h) == [("b", 1), ("c", 2), ("a", 3)]


def test_init_from_pairs():
    h = heapdict([("x", 5), ("y", 4)])
    assert h.peekitem() == ("y", 4)


def test_setitem_getitem():
    h = heapdict()
    h["a"] = 1
    assert h["a"] == 1
    assert "a" in h
    with pytest.raises(KeyError):
        h["missing"]


def test_popitem_order():
    h = heapdict()
    data = {"a": 5, "b": 2, "c": 9, "d": 1, "e": 7}
    for k, v in data.items():
        h[k] = v
    assert drain(h) == sorted(data.items(), key=lambda kv: kv[1])


def test_peekitem_does_not_remove():
    h = heapdict(a=2, b=1)
    assert h.peekitem() == ("b", 1)
    assert len(h) == 2
    assert h.peekitem() == ("b", 1)


def test_empty_popitem_and_peekitem_raise():
    h = heapdict()
    with pytest.raises((KeyError, IndexError)):
        h.popitem()
    with pytest.raises((KeyError, IndexError)):
        h.peekitem()


def test_update_existing_key_priority():
    h = heapdict(a=1, b=2, c=3)
    h["a"] = 10
    assert len(h) == 3
    assert h["a"] == 10
    assert h.peekitem() == ("b", 2)
    h["c"] = 0
    assert h.peekitem() == ("c", 0)
    check_invariant(h)
    assert drain(h) == [("c", 0), ("b", 2), ("a", 10)]


def test_delitem():
    h = heapdict({k: v for k, v in zip("abcdefg", [4, 2, 6, 1, 3, 5, 7])})
    del h["d"]
    assert "d" not in h
    assert len(h) == 6
    check_invariant(h)
    del h["g"]
    check_invariant(h)
    assert drain(h) == [("b", 2), ("e", 3), ("a", 4), ("f", 5), ("c", 6)]


def test_delitem_missing():
    h = heapdict(a=1)
    with pytest.raises(KeyError):
        del h["zz"]


def test_delete_only_item():
    h = heapdict(a=1)
    del h["a"]
    assert len(h) == 0


def test_clear():
    h = heapdict(a=1, b=2)
    h.clear()
    assert len(h) == 0
    assert h.heap == []
    h["z"] = 3
    assert h.popitem() == ("z", 3)


def test_pop_with_default_and_key():
    h = heapdict(a=1, b=2)
    assert h.pop("b") == 2
    assert h.pop("nope", None) is None
    with pytest.raises(KeyError):
        h.pop("nope")
    assert list(h) == ["a"]


def test_mapping_methods():
    h = heapdict(a=1, b=2)
    assert set(h.keys()) == {"a", "b"}
    assert sorted(h.values()) == [1, 2]
    assert dict(h.items()) == {"a": 1, "b": 2}
    assert h.get("a") == 1
    assert h.get("q", 7) == 7
    h.setdefault("c", 0)
    assert h.peekitem() == ("c", 0)


def test_docstrings_present():
    assert heapdict.popitem.__doc__
    assert heapdict.peekitem.__doc__
    assert heapdict.__len__.__doc__ == dict.__len__.__doc__


def test_randomized_against_reference():
    rng = random.Random(1234)
    h = heapdict()
    ref = {}
    for _ in range(500):
        op = rng.random()
        if op < 0.5:
            k = rng.randrange(40)
            v = rng.randrange(1000)
            h[k] = v
            ref[k] = v
        elif op < 0.75 and ref:
            k = rng.choice(sorted(ref))
            del h[k]
            del ref[k]
        elif ref:
            k, v = h.popitem()
            assert v == min(ref.values())
            assert ref.pop(k) == v
        check_invariant(h)
        assert dict(h) == ref
        if ref:
            assert h.peekitem()[1] == min(ref.values())


def test_duplicate_values():
    h = heapdict(a=1, b=1, c=1)
    vals = drain(h)
    assert sorted(k for k, _ in vals) == ["a", "b", "c"]
    assert all(v == 1 for _, v in vals)
