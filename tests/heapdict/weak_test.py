from heapdict import heapdict


def test_set_and_get():
    h = heapdict()
    h["a"] = 1
    assert h["a"] == 1


def test_popitem_returns_something():
    h = heapdict({"a": 2, "b": 1})
    assert h.popitem() is not None
