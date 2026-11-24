import random

import pytest

from heapdict import heapdict


def check_invariants(h):
    heap = h.heap
    assert len(heap) == len(h.d) == len(h)
    for i, w in enumerate(heap):
        assert w[2] == i, "stored position must match index"
        assert h.d[w[1]] is w
        for c in (2 * i + 1, 2 * i + 2):
            if c < len(heap):
                assert heap[i][0] <= heap[c][0], "heap property violated"


def drain(h):
    out = []
    while len(h):
        out.append(h.popitem())
        check_invariants(h)
    return out


def test_empty():
    h = heapdict()
    assert len(h) == 0
    assert list(h) == []
    with pytest.raises(IndexError):
        h.popitem()
    with pytest.raises(IndexError):
        h.peekitem()
    with pytest.raises(KeyError):
        h["missing"]
    with pytest.raises(KeyError):
        del h["missing"]


def test_constructor_from_mapping_and_kwargs():
    h = heapdict({"a": 3, "b": 1}, c=2)
    assert dict(h.items()) == {"a": 3, "b": 1, "c": 2}
    check_invariants(h)
    assert h.peekitem() == ("b", 1)


def test_pop_order_ascending():
    h = heapdict()
    for k, v in [("e", 5), ("b", 2), ("d", 4), ("a", 1), ("c", 3), ("f", 6), ("g", 0)]:
        h[k] = v
        check_invariants(h)
    assert drain(h) == [("g", 0), ("a", 1), ("b", 2), ("c", 3), ("d", 4), ("e", 5), ("f", 6)]


def test_single_item_popitem():
    h = heapdict(x=7)
    assert h.popitem() == ("x", 7)
    assert len(h) == 0 and h.heap == [] and h.d == {}


def test_peek_does_not_remove():
    h = heapdict(a=2, b=1)
    assert h.peekitem() == ("b", 1)
    assert h.peekitem() == ("b", 1)
    assert len(h) == 2


def test_update_priority_decrease_and_increase():
    h = heapdict(a=5, b=3, c=4)
    h["a"] = 1
    check_invariants(h)
    assert h.peekitem() == ("a", 1)
    h["a"] = 10
    check_invariants(h)
    assert h["a"] == 10
    assert len(h) == 3
    assert drain(h) == [("b", 3), ("c", 4), ("a", 10)]


def test_delete_arbitrary_keys():
    h = heapdict({k: v for v, k in enumerate("abcdefghij")})
    del h["e"]
    check_invariants(h)
    del h["a"]
    check_invariants(h)
    del h["j"]
    check_invariants(h)
    assert "e" not in h and "a" not in h
    assert [k for k, _ in drain(h)] == list("bcdfghi")


def test_equal_priorities():
    h = heapdict(a=1, b=1, c=1)
    out = drain(h)
    assert sorted(out) == [("a", 1), ("b", 1), ("c", 1)]


def test_iteration_and_contains():
    h = heapdict(a=3, b=1, c=2)
    assert set(iter(h)) == {"a", "b", "c"}
    assert "a" in h and "z" not in h
    assert h.get("z", "dflt") == "dflt"


def test_clear():
    h = heapdict(a=1, b=2)
    h.clear()
    assert len(h) == 0 and h.heap == [] and h.d == {}
    h["c"] = 3
    assert h.popitem() == ("c", 3)


def test_mutable_mapping_methods():
    h = heapdict(a=3, b=1)
    assert h.pop("a") == 3
    assert h.setdefault("z", 9) == 9
    check_invariants(h)
    assert drain(h) == [("b", 1), ("z", 9)]


def test_docstrings_copied():
    assert heapdict.clear.__doc__ == dict.clear.__doc__
    assert heapdict.__getitem__.__doc__ == dict.__getitem__.__doc__
    assert heapdict.__len__.__doc__ == dict.__len__.__doc__
    assert "lowest" in heapdict.popitem.__doc__


def test_randomised_against_reference_model():
    rng = random.Random(1234)
    h, ref = heapdict(), {}
    for _ in range(2000):
        op = rng.random()
        if op < 0.5 or not ref:
            k, v = rng.randrange(60), rng.randrange(100)
            h[k] = v
            ref[k] = v
        elif op < 0.7:
            k = rng.choice(list(ref))
            del h[k]
            del ref[k]
        elif op < 0.9:
            k, v = h.popitem()
            assert v == min(ref.values())
            assert ref.pop(k) == v
        else:
            k, v = h.peekitem()
            assert ref[k] == v == min(ref.values())
        check_invariants(h)
        assert dict(h.items()) == ref
