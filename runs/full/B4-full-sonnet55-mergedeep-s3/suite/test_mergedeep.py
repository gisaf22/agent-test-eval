# tests/test_mergedeep.py
import copy
from collections import Counter

import pytest

from mergedeep import merge, Strategy


def test_no_sources_returns_destination():
    d = {"a": 1}
    assert merge(d) is d
    assert d == {"a": 1}


def test_returns_destination_and_mutates():
    d = {"a": 1}
    r = merge(d, {"b": 2})
    assert r is d
    assert d == {"a": 1, "b": 2}


def test_source_not_mutated():
    s = {"a": {"b": [1]}}
    snapshot = copy.deepcopy(s)
    merge({}, s)
    assert s == snapshot


def test_new_keys_deepcopied():
    s = {"a": {"b": [1]}}
    d = merge({}, s)
    assert d["a"] is not s["a"]
    d["a"]["b"].append(2)
    assert s["a"]["b"] == [1]


def test_replace_default():
    d = merge({"a": 1, "b": {"c": 1}}, {"a": 2, "b": {"d": 2}})
    assert d == {"a": 2, "b": {"c": 1, "d": 2}}


def test_replace_different_types():
    assert merge({"a": {"x": 1}}, {"a": 5}) == {"a": 5}
    assert merge({"a": 5}, {"a": {"x": 1}}) == {"a": {"x": 1}}


def test_replace_list_and_copy():
    s = {"a": [1, 2]}
    d = merge({"a": [3]}, s)
    assert d["a"] == [1, 2]
    assert d["a"] is not s["a"]


def test_multiple_sources_order():
    d = merge({}, {"a": 1}, {"a": 2, "b": 1}, {"b": 3})
    assert d == {"a": 2, "b": 3}


def test_same_object_kept():
    shared = [1]
    d = {"a": shared}
    merge(d, {"a": shared}, strategy=Strategy.ADDITIVE)
    assert d["a"] == [1]


def test_replace_counter_merges_as_dict():
    d = merge({"a": Counter(x=1, y=2)}, {"a": Counter(x=5, z=1)})
    assert d["a"] == Counter(x=5, y=2, z=1)


def test_additive_list():
    assert merge({"a": [1]}, {"a": [2, 3]}, strategy=Strategy.ADDITIVE) == {"a": [1, 2, 3]}


def test_additive_set():
    assert merge({"a": {1}}, {"a": {2}}, strategy=Strategy.ADDITIVE) == {"a": {1, 2}}


def test_additive_tuple():
    assert merge({"a": (1,)}, {"a": (2,)}, strategy=Strategy.ADDITIVE) == {"a": (1, 2)}


def test_additive_counter():
    d = merge({"a": Counter(x=1)}, {"a": Counter(x=2, y=1)}, strategy=Strategy.ADDITIVE)
    assert d["a"] == Counter(x=3, y=1)


def test_additive_fallback_replace():
    assert merge({"a": 1}, {"a": 2}, strategy=Strategy.ADDITIVE) == {"a": 2}
    assert merge({"a": [1]}, {"a": (2,)}, strategy=Strategy.ADDITIVE) == {"a": (2,)}


def test_additive_nested():
    d = merge({"a": {"b": [1]}}, {"a": {"b": [2]}}, strategy=Strategy.ADDITIVE)
    assert d == {"a": {"b": [1, 2]}}


def test_additive_list_copies_items():
    inner = {"k": 1}
    d = merge({"a": []}, {"a": [inner]}, strategy=Strategy.ADDITIVE)
    assert d["a"][0] == inner and d["a"][0] is not inner


@pytest.mark.parametrize("strategy", [Strategy.TYPESAFE, Strategy.TYPESAFE_REPLACE, Strategy.TYPESAFE_ADDITIVE])
def test_typesafe_raises(strategy):
    with pytest.raises(TypeError):
        merge({"a": 1}, {"a": "x"}, strategy=strategy)


def test_typesafe_list_vs_tuple_raises():
    with pytest.raises(TypeError):
        merge({"a": [1]}, {"a": (1,)}, strategy=Strategy.TYPESAFE)


def test_typesafe_replace_same_type():
    assert merge({"a": [1]}, {"a": [2]}, strategy=Strategy.TYPESAFE) == {"a": [2]}
    assert merge({"a": 1}, {"a": 2}, strategy=Strategy.TYPESAFE_REPLACE) == {"a": 2}


def test_typesafe_additive_same_type():
    d = merge({"a": [1], "b": 1}, {"a": [2], "b": 2}, strategy=Strategy.TYPESAFE_ADDITIVE)
    assert d == {"a": [1, 2], "b": 2}


def test_typesafe_error_message_has_key():
    with pytest.raises(TypeError, match="foo"):
        merge({"foo": 1}, {"foo": "x"}, strategy=Strategy.TYPESAFE)


def test_typesafe_nested_raises():
    with pytest.raises(TypeError):
        merge({"a": {"b": 1}}, {"a": {"b": "s"}}, strategy=Strategy.TYPESAFE)


def test_typesafe_dict_vs_nondict_raises_not():
    # dict vs int is handled by the type check
    with pytest.raises(TypeError):
        merge({"a": {}}, {"a": 1}, strategy=Strategy.TYPESAFE)
