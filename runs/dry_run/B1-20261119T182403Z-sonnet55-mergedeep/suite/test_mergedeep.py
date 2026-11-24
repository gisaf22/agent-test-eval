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
    orig = copy.deepcopy(s)
    merge({}, s)
    assert s == orig


def test_new_keys_deepcopied():
    s = {"a": {"b": [1]}}
    d = merge({}, s)
    d["a"]["b"].append(2)
    assert s["a"]["b"] == [1]


def test_replace_default():
    d = merge({"a": 1, "b": {"c": 1}}, {"a": 2, "b": {"d": 2}})
    assert d == {"a": 2, "b": {"c": 1, "d": 2}}


def test_replace_scalar_with_dict_and_back():
    assert merge({"a": 1}, {"a": {"x": 1}}) == {"a": {"x": 1}}
    assert merge({"a": {"x": 1}}, {"a": 1}) == {"a": 1}


def test_replace_list():
    assert merge({"a": [1]}, {"a": [2]}) == {"a": [2]}


def test_replace_copies_value():
    s = {"a": [1]}
    d = merge({"a": 0}, s)
    d["a"].append(2)
    assert s["a"] == [1]


def test_multiple_sources_order():
    d = merge({}, {"a": 1}, {"a": 2, "b": 1}, {"b": 3})
    assert d == {"a": 2, "b": 3}


def test_same_object_kept():
    shared = [1]
    d = {"a": shared}
    merge(d, {"a": shared}, strategy=Strategy.ADDITIVE)
    assert d["a"] == [1]


def test_replace_counter_merges_as_dict():
    d = merge({"a": Counter(x=1, y=1)}, {"a": Counter(x=5)})
    assert d["a"] == Counter(x=5, y=1)


def test_additive_list():
    assert merge({"a": [1]}, {"a": [2, 3]}, strategy=Strategy.ADDITIVE) == {"a": [1, 2, 3]}


def test_additive_set():
    assert merge({"a": {1}}, {"a": {2}}, strategy=Strategy.ADDITIVE) == {"a": {1, 2}}


def test_additive_tuple():
    assert merge({"a": (1,)}, {"a": (2,)}, strategy=Strategy.ADDITIVE) == {"a": (1, 2)}


def test_additive_counter_sums():
    d = merge({"a": Counter(x=1)}, {"a": Counter(x=2, y=1)}, strategy=Strategy.ADDITIVE)
    assert d["a"] == Counter(x=3, y=1)


def test_additive_nested():
    d = merge({"a": {"b": [1]}}, {"a": {"b": [2]}}, strategy=Strategy.ADDITIVE)
    assert d == {"a": {"b": [1, 2]}}


def test_additive_mismatch_falls_back_to_replace():
    assert merge({"a": [1]}, {"a": (2,)}, strategy=Strategy.ADDITIVE) == {"a": (2,)}
    assert merge({"a": 1}, {"a": 2}, strategy=Strategy.ADDITIVE) == {"a": 2}


def test_additive_does_not_alias_source():
    s = {"a": [[1]]}
    d = merge({"a": []}, s, strategy=Strategy.ADDITIVE)
    d["a"][0].append(9)
    assert s == {"a": [[1]]}


@pytest.mark.parametrize("strategy", [Strategy.TYPESAFE, Strategy.TYPESAFE_REPLACE, Strategy.TYPESAFE_ADDITIVE])
def test_typesafe_raises_on_type_mismatch(strategy):
    with pytest.raises(TypeError):
        merge({"a": 1}, {"a": "x"}, strategy=strategy)


def test_typesafe_error_message_mentions_key():
    with pytest.raises(TypeError, match="a"):
        merge({"a": [1]}, {"a": (1,)}, strategy=Strategy.TYPESAFE)


@pytest.mark.parametrize("strategy", [Strategy.TYPESAFE, Strategy.TYPESAFE_REPLACE])
def test_typesafe_replace_same_type(strategy):
    assert merge({"a": [1]}, {"a": [2]}, strategy=strategy) == {"a": [2]}


def test_typesafe_additive_same_type():
    d = merge({"a": [1], "b": 1}, {"a": [2], "b": 2}, strategy=Strategy.TYPESAFE_ADDITIVE)
    assert d == {"a": [1, 2], "b": 2}


def test_typesafe_nested_mismatch():
    with pytest.raises(TypeError):
        merge({"a": {"b": 1}}, {"a": {"b": "x"}}, strategy=Strategy.TYPESAFE)


def test_typesafe_dict_vs_scalar_raises():
    with pytest.raises(TypeError):
        merge({"a": {"b": 1}}, {"a": 1}, strategy=Strategy.TYPESAFE)


def test_typesafe_new_key_ok():
    assert merge({"a": 1}, {"b": "x"}, strategy=Strategy.TYPESAFE) == {"a": 1, "b": "x"}


def test_empty_sources():
    assert merge({}, {}, {}) == {}
