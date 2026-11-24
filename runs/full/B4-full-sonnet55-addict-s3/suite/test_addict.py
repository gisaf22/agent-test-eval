# tests/test_addict.py
import copy
import pickle
import pytest
from addict import Dict


def test_empty():
    assert Dict() == {}


def test_init_falsy_args_skipped():
    assert Dict({}) == {}
    assert Dict(None, {}, (), [], a=1) == {'a': 1}
    assert Dict({}, {'a': 1}) == {'a': 1}


def test_init_multiple_args_merge():
    assert Dict({'a': 1}, {'b': 2}) == {'a': 1, 'b': 2}


def test_init_dict_and_kwargs():
    d = Dict({'a': 1}, b=2)
    assert d == {'a': 1, 'b': 2}
    assert d.a == 1 and d.b == 2


def test_init_tuple_pairs():
    assert Dict([('a', 1), ('b', 2)]) == {'a': 1, 'b': 2}


def test_init_single_tuple():
    assert Dict(('a', 1)) == {'a': 1}


def test_nested_auto_create():
    d = Dict()
    d.a.b.c = 5
    assert d == {'a': {'b': {'c': 5}}}
    assert isinstance(d.a.b, Dict)


def test_missing_read_does_not_persist():
    d = Dict()
    d.a.b
    assert 'a' not in d
    assert d == {}


def test_setitem_getitem():
    d = Dict()
    d['x']['y'] = 1
    assert d.x.y == 1


def test_hook_converts_nested():
    d = Dict({'a': [{'b': 1}], 'c': ({'d': 2},)})
    assert isinstance(d.a[0], Dict)
    assert d.a[0].b == 1
    assert isinstance(d.c, tuple)
    assert d.c[0].d == 2


def test_to_dict():
    d = Dict({'a': {'b': 1}, 'l': [{'c': 2}], 't': ({'e': 3},)})
    r = d.to_dict()
    assert r == {'a': {'b': 1}, 'l': [{'c': 2}], 't': ({'e': 3},)}
    assert type(r) is dict
    assert type(r['a']) is dict
    assert type(r['l'][0]) is dict
    assert type(r['t']) is tuple
    assert type(r['t'][0]) is dict


def test_delattr_and_delitem():
    d = Dict(a=1, b=2)
    del d.a
    del d['b']
    assert d == {}
    with pytest.raises(KeyError):
        del d.zzz


def test_readonly_attribute():
    d = Dict()
    with pytest.raises(AttributeError):
        d.keys = 1


def test_add():
    assert Dict() + {'a': 1} == {'a': 1}
    with pytest.raises(TypeError):
        Dict(a=1) + {'b': 1}


def test_update_recursive():
    d = Dict({'a': {'b': 1, 'c': 2}})
    d.update({'a': {'b': 9}, 'z': 1})
    assert d == {'a': {'b': 9, 'c': 2}, 'z': 1}


def test_update_kwargs_and_overwrite():
    d = Dict(a={'x': 1})
    d.update(a=5)
    assert d.a == 5
    d.update({'q': 1}, r=2)
    assert d.q == 1 and d.r == 2


def test_update_too_many_args():
    with pytest.raises(TypeError):
        Dict().update({}, {})


def test_or_operators():
    d = Dict(a=1)
    r = d | {'b': 2}
    assert r == {'a': 1, 'b': 2}
    assert isinstance(r, Dict)
    assert d == {'a': 1}
    r2 = {'b': 2} | d
    assert isinstance(r2, Dict)
    assert r2 == {'a': 1, 'b': 2}
    assert d.__or__(3) is NotImplemented
    assert d.__ror__(3) is NotImplemented
    with pytest.raises(TypeError):
        d | 3


def test_ior():
    d = Dict(a={'b': 1})
    d |= {'a': {'c': 2}}
    assert d == {'a': {'b': 1, 'c': 2}}


def test_setdefault():
    d = Dict(a=1)
    assert d.setdefault('a', 5) == 1
    assert d.setdefault('b', 7) == 7
    assert d.b == 7
    assert d.setdefault('c') is None
    assert 'c' in d


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
    c2 = copy.deepcopy(d)
    assert c2 == d and isinstance(c2, Dict)


def test_pickle_roundtrip():
    d = Dict(a={'b': 1}, c=[1, 2])
    r = pickle.loads(pickle.dumps(d))
    assert r == d
    assert isinstance(r, Dict)


def test_freeze():
    d = Dict(a={'b': 1})
    d.freeze()
    with pytest.raises(KeyError):
        d.new = 1
    with pytest.raises(KeyError):
        d.a.new = 1
    with pytest.raises(KeyError):
        d.missing
    d.a.b = 2
    assert d.a.b == 2


def test_unfreeze():
    d = Dict(a={'b': 1})
    d.freeze()
    d.unfreeze()
    d.new = 1
    d.a.c = 2
    assert d.new == 1 and d.a.c == 2


def test_freeze_false():
    d = Dict(a=1)
    d.freeze()
    d.freeze(False)
    d.b = 2
    assert d.b == 2


def test_subclass_hook():
    class Sub(Dict):
        pass
    s = Sub({'a': {'b': 1}})
    assert isinstance(s.a, Sub)
    assert type(s.to_dict()['a']) is dict


def test_keys_nonstring():
    d = Dict()
    d[1] = 'x'
    assert d[1] == 'x'


def test_parent_link_assignment_once():
    d = Dict()
    child = d.a
    child.x = 1
    assert d == {'a': {'x': 1}}
