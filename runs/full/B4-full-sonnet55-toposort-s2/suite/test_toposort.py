# tests/test_toposort.py
import pytest

from toposort import toposort, toposort_flatten, CircularDependencyError


def test_empty_input():
    assert list(toposort({})) == []
    assert toposort_flatten({}) == []


def test_simple_chain():
    data = {2: {1}, 3: {2}}
    assert list(toposort(data)) == [{1}, {2}, {3}]


def test_levels_and_extra_items():
    data = {
        2: {11},
        9: {11, 8, 10},
        10: {11, 3},
        11: {7, 5},
        8: {7, 3},
    }
    assert list(toposort(data)) == [
        {3, 5, 7},
        {8, 11},
        {2, 10},
        {9},
    ]


def test_dependency_only_items_included():
    assert list(toposort({"a": {"b"}})) == [{"b"}, {"a"}]


def test_items_with_empty_deps():
    assert list(toposort({"a": set(), "b": set()})) == [{"a", "b"}]


def test_self_dependency_ignored():
    assert list(toposort({1: {1}, 2: {1, 2}})) == [{1}, {2}]


def test_input_not_modified():
    data = {2: {1, 2}, 3: {2}}
    copy = {k: set(v) for k, v in data.items()}
    list(toposort(data))
    toposort_flatten(data)
    assert data == copy


def test_circular_raises():
    with pytest.raises(CircularDependencyError):
        list(toposort({1: {2}, 2: {1}}))


def test_circular_error_data_and_type():
    data = {1: {2}, 2: {1}, 3: {1}, 0: set()}
    with pytest.raises(CircularDependencyError) as ei:
        list(toposort(data))
    err = ei.value
    assert isinstance(err, ValueError)
    assert err.data == {1: {2}, 2: {1}, 3: {1}}
    assert "Circular dependencies" in str(err)


def test_circular_yields_earlier_levels_first():
    gen = toposort({1: {2}, 2: {1}, 3: set()})
    assert next(gen) == {3}
    with pytest.raises(CircularDependencyError):
        next(gen)


def test_circular_three_cycle():
    with pytest.raises(CircularDependencyError):
        toposort_flatten({1: {2}, 2: {3}, 3: {1}})


def test_flatten_sorted():
    data = {3: {1, 2}, 2: {5}, 1: {5}}
    assert toposort_flatten(data) == [5, 1, 2, 3]


def test_flatten_unsorted_contains_all_in_order():
    data = {"c": {"a", "b"}, "b": {"a"}}
    res = toposort_flatten(data, sort=False)
    assert res == ["a", "b", "c"]


def test_flatten_unsorted_level_membership():
    data = {4: {1, 2, 3}}
    res = toposort_flatten(data, sort=False)
    assert sorted(res[:3]) == [1, 2, 3]
    assert res[3] == 4


def test_toposort_is_generator_lazy():
    gen = toposort({1: {2}, 2: {1}})
    # no error until iterated
    with pytest.raises(CircularDependencyError):
        list(gen)


def test_accepts_frozenset_and_list_values():
    assert list(toposort({1: [2], 3: frozenset({1})})) == [{2}, {1}, {3}]


def test_string_keys_diamond():
    data = {"d": {"b", "c"}, "b": {"a"}, "c": {"a"}}
    assert list(toposort(data)) == [{"a"}, {"b", "c"}, {"d"}]
