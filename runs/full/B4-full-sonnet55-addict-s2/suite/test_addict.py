# tests/test_addict.py
import copy
import json
import pickle

import pytest

from addict import Dict


def test_empty():
    assert Dict() == {}


def test_init_variants():
    assert Dict({"a": 1}) == {"a": 1}
    assert Dict(a=1, b=2) == {"a": 1, "b": 2}
    assert Dict([("a", 1), ("b", 2)]) == {"a": 1, "b": 2}
    assert Dict(("a", 1)) == {"a": 1}
    assert Dict({"a": 1}, b=2) == {"a": 1, "b": 2}
    assert Dict(None) == {}


def test_init_nested_conversion():
    d = Dict({"a": {"b": 1}, "l": [{"c": 2}], "t": ({"d": 3},)})
    assert isinstance(d.a, Dict)
    assert isinstance(d.l[0], Dict)
    assert isinstance(d.t, tuple)
    assert isinstance(d.t[0], Dict)
    assert d.a.b == 1


def test_attr_set_get():
    d = Dict()
    d.a = 1
    assert d["a"] == 1
    assert d.a == 1


def test_auto_create_nested():
    d = Dict()
    d.a.b.c = 5
    assert d == {"a": {"b": {"c": 5}}}


def test_missing_read_does_not_persist():
    d = Dict()
    _ = d.a.b
    assert d == {}
    assert "a" not in d


def test_item_nested_creation():
    d = Dict()
    d["x"]["y"] = 1
    assert d.x.y == 1


def test_readonly_attribute():
    d = Dict()
    with pytest.raises(AttributeError):
        d.keys = 1
    with pytest.raises(AttributeError):
        d.update = 1


def test_delattr_and_delitem():
    d = Dict(a=1, b=2)
    del d.a
    assert d == {"b": 2}
    del d["b"]
    assert d == {}
    with pytest.raises(KeyError):
        del d.zzz


def test_add():
    assert Dict() + {"a": 1} == {"a": 1}
    with pytest.raises(TypeError):
        Dict(a=1) + {"b": 2}


def test_to_dict():
    d = Dict({"a": {"b": 1}, "l": [{"c": 2}], "t": ({"d": 3},)})
    r = d.to_dict()
    assert r == {"a": {"b": 1}, "l": [{"c": 2}], "t": ({"d": 3},)}
    assert type(r) is dict
    assert type(r["a"]) is dict
    assert type(r["l"][0]) is dict
    assert type(r["t"]) is tuple
    assert type(r["t"][0]) is dict


def test_json_roundtrip():
    d = Dict(a={"b": [1, 2]})
    assert json.loads(json.dumps(d)) == {"a": {"b": [1, 2]}}


def test_copy_shallow():
    d = Dict(a={"b": 1})
    c = d.copy()
    assert c == d
    assert c.a is d.a
    c.x = 1
    assert "x" not in d


def test_deepcopy():
    d = Dict(a={"b": [1, 2]})
    c = d.deepcopy()
    assert c == d
    assert c.a is not d.a
    c.a.b.append(3)
    assert d.a.b == [1, 2]
    assert isinstance(c, Dict)
    c2 = copy.deepcopy(d)
    assert c2 == d and c2.a is not d.a


def test_update_merge():
    d = Dict(a={"b": 1, "c": 2}, x=1)
    d.update({"a": {"b": 9, "d": 4}, "y": 2})
    assert d == {"a": {"b": 9, "c": 2, "d": 4}, "x": 1, "y": 2}


def test_update_kwargs_and_replace():
    d = Dict(a={"b": 1})
    d.update(a=5)
    assert d.a == 5
    d.update({"n": 1}, m=2)
    assert d.n == 1 and d.m == 2


def test_update_too_many_args():
    with pytest.raises(TypeError):
        Dict().update({}, {})


def test_update_dict_over_nondict():
    d = Dict(a=1)
    d.update({"a": {"b": 2}})
    assert d.a == {"b": 2}
    assert d["a"]["b"] == 2


def test_pickle_roundtrip():
    d = Dict(a={"b": 1}, l=[1, 2])
    r = pickle.loads(pickle.dumps(d))
    assert r == d
    assert isinstance(r, Dict)
    assert isinstance(r.a, Dict)


def test_or():
    a = Dict(a={"x": 1})
    b = {"a": {"y": 2}, "c": 3}
    r = a | b
    assert r == {"a": {"x": 1, "y": 2}, "c": 3}
    assert isinstance(r, Dict)
    assert a == {"a": {"x": 1}}


def test_ror():
    r = {"a": 1, "b": 2} | Dict(b=3)
    assert r == {"a": 1, "b": 3}
    assert isinstance(r, Dict)


def test_or_not_implemented():
    with pytest.raises(TypeError):
        Dict() | 5
    assert Dict().__or__(5) is NotImplemented
    assert Dict().__ror__(5) is NotImplemented


def test_ior():
    d = Dict(a=1)
    d |= {"b": 2}
    assert d == {"a": 1, "b": 2}
    assert isinstance(d, Dict)


def test_setdefault():
    d = Dict(a=1)
    assert d.setdefault("a", 5) == 1
    assert d.setdefault("b", 7) == 7
    assert d.b == 7
    assert d.setdefault("c") is None
    assert "c" in d


def test_freeze():
    d = Dict(a={"b": 1})
    d.freeze()
    d.a.b = 2
    assert d.a.b == 2
    with pytest.raises(KeyError):
        d.new = 1
    with pytest.raises(KeyError):
        d.a.new = 1
    with pytest.raises(KeyError):
        _ = d.missing
    with pytest.raises(KeyError):
        _ = d["missing"]


def test_unfreeze():
    d = Dict(a={"b": 1})
    d.freeze()
    d.unfreeze()
    d.new = 1
    d.a.c = 2
    assert d == {"a": {"b": 1, "c": 2}, "new": 1}


def test_freeze_false():
    d = Dict(a=1)
    d.freeze()
    d.freeze(False)
    d.b = 2
    assert d.b == 2


def test_keys_with_non_identifier():
    d = Dict()
    d["a b"] = 1
    d[1] = 2
    assert d["a b"] == 1 and d[1] == 2


def test_hook_in_list_assignment_not_converted():
    d = Dict()
    d.l = [{"a": 1}]
    assert type(d.l[0]) is dict


def test_dict_subclass_isinstance():
    assert isinstance(Dict(), dict)
