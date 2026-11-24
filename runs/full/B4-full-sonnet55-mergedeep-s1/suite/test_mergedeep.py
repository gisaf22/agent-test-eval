# tests/test_mergedeep.py
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
    d = {}
    merge(d, s)
    d["a"]["b"].append(2)
    assert s == {"a": {"b": [1]}}


def test_deepcopy_of_new_keys():
    s = {"a": {"x": 1}}
    d = {}
    merge(d, s)
    assert d["a"] is not s["a"]


def test_replace_default():
    d = {"a": 1, "n": {"x": 1, "y": 2}}
    merge(d, {"a": 2, "n": {"y": 3, "z": 4}})
    assert d == {"a": 2, "n": {"x": 1, "y": 3, "z": 4}}


def test_replace_lists():
    d = {"a": [1, 2]}
    merge(d, {"a": [3]})
    assert d == {"a": [3]}


def test_replace_mapping_with_scalar_and_back():
    d = {"a": {"x": 1}}
    merge(d, {"a": 5})
    assert d == {"a": 5}
    merge(d, {"a": {"y": 1}})
    assert d == {"a": {"y": 1}}


def test_multiple_sources_in_order():
    d = {}
    merge(d, {"a": 1}, {"a": 2, "b": 1}, {"b": 3})
    assert d == {"a": 2, "b": 3}


def test_replace_copy_is_deep():
    s = {"a": [1]}
    d = {"a": 0}
    merge(d, s)
    assert d["a"] is not s["a"]


def test_same_object_kept():
    shared = [1]
    d = {"a": shared}
    merge(d, {"a": shared}, strategy=Strategy.ADDITIVE)
    assert d["a"] == [1]


def test_counter_replace_merges_as_dict():
    d = {"c": Counter(a=1, b=2)}
    merge(d, {"c": Counter(a=5)})
    assert d["c"] == Counter(a=5, b=2)


def test_additive_list():
    d = {"a": [1]}
    merge(d, {"a": [2, 3]}, strategy=Strategy.ADDITIVE)
    assert d == {"a": [1, 2, 3]}


def test_additive_set():
    d = {"a": {1}}
    merge(d, {"a": {2}}, strategy=Strategy.ADDITIVE)
    assert d == {"a": {1, 2}}


def test_additive_tuple():
    d = {"a": (1,)}
    merge(d, {"a": (2,)}, strategy=Strategy.ADDITIVE)
    assert d == {"a": (1, 2)}


def test_additive_counter():
    d = {"a": Counter(x=1)}
    merge(d, {"a": Counter(x=2, y=1)}, strategy=Strategy.ADDITIVE)
    assert d["a"] == Counter(x=3, y=1)


def test_additive_nested():
    d = {"a": {"b": [1]}}
    merge(d, {"a": {"b": [2]}}, strategy=Strategy.ADDITIVE)
    assert d == {"a": {"b": [1, 2]}}


def test_additive_mismatched_types_replace():
    d = {"a": [1]}
    merge(d, {"a": (2,)}, strategy=Strategy.ADDITIVE)
    assert d == {"a": (2,)}


def test_additive_scalar_replace():
    d = {"a": 1}
    merge(d, {"a": 2}, strategy=Strategy.ADDITIVE)
    assert d == {"a": 2}


def test_additive_list_source_not_aliased():
    s = {"a": [[1]]}
    d = {"a": [[0]]}
    merge(d, s, strategy=Strategy.ADDITIVE)
    assert d["a"][1] is not s["a"][0]


@pytest.mark.parametrize("strategy", [Strategy.TYPESAFE, Strategy.TYPESAFE_REPLACE, Strategy.TYPESAFE_ADDITIVE])
def test_typesafe_raises_on_type_mismatch(strategy):
    with pytest.raises(TypeError):
        merge({"a": 1}, {"a": "x"}, strategy=strategy)


@pytest.mark.parametrize("strategy", [Strategy.TYPESAFE, Strategy.TYPESAFE_REPLACE])
def test_typesafe_replace_same_type(strategy):
    d = {"a": [1], "b": 1}
    merge(d, {"a": [2], "b": 2}, strategy=strategy)
    assert d == {"a": [2], "b": 2}


def test_typesafe_additive_same_type():
    d = {"a": [1], "b": {2}}
    merge(d, {"a": [2], "b": {3}}, strategy=Strategy.TYPESAFE_ADDITIVE)
    assert d == {"a": [1, 2], "b": {2, 3}}


def test_typesafe_error_message_has_key():
    with pytest.raises(TypeError, match="a"):
        merge({"a": 1}, {"a": []}, strategy=Strategy.TYPESAFE)


def test_typesafe_nested_mismatch():
    with pytest.raises(TypeError):
        merge({"a": {"b": 1}}, {"a": {"b": "s"}}, strategy=Strategy.TYPESAFE)


def test_typesafe_new_keys_ok():
    d = {"a": 1}
    merge(d, {"b": "x"}, strategy=Strategy.TYPESAFE)
    assert d == {"a": 1, "b": "x"}


def test_empty_source():
    d = {"a": 1}
    merge(d, {})
    assert d == {"a": 1}
