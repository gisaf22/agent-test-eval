import pytest

from toposort import CircularDependencyError, toposort, toposort_flatten


def test_empty_input_yields_nothing():
    assert list(toposort({})) == []
    assert toposort_flatten({}) == []


def test_layered_order_exact():
    data = {2: {11}, 9: {11, 8, 10}, 10: {11, 3}, 11: {7, 5}, 8: {7, 3}}
    assert list(toposort(data)) == [{3, 5, 7}, {8, 11}, {2, 10}, {9}]


def test_items_only_in_dependencies_are_added():
    assert list(toposort({"a": {"b", "c"}})) == [{"b", "c"}, {"a"}]


def test_independent_items_share_first_layer():
    assert list(toposort({"a": set(), "b": set()})) == [{"a", "b"}]


def test_self_dependency_is_discarded():
    assert list(toposort({1: {1, 2}, 2: set()})) == [{2}, {1}]
    assert list(toposort({1: {1}})) == [{1}]


def test_input_not_mutated():
    data = {1: {1, 2}, 3: {2}}
    snapshot = {k: set(v) for k, v in data.items()}
    list(toposort(data))
    assert data == snapshot


def test_long_chain():
    data = {i: {i - 1} for i in range(1, 30)}
    assert list(toposort(data)) == [{i} for i in range(30)]


def test_cycle_raises_with_remaining_data():
    with pytest.raises(CircularDependencyError) as exc:
        list(toposort({1: {2}, 2: {1}}))
    assert exc.value.data == {1: {2}, 2: {1}}
    assert isinstance(exc.value, ValueError)


def test_cycle_after_partial_progress():
    gen = toposort({1: {2}, 2: {3}, 3: {2}, 4: set()})
    assert next(gen) == {4}
    with pytest.raises(CircularDependencyError) as exc:
        next(gen)
    # 1 depends on the cycle, so it remains unresolved too
    assert exc.value.data == {1: {2}, 2: {3}, 3: {2}}


def test_cycle_message_format():
    err = CircularDependencyError({"a": {"b"}})
    assert str(err) == "Circular dependencies exist among these items: {a:{'b'}}"
    err2 = CircularDependencyError({1: {2}, 2: {1}})
    assert str(err2) == "Circular dependencies exist among these items: {1:{2}, 2:{1}}"


def test_flatten_sorted_within_layers():
    data = {"z": {"b", "a"}, "y": {"a"}}
    assert toposort_flatten(data) == ["a", "b", "y", "z"]
    assert toposort_flatten(data, sort=True) == ["a", "b", "y", "z"]


def test_flatten_unsorted_keeps_layer_membership():
    data = {"z": {"b", "a"}, "y": {"a"}}
    out = toposort_flatten(data, sort=False)
    assert isinstance(out, list)
    assert set(out[:2]) == {"a", "b"}
    assert set(out[2:]) == {"y", "z"}
    assert len(out) == 4


def test_flatten_propagates_cycle_error():
    with pytest.raises(CircularDependencyError):
        toposort_flatten({1: {2}, 2: {1}})


def test_toposort_is_lazy_generator():
    gen = toposort({1: {2}, 2: {1}})  # no error until iterated
    with pytest.raises(CircularDependencyError):
        next(gen)
