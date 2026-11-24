# tests/test_addict.py
import copy
import json
import pickle

import pytest

from addict import Dict


def test_empty():
    assert Dict() == {}


def test_init_from_dict_and_kwargs():
    d = Dict({'a': 1}, b=2)
    assert d == {'a': 1, 'b': 2}
    assert d.a == 1 and d.b == 2


def test_init_from_tuple_pairs_and_iterable():
    assert Dict([('a', 1), ('b', 2)]) == {'a': 1, 'b': 2}
    assert Dict(('a', 1)) == {'a': 1}


def test_init_falsy_args_skipped():
    assert Dict(None) == {}
    assert Dict({}) == {}
    assert Dict([]) == {}
    assert Dict(None, {'a': 1}, ()) == {'a': 1}


def test_nested_dicts_converted():
    d = Dict({'a': {'b': {'c': 1}}})
    assert isinstance(d.a, Dict)
    assert d.a.b.c == 1


def test_lists_and_tuples_hooked():
    d = Dict({'a': [{'x': 1}], 't': ({'y': 2},)})
    assert isinstance(d.a[0], Dict)
    assert d.a[0].x == 1
    assert isinstance(d.t, tuple)
    assert d.t[0].y == 2


def test_autovivification():
    d = Dict()
    d.a.b.c = 5
    assert d == {'a': {'b': {'c': 5}}}


def test_missing_read_does_not_create_key():
    d = Dict()
    _ = d.a.b
    assert 'a' not in d
    assert d == {}


def test_setitem_getitem_attr_equivalence():
    d = Dict()
    d['x'] = 1
    assert d.x == 1
    d.y = 2
    assert d['y'] == 2


def test_readonly_attribute():
    d = Dict()
    with pytest.raises(AttributeError):
        d.keys = 1
    with pytest.raises(AttributeError):
        d.update = 1


def test_delattr_and_delitem():
    d = Dict(a=1, b=2)
    del d.a
    del d['b']
    assert d == {}
    with pytest.raises(KeyError):
        del d.zzz


def test_add_empty():
    assert Dict() + {'a': 1} == {'a': 1}
    with pytest.raises(TypeError):
        Dict(a=1) + {'b': 1}


def test_to_dict():
    d = Dict({'a': {'b': 1}, 'l': [{'c': 2}], 't': ({'e': 3},)})
    r = d.to_dict()
    assert r == {'a': {'b': 1}, 'l': [{'c': 2}], 't': ({'e': 3},)}
    assert type(r) is dict
    assert type(r['a']) is dict
    assert type(r['l'][0]) is dict
    assert type(r['t'][0]) is dict
    assert isinstance(r['t'], tuple)


def test_json_roundtrip():
    d = Dict(a={'b': [1, 2]})
    assert json.loads(json.dumps(d)) == {'a': {'b': [1, 2]}}


def test_copy_shallow():
    d = Dict(a={'b': 1})
    c = d.copy()
    assert c == d
    assert c.a is d.a
    c.x = 1
    assert 'x' not in d


def test_deepcopy():
    d = Dict(a={'b': [1, 2]})
    c = d.deepcopy()
    assert c == d
    assert c.a is not d.a
    c.a.b.append(3)
    assert d.a.b == [1, 2]
    assert isinstance(c, Dict)
    c2 = copy.deepcopy(d)
    assert c2 == d and c2.a is not d.a


def test_update_merges_nested():
    d = Dict(a={'b': 1, 'c': 2})
    d.update({'a': {'b': 9, 'd': 4}})
    assert d == {'a': {'b': 9, 'c': 2, 'd': 4}}


def test_update_kwargs_and_replace():
    d = Dict(a=1)
    d.update(a={'x': 1}, b=2)
    assert d == {'a': {'x': 1}, 'b': 2}
    d.update({'a': 5})
    assert d.a == 5


def test_update_too_many_args():
    with pytest.raises(TypeError):
        Dict().update({}, {})


def test_or_operators():
    d = Dict(a={'x': 1})
    r = d | {'a': {'y': 2}, 'b': 3}
    assert r == {'a': {'x': 1, 'y': 2}, 'b': 3}
    assert d == {'a': {'x': 1}}
    r2 = {'q': 1} | Dict(z=2)
    assert r2 == {'q': 1, 'z': 2}
    assert isinstance(r2, Dict)
    with pytest.raises(TypeError):
        d | 5


def test_ror_not_implemented():
    with pytest.raises(TypeError):
        5 | Dict(a=1)
    assert Dict().__ror__(5) is NotImplemented
    assert Dict().__or__(5) is NotImplemented


def test_ior():
    d = Dict(a=1)
    d |= {'b': 2}
    assert d == {'a': 1, 'b': 2}
    assert isinstance(d, Dict)


def test_setdefault():
    d = Dict(a=1)
    assert d.setdefault('a', 5) == 1
    assert d.setdefault('b', 5) == 5
    assert d.b == 5
    assert d.setdefault('c') is None
    assert 'c' in d


def test_freeze():
    d = Dict(a={'b': 1})
    d.freeze()
    d.a.b = 2
    assert d.a.b == 2
    with pytest.raises(KeyError):
        d.new = 1
    with pytest.raises(KeyError):
        d.a.new = 1
    with pytest.raises(KeyError):
        _ = d.missing


def test_unfreeze():
    d = Dict(a={'b': 1})
    d.freeze()
    d.unfreeze()
    d.new = 1
    d.a.c = 2
    assert d.new == 1 and d.a.c == 2


def test_pickle_roundtrip():
    d = Dict(a={'b': 1}, c=[1, 2])
    r = pickle.loads(pickle.dumps(d))
    assert r == d
    assert isinstance(r, Dict)
    assert isinstance(r.a, Dict)


def test_parent_not_attached_when_unset():
    d = Dict()
    child = d.a
    assert 'a' not in d
    child.x = 1
    assert d == {'a': {'x': 1}}


def test_keys_nonstring():
    d = Dict()
    d[1] = 'x'
    assert d[1] == 'x'
