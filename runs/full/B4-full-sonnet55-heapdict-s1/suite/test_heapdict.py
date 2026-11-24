# tests/test_heapdict.py
import random
import pytest
from heapdict import heapdict


def check_invariant(h):
    for i, w in enumerate(h.heap):
        assert w[2] == i
        assert h.d[w[1]] is w
        for c in (2 * i + 1, 2 * i + 2):
            if c < len(h.heap):
                assert not (h.heap[c][0] < w[0])
    assert len(h.heap) == len(h.d)


def test_empty():
    h = heapdict()
    assert len(h) == 0
    assert list(h) == []
    with pytest.raises((KeyError, IndexError)):
        h.popitem()
    with pytest.raises((KeyError, IndexError)):
        h.peekitem()


def test_init_forms():
    assert dict(heapdict({'a': 2, 'b': 1})) == {'a': 2, 'b': 1}
    assert dict(heapdict([('a', 2), ('b', 1)])) == {'a': 2, 'b': 1}
    h = heapdict(a=3, b=1)
    assert h['a'] == 3 and h.peekitem() == ('b', 1)


def test_setget_and_missing():
    h = heapdict()
    h['x'] = 5
    assert h['x'] == 5
    assert 'x' in h
    with pytest.raises(KeyError):
        h['nope']


def test_popitem_order():
    h = heapdict({'a': 5, 'b': 2, 'c': 9, 'd': 1, 'e': 7})
    out = []
    while h:
        check_invariant(h)
        out.append(h.popitem())
    assert out == [('d', 1), ('b', 2), ('a', 5), ('e', 7), ('c', 9)]


def test_peekitem_does_not_remove():
    h = heapdict({'a': 3, 'b': 1})
    assert h.peekitem() == ('b', 1)
    assert len(h) == 2
    assert h.peekitem() == ('b', 1)


def test_update_value_changes_priority():
    h = heapdict({'a': 1, 'b': 2, 'c': 3})
    h['a'] = 10
    assert len(h) == 3
    assert h.peekitem() == ('b', 2)
    h['c'] = 0
    assert h.peekitem() == ('c', 0)
    check_invariant(h)
    assert [h.popitem()[0] for _ in range(3)] == ['c', 'b', 'a']


def test_delitem():
    h = heapdict({k: v for k, v in zip('abcdefg', [4, 1, 6, 3, 7, 2, 5])})
    del h['e']
    check_invariant(h)
    assert 'e' not in h
    del h['b']
    check_invariant(h)
    assert len(h) == 5
    assert h.popitem() == ('f', 2)
    with pytest.raises(KeyError):
        del h['zzz']


def test_delete_only_item():
    h = heapdict({'a': 1})
    del h['a']
    assert len(h) == 0
    assert h.heap == []


def test_pop_and_default():
    h = heapdict({'a': 1, 'b': 2})
    assert h.pop('a') == 1
    assert h.pop('zz', 42) == 42
    assert list(h) == ['b']
    with pytest.raises(KeyError):
        h.pop('zz')


def test_clear():
    h = heapdict({'a': 1, 'b': 2})
    h.clear()
    assert len(h) == 0 and h.heap == [] and h.d == {}
    h['q'] = 1
    assert h.popitem() == ('q', 1)


def test_iteration_and_mapping_api():
    h = heapdict({'a': 3, 'b': 1, 'c': 2})
    assert set(h) == {'a', 'b', 'c'}
    assert set(h.keys()) == {'a', 'b', 'c'}
    assert sorted(h.values()) == [1, 2, 3]
    assert dict(h.items()) == {'a': 3, 'b': 1, 'c': 2}
    assert h.get('zz') is None
    assert h.setdefault('d', 0) == 0
    assert h.peekitem() == ('d', 0)


def test_duplicate_values():
    h = heapdict({i: 1 for i in range(10)})
    check_invariant(h)
    keys = set()
    while h:
        k, v = h.popitem()
        assert v == 1
        keys.add(k)
    assert keys == set(range(10))


def test_random_against_reference():
    rnd = random.Random(1234)
    h = heapdict()
    ref = {}
    for _ in range(1000):
        op = rnd.random()
        if op < 0.5:
            k = rnd.randrange(50)
            v = rnd.randrange(1000)
            h[k] = v
            ref[k] = v
        elif op < 0.7 and ref:
            k = rnd.choice(sorted(ref))
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


def test_docstrings_present():
    assert heapdict.popitem.__doc__
    assert heapdict.peekitem.__doc__
    assert heapdict.__len__.__doc__ == dict.__len__.__doc__
