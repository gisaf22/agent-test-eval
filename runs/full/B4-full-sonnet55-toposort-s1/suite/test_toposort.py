# tests/test_toposort.py
import pytest

from toposort import toposort, toposort_flatten, CircularDependencyError


def test_empty_input():
    assert list(toposort({})) == []
    assert toposort_flatten({}) == []


def test_simple_chain():
    data = {2: {1}, 3: {2}}
    assert list(toposort(data)) == [{1}, {2}, {3}]


def test_levels_grouped():
    data = {
        2: {11},
        9: {11, 8, 10},
        10: {11, 3},
        11: {7, 5},
        8: {7, 3},
    }
    assert list(toposort(data)) == [{3, 5, 7}, {8, 11}, {2, 10}, {9}]


def test_items_only_in_dependencies_are_included():
    assert list(toposort({"a": {"b", "c"}})) == [{"b", "c"}, {"a"}]


def test_items_with_empty_deps():
    assert list(toposort({"a": set(), "b": {"a"}, "c": set()})) == [{"a", "c"}, {"b"}]


def test_self_dependency_ignored():
    assert list(toposort({1: {1}, 2: {1, 2}})) == [{1}, {2}]


def test_input_not_modified():
    data = {2: {1, 2}, 3: {2}}
    snapshot = {k: set(v) for k, v in data.items()}
    list(toposort(data))
    assert data == snapshot
    toposort_flatten(data)
    assert data == snapshot


def test_circular_two_nodes():
    with pytest.raises(CircularDependencyError) as ei:
        list(toposort({1: {2}, 2: {1}}))
    assert ei.value.data == {1: {2}, 2: {1}}


def test_circular_is_valueerror():
    assert issubclass(CircularDependencyError, ValueError)
    with pytest.raises(ValueError):
        toposort_flatten({1: {2}, 2: {3}, 3: {1}})


def test_circular_data_excludes_resolved_items():
    data = {1: set(), 2: {1}, 3: {4}, 4: {3}, 5: {3}}
    with pytest.raises(CircularDependencyError) as ei:
        list(toposort(data))
    assert set(ei.value.data) == {3, 4, 5}
    assert ei.value.data[5] == {3}


def test_circular_error_message():
    with pytest.raises(CircularDependencyError) as ei:
        list(toposort({1: {2}, 2: {1}}))
    msg = str(ei.value)
    assert "Circular dependencies exist among these items" in msg
    assert "1:{2}" in msg and "2:{1}" in msg


def test_error_raised_lazily_after_valid_levels():
    gen = toposort({1: set(), 2: {3}, 3: {2}})
    assert next(gen) == {1}
    with pytest.raises(CircularDependencyError):
        next(gen)


def test_flatten_sorted():
    data = {3: {2, 1}, 4: {3}}
    assert toposort_flatten(data) == [1, 2, 3, 4]


def test_flatten_unsorted_respects_order():
    data = {"c": {"a", "b"}, "d": {"c"}}
    res = toposort_flatten(data, sort=False)
    assert set(res[:2]) == {"a", "b"}
    assert res[2:] == ["c", "d"]


def test_flatten_default_sorts_within_level():
    data = {"z": {"y", "x", "w"}}
    assert toposort_flatten(data) == ["w", "x", "y", "z"]


def test_values_may_be_other_iterables():
    assert list(toposort({2: [1], 3: (2,)})) == [{1}, {2}, {3}]


def test_topological_property_large():
    data = {i: set(range(max(0, i - 3), i)) for i in range(1, 50)}
    order = toposort_flatten(data)
    pos = {x: i for i, x in enumerate(order)}
    assert len(order) == 50
    for k, deps in data.items():
        for d in deps:
            assert pos[d] < pos[k]
