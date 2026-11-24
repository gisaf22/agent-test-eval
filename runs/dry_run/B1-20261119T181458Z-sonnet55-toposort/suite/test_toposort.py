# tests/test_toposort.py
import pytest

from toposort import toposort, toposort_flatten, CircularDependencyError


def test_empty():
    assert list(toposort({})) == []
    assert toposort_flatten({}) == []


def test_toposort_is_generator_for_empty():
    assert list(toposort({})) == []


def test_simple():
    data = {2: {11}, 9: {11, 8}, 10: {11, 3}, 11: {7, 5}, 8: {7, 3}}
    assert list(toposort(data)) == [{3, 5, 7}, {8, 11}, {2, 9, 10}]


def test_no_dependencies():
    assert list(toposort({1: set(), 2: set()})) == [{1, 2}]


def test_extra_items_in_deps_added():
    assert list(toposort({1: {2}})) == [{2}, {1}]


def test_self_dependency_ignored():
    assert list(toposort({1: {1}, 2: {1, 2}})) == [{1}, {2}]


def test_input_not_modified():
    data = {1: {2, 3}, 2: {3}}
    copy = {k: set(v) for k, v in data.items()}
    list(toposort(data))
    assert data == copy


def test_input_not_modified_on_flatten():
    data = {1: {2}, 2: set()}
    toposort_flatten(data)
    assert data == {1: {2}, 2: set()}


def test_chain():
    data = {1: {2}, 2: {3}, 3: {4}}
    assert list(toposort(data)) == [{4}, {3}, {2}, {1}]


def test_cycle_raises():
    with pytest.raises(CircularDependencyError):
        list(toposort({1: {2}, 2: {1}}))


def test_cycle_is_valueerror():
    with pytest.raises(ValueError):
        toposort_flatten({1: {2}, 2: {1}})


def test_cycle_data_and_message():
    data = {1: {2}, 2: {1}, 3: {1}, 0: set()}
    with pytest.raises(CircularDependencyError) as ei:
        list(toposort(data))
    assert ei.value.data == {1: {2}, 2: {1}, 3: {1}}
    assert "Circular dependencies exist among these items" in str(ei.value)
    assert "1:{2}" in str(ei.value)


def test_cycle_yields_earlier_levels_first():
    gen = toposort({1: {2}, 2: {1}, 3: set(), 4: {3}})
    assert next(gen) == {3}
    assert next(gen) == {4}
    with pytest.raises(CircularDependencyError):
        next(gen)


def test_flatten_sorted():
    data = {2: {11}, 9: {11, 8}, 10: {11, 3}, 11: {7, 5}, 8: {7, 3}}
    assert toposort_flatten(data) == [3, 5, 7, 8, 11, 2, 9, 10]


def test_flatten_unsorted_respects_order():
    data = {2: {11}, 9: {11, 8}, 10: {11, 3}, 11: {7, 5}, 8: {7, 3}}
    res = toposort_flatten(data, sort=False)
    assert sorted(res) == [2, 3, 5, 7, 8, 9, 10, 11]
    for k, deps in data.items():
        for d in deps:
            assert res.index(d) < res.index(k)


def test_string_items():
    data = {"b": {"a"}, "c": {"b", "a"}}
    assert toposort_flatten(data) == ["a", "b", "c"]


def test_exports():
    import toposort as m
    assert set(m.__all__) == {"toposort", "toposort_flatten", "CircularDependencyError"}
