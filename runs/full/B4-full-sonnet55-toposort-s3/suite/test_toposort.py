# tests/test_toposort.py
import pytest

from toposort import toposort, toposort_flatten, CircularDependencyError


def test_empty():
    assert list(toposort({})) == []
    assert toposort_flatten({}) == []


def test_single_item_no_deps():
    assert list(toposort({1: set()})) == [{1}]


def test_simple_chain():
    data = {3: {2}, 2: {1}}
    assert list(toposort(data)) == [{1}, {2}, {3}]
    assert toposort_flatten(data) == [1, 2, 3]


def test_extra_items_in_deps_are_added():
    assert list(toposort({1: {2, 3}})) == [{2, 3}, {1}]


def test_levels_grouping():
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


def test_self_dependency_ignored():
    assert list(toposort({1: {1}})) == [{1}]
    assert list(toposort({1: {1, 2}})) == [{2}, {1}]


def test_input_not_modified():
    data = {1: {2, 3}, 2: {3}}
    copy = {k: set(v) for k, v in data.items()}
    list(toposort(data))
    toposort_flatten(data)
    assert data == copy


def test_simple_cycle():
    with pytest.raises(CircularDependencyError):
        list(toposort({1: {2}, 2: {1}}))


def test_cycle_error_data_and_type():
    data = {1: {2}, 2: {1}, 3: {1}}
    with pytest.raises(CircularDependencyError) as ei:
        list(toposort(data))
    assert isinstance(ei.value, ValueError)
    assert ei.value.data == {1: {2}, 2: {1}, 3: {1}}
    assert "Circular dependencies" in str(ei.value)


def test_cycle_after_valid_levels():
    gen = toposort({1: {2}, 2: {3}, 3: {2}, 4: set()})
    assert next(gen) == {4}
    with pytest.raises(CircularDependencyError) as ei:
        list(gen)
    assert set(ei.value.data) == {1, 2, 3}


def test_cycle_data_excludes_resolved():
    with pytest.raises(CircularDependencyError) as ei:
        list(toposort({1: {2}, 2: {1}, 3: set()}))
    assert ei.value.data == {1: {2}, 2: {1}}


def test_flatten_sorted():
    data = {10: {3, 2}, 5: set()}
    assert toposort_flatten(data) == [2, 3, 5, 10]


def test_flatten_unsorted_levels_preserved():
    data = {4: {1, 2, 3}}
    result = toposort_flatten(data, sort=False)
    assert sorted(result[:3]) == [1, 2, 3]
    assert result[3] == 4


def test_flatten_cycle_raises():
    with pytest.raises(CircularDependencyError):
        toposort_flatten({1: {2}, 2: {1}})


def test_string_items():
    data = {"b": {"a"}, "c": {"a", "b"}}
    assert toposort_flatten(data) == ["a", "b", "c"]


def test_accepts_list_dependencies():
    assert toposort_flatten({2: [1], 3: [2, 1]}) == [1, 2, 3]


def test_dependencies_come_before_dependents():
    data = {i: set(range(i)) for i in range(1, 20)}
    order = toposort_flatten(data)
    pos = {x: i for i, x in enumerate(order)}
    for k, deps in data.items():
        for d in deps:
            assert pos[d] < pos[k]
