import copy
import json
import pickle

import pytest

from addict import Dict


def test_init_from_nested_dict_converts_children():
    d = Dict({"a": {"b": {"c": 1}}, "x": 2})
    assert type(d.a) is Dict and type(d.a.b) is Dict
    assert d.a.b.c == 1 and d.x == 2


def test_init_from_kwargs_and_mixed_args():
    d = Dict({"a": 1}, b={"c": 2})
    assert d == {"a": 1, "b": {"c": 2}}
    assert type(d.b) is Dict


def test_init_from_single_pair_tuple():
    assert Dict(("a", {"b": 1})) == {"a": {"b": 1}}
    assert type(Dict(("a", {"b": 1})).a) is Dict


def test_init_from_iterable_of_pairs():
    assert Dict([("a", 1), ("b", {"c": 2})]) == {"a": 1, "b": {"c": 2}}
    assert Dict((("a", 1), ("b", 2))) == {"a": 1, "b": 2}
    assert Dict(zip("ab", [1, 2])) == {"a": 1, "b": 2}


def test_falsy_positional_args_skipped():
    assert Dict({}, None, [], (), {"a": 1}) == {"a": 1}


def test_hook_converts_dicts_in_lists_and_tuples_preserving_type():
    d = Dict({"l": [{"a": 1}, 2, [{"b": 2}]], "t": ({"c": 3},)})
    assert type(d.l) is list and type(d.l[0]) is Dict and d.l[0].a == 1
    assert type(d.l[2][0]) is Dict
    assert type(d.t) is tuple and type(d.t[0]) is Dict


def test_attribute_and_item_access_are_equivalent():
    d = Dict()
    d.a = 1
    d["b"] = 2
    assert d["a"] == 1 and d.b == 2
    del d.a
    assert "a" not in d
    del d["b"]
    assert d == {}


def test_missing_key_returns_empty_dict_without_inserting():
    d = Dict()
    child = d.missing
    assert child == {} and type(child) is Dict
    assert "missing" not in d
    assert d["other"] == {} and "other" not in d


def test_deep_autovivification_on_assignment():
    d = Dict()
    d.a.b.c = 1
    assert d == {"a": {"b": {"c": 1}}}
    d.a.b.d = 2
    assert d.to_dict() == {"a": {"b": {"c": 1, "d": 2}}}


def test_parent_link_attached_once():
    d = Dict()
    child = d.x
    child.y = 1
    assert d.x is child
    child.z = 2
    assert d == {"x": {"y": 1, "z": 2}}


def test_delete_missing_raises():
    d = Dict()
    with pytest.raises(KeyError):
        del d.nope
    with pytest.raises(KeyError):
        del d["nope"]


def test_setting_class_attribute_name_is_read_only():
    d = Dict()
    with pytest.raises(AttributeError) as exc:
        d.keys = 1
    assert str(exc.value) == "'Dict' object attribute 'keys' is read-only"
    d["keys"] = 1  # item access still allowed
    assert d["keys"] == 1


def test_add_on_empty_returns_other_enabling_counters():
    d = Dict()
    assert Dict() + 5 == 5
    d.count += 1
    d.count += 1
    assert d.count == 2


def test_add_on_nonempty_raises():
    with pytest.raises(TypeError) as exc:
        Dict(a=1) + 1
    assert str(exc.value) == "unsupported operand type(s) for +: 'Dict' and 'int'"


def test_to_dict_recursive_plain_types():
    d = Dict({"a": {"b": 1}, "l": [{"c": 2}, 3], "t": ({"d": 4},)})
    out = d.to_dict()
    assert out == {"a": {"b": 1}, "l": [{"c": 2}, 3], "t": ({"d": 4},)}
    assert type(out) is dict and type(out["a"]) is dict
    assert type(out["l"]) is list and type(out["l"][0]) is dict
    assert type(out["t"]) is tuple and type(out["t"][0]) is dict
    json.dumps(out)


def test_copy_is_shallow():
    d = Dict({"a": {"b": 1}})
    c = d.copy()
    assert type(c) is Dict and c == d and c is not d
    c.a.b = 2
    assert d.a.b == 2


def test_deepcopy_is_independent():
    d = Dict({"a": {"b": [1]}})
    for c in (d.deepcopy(), copy.deepcopy(d)):
        assert type(c) is Dict and type(c.a) is Dict and c == d
        c.a.b.append(2)
        assert d.a.b == [1]


def test_deepcopy_handles_self_reference():
    d = Dict()
    d["me"] = d
    c = copy.deepcopy(d)
    assert c["me"] is c


def test_update_merges_recursively():
    d = Dict({"a": {"b": 1, "c": 2}, "x": 1})
    d.update({"a": {"c": 3, "d": 4}, "y": 2})
    assert d == {"a": {"b": 1, "c": 3, "d": 4}, "x": 1, "y": 2}


def test_update_non_dict_replaces_and_kwargs():
    d = Dict({"a": {"b": 1}, "n": 1})
    d.update({"a": 5}, n={"z": 1})
    assert d == {"a": 5, "n": {"z": 1}}


def test_update_dict_over_non_dict_replaces():
    d = Dict(a=1)
    d.update(a={"b": 2})
    assert d.a == {"b": 2}


def test_update_too_many_positional_args():
    with pytest.raises(TypeError):
        Dict().update({}, {})


def test_update_empty_is_noop():
    d = Dict(a=1)
    d.update()
    assert d == {"a": 1}


def test_pickle_roundtrip():
    d = Dict({"a": {"b": [1, {"c": 2}]}, "x": 1})
    r = pickle.loads(pickle.dumps(d))
    assert r == d and type(r) is Dict and type(r.a) is Dict


def test_or_operators():
    a = Dict({"x": {"y": 1}})
    b = {"x": {"z": 2}, "w": 3}
    r = a | b
    assert type(r) is Dict and r == {"x": {"y": 1, "z": 2}, "w": 3}
    assert a == {"x": {"y": 1}}
    r2 = b | a
    assert type(r2) is Dict and r2 == {"x": {"z": 2, "y": 1}, "w": 3}
    with pytest.raises(TypeError):
        a | 1
    with pytest.raises(TypeError):
        1 | a


def test_ior_in_place():
    a = Dict({"x": {"y": 1}})
    same = a
    a |= {"x": {"z": 2}}
    assert a is same and a == {"x": {"y": 1, "z": 2}}


def test_setdefault():
    d = Dict(a=1)
    assert d.setdefault("a", 9) == 1
    assert d.setdefault("b", 2) == 2 and d.b == 2
    assert d.setdefault("c") is None and "c" in d


def test_freeze_blocks_new_keys_and_missing_reads():
    d = Dict({"a": 1, "n": {"m": 1}})
    d.freeze()
    d.a = 2
    d.n.m = 3
    assert d == {"a": 2, "n": {"m": 3}}
    with pytest.raises(KeyError):
        d.new = 1
    with pytest.raises(KeyError):
        d["missing"]
    with pytest.raises(KeyError):
        d.n.missing
    with pytest.raises(KeyError):
        d.n.newkey = 1


def test_unfreeze_and_freeze_false():
    d = Dict({"n": {}})
    d.freeze()
    d.unfreeze()
    d.new = 1
    d.n.new = 2
    assert d == {"n": {"new": 2}, "new": 1}
    d.freeze()
    d.freeze(False)
    assert d.other == {}


def test_equality_with_plain_dict():
    assert Dict({"a": {"b": 1}}) == {"a": {"b": 1}}
    assert isinstance(Dict(), dict)
