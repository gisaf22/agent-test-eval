from collections import Counter, OrderedDict

import pytest

from mergedeep import Strategy, merge


def test_strategy_enum_values():
    assert [(s.name, s.value) for s in Strategy] == [
        ("REPLACE", 0), ("ADDITIVE", 1), ("TYPESAFE", 2),
        ("TYPESAFE_REPLACE", 3), ("TYPESAFE_ADDITIVE", 4),
    ]


def test_returns_destination_object_and_no_sources():
    dst = {"a": 1}
    assert merge(dst) is dst
    assert merge(dst, {"b": 2}) is dst
    assert dst == {"a": 1, "b": 2}


def test_nested_recursive_merge_default_replace():
    dst = {"a": {"b": 1, "c": {"d": 1}}, "l": [1]}
    src = {"a": {"c": {"e": 2}, "f": 3}, "l": [2]}
    merge(dst, src)
    assert dst == {"a": {"b": 1, "c": {"d": 1, "e": 2}, "f": 3}, "l": [2]}


def test_multiple_sources_applied_in_order():
    assert merge({}, {"a": 1}, {"a": 2, "b": 1}, {"a": 3}) == {"a": 3, "b": 1}


def test_new_keys_are_deep_copied():
    inner = {"x": [1]}
    dst = merge({}, {"k": inner})
    inner["x"].append(2)
    assert dst == {"k": {"x": [1]}}
    assert dst["k"] is not inner


def test_replaced_values_are_deep_copied():
    src_list = [1, [2]]
    dst = merge({"k": [0]}, {"k": src_list})
    src_list[1].append(3)
    assert dst == {"k": [1, [2]]}


def test_identical_object_kept():
    shared = [1, 2]
    dst = {"k": shared}
    merge(dst, {"k": shared})
    assert dst["k"] is shared
    merge(dst, {"k": shared}, strategy=Strategy.ADDITIVE)
    assert dst["k"] is shared and shared == [1, 2]


def test_mapping_replaced_by_non_mapping_and_vice_versa():
    assert merge({"a": {"b": 1}}, {"a": 5}) == {"a": 5}
    assert merge({"a": 5}, {"a": {"b": 1}}) == {"a": {"b": 1}}


def test_other_mapping_types_recurse():
    dst = {"a": OrderedDict(x=1)}
    merge(dst, {"a": {"y": 2}})
    assert dst["a"] == {"x": 1, "y": 2}
    assert isinstance(dst["a"], OrderedDict)


def test_replace_counter_merges_like_dict():
    dst = {"c": Counter(a=1, b=5)}
    merge(dst, {"c": Counter(a=2, z=1)})
    assert dst["c"] == Counter(a=2, b=5, z=1)
    assert isinstance(dst["c"], Counter)


def test_replace_counter_with_non_counter():
    assert merge({"c": Counter(a=1)}, {"c": {"a": 9}}) == {"c": {"a": 9}}


def test_top_level_counters_are_not_recursive():
    # both Counter -> _is_recursive_merge False -> handled by strategy
    dst = {"c": Counter(a=1)}
    merge(dst, {"c": Counter(a=1)}, strategy=Strategy.ADDITIVE)
    assert dst["c"] == Counter(a=2)


def test_additive_list_set_tuple_counter():
    dst = {"l": [1], "s": {1}, "t": (1,), "c": Counter(a=1)}
    src = {"l": [2, [3]], "s": {2}, "t": (2,), "c": Counter(a=2, b=1)}
    merge(dst, src, strategy=Strategy.ADDITIVE)
    assert dst == {"l": [1, 2, [3]], "s": {1, 2}, "t": (1, 2), "c": Counter(a=3, b=1)}
    src["l"][1].append(4)
    assert dst["l"] == [1, 2, [3]]


def test_additive_list_extends_in_place():
    lst = [1]
    dst = {"l": lst}
    merge(dst, {"l": [2]}, strategy=Strategy.ADDITIVE)
    assert dst["l"] is lst and lst == [1, 2]


def test_additive_mismatched_types_fall_back_to_replace():
    dst = {"a": [1], "b": (1,), "c": {1}, "d": 1, "e": "x"}
    merge(dst, {"a": (2,), "b": [2], "c": [2], "d": 2, "e": "y"}, strategy=Strategy.ADDITIVE)
    assert dst == {"a": (2,), "b": [2], "c": [2], "d": 2, "e": "y"}


def test_additive_nested():
    dst = {"x": {"l": [1]}}
    merge(dst, {"x": {"l": [2]}}, strategy=Strategy.ADDITIVE)
    assert dst == {"x": {"l": [1, 2]}}


@pytest.mark.parametrize("strategy", [Strategy.TYPESAFE, Strategy.TYPESAFE_REPLACE])
def test_typesafe_replace_same_type(strategy):
    dst = {"l": [1], "n": {"a": [1]}}
    merge(dst, {"l": [2], "n": {"a": [3]}}, strategy=strategy)
    assert dst == {"l": [2], "n": {"a": [3]}}


def test_typesafe_additive_same_type():
    dst = {"l": [1]}
    merge(dst, {"l": [2]}, strategy=Strategy.TYPESAFE_ADDITIVE)
    assert dst == {"l": [1, 2]}


@pytest.mark.parametrize("strategy", [Strategy.TYPESAFE, Strategy.TYPESAFE_REPLACE, Strategy.TYPESAFE_ADDITIVE])
def test_typesafe_type_mismatch_raises(strategy):
    with pytest.raises(TypeError) as exc:
        merge({"k": [1]}, {"k": (1,)}, strategy=strategy)
    assert str(exc.value) == (
        "destination type: <class 'list'> differs from source type: <class 'tuple'> for key: \"k\""
    )


def test_typesafe_subclass_counts_as_mismatch():
    with pytest.raises(TypeError):
        merge({"k": 1}, {"k": True}, strategy=Strategy.TYPESAFE)


def test_typesafe_new_keys_allowed():
    assert merge({"a": 1}, {"b": "x"}, strategy=Strategy.TYPESAFE) == {"a": 1, "b": "x"}


def test_sources_not_mutated():
    src = {"a": {"b": [1]}}
    merge({"a": {"b": [0]}}, src, strategy=Strategy.ADDITIVE)
    assert src == {"a": {"b": [1]}}
