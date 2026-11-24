# tests/test_heapdict.py
import random
import pytest
from heapdict import heapdict


def drain(h):
    out = []
    while len(h):
        out.append(h.popitem())
    return out


def test_empty():
    h = heapdict()
    assert len(h) == 0
    assert list(h) == []
    assert not h


def test_init_from_dict_and_kwargs_and_pairs():
    assert dict(heapdict({"a": 2, "b": 1})) == {"a": 2, "b": 1}
    assert dict(heapdict(a=3, b=4)) == {"a": 3, "b": 4}
    assert dict(heapdict([("x", 5), ("y", 0)])) == {"x": 5, "y": 0}


def test_getitem_setitem_contains():
    h = heapdict()
    h["a"] = 5
    assert h["a"] == 5
    assert "a" in h
    assert "b" not in h
    with pytest.raises(KeyError):
        h["b"]


def test_popitem_order():
    h = heapdict({"a": 3, "b": 1, "c": 2, "d": 0, "e": 10})
    assert drain(h) == [("d", 0), ("b", 1), ("c", 2), ("a", 3), ("e", 10)]


def test_peekitem_does_not_remove():
    h = heapdict({"a": 3, "b": 1})
    assert h.peekitem() == ("b", 1)
    assert len(h) == 2
    assert h.peekitem() == ("b", 1)


def test_empty_popitem_and_peekitem_raise():
    h = heapdict()
    with pytest.raises((KeyError, IndexError)):
        h.popitem()
    with pytest.raises((KeyError, IndexError)):
        h.peekitem()


def test_update_value_existing_key():
    h = heapdict({"a": 1, "b": 2, "c": 3})
    h["a"] = 10
    assert len(h) == 3
    assert h["a"] == 10
    assert h.peekitem() == ("b", 2)
    h["c"] = 0
    assert h.peekitem() == ("c", 0)
    assert drain(h) == [("c", 0), ("b", 2), ("a", 10)]


def test_delete_item():
    h = heapdict({k: v for k, v in zip("abcdefg", [5, 3, 7, 1, 9, 2, 8])})
    del h["d"]
    assert "d" not in h
    assert len(h) == 6
    del h["g"]
    assert drain(h) == [("f", 2), ("b", 3), ("a", 5), ("c", 7), ("e", 9)]


def test_delete_missing_raises():
    h = heapdict({"a": 1})
    with pytest.raises(KeyError):
        del h["z"]


def test_delete_only_item():
    h = heapdict({"a": 1})
    del h["a"]
    assert len(h) == 0


def test_clear():
    h = heapdict({"a": 1, "b": 2})
    h.clear()
    assert len(h) == 0
    assert list(h) == []
    h["z"] = 4
    assert h.peekitem() == ("z", 4)


def test_pop_with_key_and_default():
    h = heapdict({"a": 1, "b": 2})
    assert h.pop("b") == 2
    assert "b" not in h
    assert h.pop("zz", None) is None
    with pytest.raises(KeyError):
        h.pop("zz")


def test_iteration_and_mapping_views():
    h = heapdict({"a": 3, "b": 1, "c": 2})
    assert set(h) == {"a", "b", "c"}
    assert set(h.keys()) == {"a", "b", "c"}
    assert sorted(h.values()) == [1, 2, 3]
    assert set(h.items()) == {("a", 3), ("b", 1), ("c", 2)}


def test_setdefault():
    h = heapdict()
    assert h.setdefault("a", 4) == 4
    assert h.setdefault("a", 9) == 4


def test_random_operations_against_reference():
    rng = random.Random(12345)
    h = heapdict()
    ref = {}
    for step in range(2000):
        op = rng.random()
        if op < 0.5:
            k = rng.randrange(50)
            v = rng.random()
            h[k] = v
            ref[k] = v
        elif op < 0.7 and ref:
            k = rng.choice(sorted(ref))
            del h[k]
            del ref[k]
        elif ref:
            k, v = h.popitem()
            assert v == min(ref.values())
            assert ref.pop(k) == v
        assert len(h) == len(ref)
        if ref:
            assert h.peekitem()[1] == min(ref.values())
    assert dict(h) == ref
    vals = [v for _, v in drain(h)]
    assert vals == sorted(ref.values())


def test_equal_values_all_returned():
    h = heapdict({"a": 1, "b": 1, "c": 1})
    out = drain(h)
    assert sorted(out) == [("a", 1), ("b", 1), ("c", 1)]


def test_non_numeric_comparable_values():
    h = heapdict({1: "pear", 2: "apple", 3: "zebra"})
    assert h.popitem() == (2, "apple")
