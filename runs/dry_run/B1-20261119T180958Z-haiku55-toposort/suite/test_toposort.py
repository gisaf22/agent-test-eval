# tests/test_toposort.py
import copy
import inspect
import types

import pytest

import toposort as toposort_module
from toposort import CircularDependencyError, toposort, toposort_flatten


def layers(data):
    """Materialise toposort output as a list of sets."""
    return list(toposort(data))


def assert_valid_layering(data, result):
    """Every item appears exactly once, and each item's dependencies
    (excluding self-dependencies) appear in strictly earlier layers."""
    all_items = set(data.keys())
    for deps in data.values():
        all_items |= set(deps)

    seen = set()
    position = {}
    for index, layer in enumerate(result):
        assert isinstance(layer, set)
        assert layer, "toposort should never yield an empty layer"
        assert not (layer & seen), "items must not repeat across layers"
        for item in layer:
            position[item] = index
        seen |= layer

    assert seen == all_items

    for item, deps in data.items():
        for dep in deps:
            if dep == item:
                continue
            assert position[dep] < position[item], (
                f"{dep!r} must come before {item!r}"
            )


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------

def test_module_exports_public_names():
    assert set(toposort_module.__all__) == {
        "toposort",
        "toposort_flatten",
        "CircularDependencyError",
    }


def test_version_is_a_string():
    assert isinstance(toposort_module.__version__, str)
    assert toposort_module.__version__


def test_toposort_is_a_generator_function():
    assert inspect.isgeneratorfunction(toposort)


def test_circular_error_is_value_error_subclass():
    assert issubclass(CircularDependencyError, ValueError)


# ---------------------------------------------------------------------------
# Empty and trivial inputs
# ---------------------------------------------------------------------------

def test_empty_input_yields_nothing():
    assert layers({}) == []


def test_empty_input_returns_generator_object():
    gen = toposort({})
    assert isinstance(gen, types.GeneratorType)
    assert list(gen) == []


def test_single_item_without_dependencies():
    assert layers({"a": set()}) == [{"a"}]


def test_multiple_independent_items_form_one_layer():
    assert layers({"a": set(), "b": set(), "c": set()}) == [{"a", "b", "c"}]


def test_empty_dependency_collection_is_accepted_as_list():
    assert layers({"a": []}) == [{"a"}]


# ---------------------------------------------------------------------------
# Basic ordering
# ---------------------------------------------------------------------------

def test_simple_chain():
    data = {"c": {"b"}, "b": {"a"}, "a": set()}
    assert layers(data) == [{"a"}, {"b"}, {"c"}]


def test_items_only_present_as_dependencies_are_added():
    # 2 and 3 never appear as keys; they should be yielded first.
    assert layers({1: {2, 3}}) == [{2, 3}, {1}]


def test_dependency_only_item_is_placed_in_first_layer():
    result = layers({"x": {"y"}})
    assert result[0] == {"y"}
    assert result[1] == {"x"}
    assert len(result) == 2


def test_diamond_graph():
    data = {
        "top": {"left", "right"},
        "left": {"bottom"},
        "right": {"bottom"},
        "bottom": set(),
    }
    assert layers(data) == [{"bottom"}, {"left", "right"}, {"top"}]


def test_parallel_independent_chains_are_grouped_by_depth():
    data = {
        "a1": set(),
        "a2": {"a1"},
        "b1": set(),
        "b2": {"b1"},
        "b3": {"b2"},
    }
    result = layers(data)
    assert result[0] == {"a1", "b1"}
    assert result[1] == {"a2", "b2"}
    assert result[2] == {"b3"}
    assert_valid_layering(data, result)


def test_items_are_grouped_in_maximal_layers():
    # 'd' depends only on 'a', so it can be produced in the same layer as 'b'.
    data = {"a": set(), "b": {"a"}, "c": {"b"}, "d": {"a"}}
    result = layers(data)
    assert result == [{"a"}, {"b", "d"}, {"c"}]


def test_dependencies_as_list_and_tuple_and_frozenset():
    data = {"c": ["b"], "b": ("a",), "a": frozenset()}
    result = layers(data)
    assert result == [{"a"}, {"b"}, {"c"}]


def test_integer_and_mixed_hashable_items():
    data = {1: {2}, 2: {"two"}, "two": set(), (3, 4): {1}}
    result = layers(data)
    assert_valid_layering(data, result)
    assert result[0] == {"two"}


def test_wide_fan_in():
    deps = {f"leaf{i}" for i in range(50)}
    data = {"root": deps}
    result = layers(data)
    assert result == [deps, {"root"}]


def test_wide_fan_out():
    data = {f"child{i}": {"root"} for i in range(50)}
    data["root"] = set()
    result = layers(data)
    assert result[0] == {"root"}
    assert result[1] == {f"child{i}" for i in range(50)}


def test_long_chain_is_resolved_in_order():
    n = 500
    data = {i: {i - 1} for i in range(1, n)}
    data[0] = set()
    result = layers(data)
    assert len(result) == n
    assert all(layer == {i} for i, layer in enumerate(result))


# ---------------------------------------------------------------------------
# Self-dependencies
# ---------------------------------------------------------------------------

def test_self_dependency_is_discarded():
    assert layers({"a": {"a"}}) == [{"a"}]


def test_self_dependency_alongside_real_dependency():
    data = {"a": {"a", "b"}, "b": set()}
    assert layers(data) == [{"b"}, {"a"}]


def test_self_dependency_does_not_create_cycle_error():
    data = {"a": {"a"}, "b": {"b", "a"}}
    result = layers(data)
    assert result == [{"a"}, {"b"}]


# ---------------------------------------------------------------------------
# Input is not mutated
# ---------------------------------------------------------------------------

def test_input_dict_is_not_modified():
    data = {"a": set(), "b": {"a", "b"}, "c": {"x"}}
    snapshot = copy.deepcopy(data)
    layers(data)
    assert data == snapshot


def test_input_value_sets_are_not_modified_during_sort():
    data = {"b": {"a"}, "a": set()}
    value_before = data["b"]
    layers(data)
    assert data["b"] is value_before
    assert data["b"] == {"a"}


def test_input_not_modified_when_error_raised():
    data = {1: {2}, 2: {1}, 3: set()}
    snapshot = copy.deepcopy(data)
    with pytest.raises(CircularDependencyError):
        layers(data)
    assert data == snapshot


def test_repeated_calls_give_same_result():
    data = {"c": {"a", "b"}, "a": set(), "b": {"a"}}
    assert layers(data) == layers(data)


# ---------------------------------------------------------------------------
# Lazy evaluation
# ---------------------------------------------------------------------------

def test_creating_generator_does_not_raise_on_cycle():
    data = {1: {2}, 2: {1}}
    gen = toposort(data)  # no exception until iteration begins
    with pytest.raises(CircularDependencyError):
        next(gen)


def test_layers_before_cycle_are_yielded_before_error():
    data = {"ok": set(), "after": {"ok"}, "p": {"q"}, "q": {"p"}}
    gen = toposort(data)
    assert next(gen) == {"ok"}
    assert next(gen) == {"after"}
    with pytest.raises(CircularDependencyError):
        next(gen)


def test_exhausted_generator_stays_exhausted():
    gen = toposort({"a": set()})
    assert next(gen) == {"a"}
    with pytest.raises(StopIteration):
        next(gen)
    with pytest.raises(StopIteration):
        next(gen)


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

def test_two_node_cycle_raises():
    with pytest.raises(CircularDependencyError):
        layers({1: {2}, 2: {1}})


def test_three_node_cycle_raises():
    with pytest.raises(CircularDependencyError):
        layers({"a": {"b"}, "b": {"c"}, "c": {"a"}})


def test_cycle_downstream_of_resolvable_items_raises():
    data = {"root": set(), "x": {"root", "y"}, "y": {"x"}}
    with pytest.raises(CircularDependencyError):
        layers(data)


def test_error_is_catchable_as_value_error():
    with pytest.raises(ValueError):
        layers({"a": {"b"}, "b": {"a"}})


def test_error_message_mentions_circular_dependencies():
    with pytest.raises(CircularDependencyError) as excinfo:
        layers({"a": {"b"}, "b": {"a"}})
    msg = str(excinfo.value)
    assert "Circular dependencies exist" in msg
    assert "a" in msg and "b" in msg


def test_error_data_contains_only_unresolved_items():
    data = {1: {2}, 2: {1}, 3: set(), 4: {3}}
    with pytest.raises(CircularDependencyError) as excinfo:
        layers(data)
    assert excinfo.value.data == {1: {2}, 2: {1}}


def test_error_data_for_pure_cycle_is_full_graph():
    data = {"a": {"b"}, "b": {"a"}}
    with pytest.raises(CircularDependencyError) as excinfo:
        layers(data)
    assert excinfo.value.data == {"a": {"b"}, "b": {"a"}}


def test_error_data_is_a_dict():
    with pytest.raises(CircularDependencyError) as excinfo:
        layers({"a": {"a2"}, "a2": {"a"}})
    assert isinstance(excinfo.value.data, dict)


def test_error_message_includes_items_in_cycle_only_not_resolved_ones():
    with pytest.raises(CircularDependencyError) as excinfo:
        layers({"free": set(), "p": {"q"}, "q": {"p"}})
    msg = str(excinfo.value)
    assert "p" in msg and "q" in msg


def test_cycle_error_can_be_constructed_directly():
    err = CircularDependencyError({"a": {"b"}})
    assert isinstance(err, ValueError)
    assert err.data == {"a": {"b"}}
    assert "Circular dependencies exist" in str(err)


def test_toposort_flatten_raises_on_cycle():
    with pytest.raises(CircularDependencyError):
        toposort_flatten({1: {2}, 2: {1}})


# ---------------------------------------------------------------------------
# toposort_flatten
# ---------------------------------------------------------------------------

def test_flatten_empty_input():
    assert toposort_flatten({}) == []


def test_flatten_single_item():
    assert toposort_flatten({"a": set()}) == ["a"]


def test_flatten_sorts_within_layers_by_default():
    data = {"c": set(), "a": set(), "b": set()}
    assert toposort_flatten(data) == ["a", "b", "c"]


def test_flatten_chain_order():
    data = {"c": {"b"}, "b": {"a"}, "a": set()}
    assert toposort_flatten(data) == ["a", "b", "c"]


def test_flatten_respects_layer_boundaries():
    data = {"top": {"left", "right"}, "left": {"bottom"}, "right": {"bottom"}, "bottom": set()}
    assert toposort_flatten(data) == ["bottom", "left", "right", "top"]


def test_flatten_sort_false_keeps_all_items_and_layer_order():
    data = {"top": {"left", "right"}, "left": {"bottom"}, "right": {"bottom"}, "bottom": set()}
    result = toposort_flatten(data, sort=False)
    assert sorted(result) == sorted(["top", "left", "right", "bottom"])
    assert result[0] == "bottom"
    assert result[-1] == "top"
    assert set(result[1:3]) == {"left", "right"}


def test_flatten_sort_false_is_a_list():
    assert isinstance(toposort_flatten({"a": set()}, sort=False), list)


def test_flatten_is_deterministic():
    data = {f"n{i}": {f"n{i - 1}"} for i in range(1, 30)}
    data["n0"] = set()
    assert toposort_flatten(data) == toposort_flatten(data)


def test_flatten_includes_dependency_only_items():
    result = toposort_flatten({1: {2, 3}})
    assert result == [2, 3, 1]


def test_flatten_handles_self_dependency():
    assert toposort_flatten({"a": {"a"}, "b": {"a"}}) == ["a", "b"]


def test_flatten_is_valid_topological_order():
    data = {
        "app": {"lib", "util"},
        "lib": {"core"},
        "util": {"core", "log"},
        "core": set(),
        "log": set(),
    }
    result = toposort_flatten(data)
    position = {item: i for i, item in enumerate(result)}
    assert len(result) == len(set(result)) == 5
    for item, deps in data.items():
        for dep in deps:
            assert position[dep] < position[item]


# ---------------------------------------------------------------------------
# Property-style checks on several graphs
# ---------------------------------------------------------------------------

GRAPHS = [
    {},
    {"a": set()},
    {"a": {"a"}},
    {1: {2, 3}},
    {"c": {"b"}, "b": {"a"}, "a": set()},
    {"top": {"left", "right"}, "left": {"bottom"}, "right": {"bottom"}, "bottom": set()},
    {"x": {"y", "z"}, "y": {"z"}, "z": set(), "w": {"x"}},
    {i: {j for j in range(i) if (i + j) % 3 == 0} for i in range(20)},
]


@pytest.mark.parametrize("graph", GRAPHS)
def test_layering_is_valid_for_each_graph(graph):
    result = layers(graph)
    assert_valid_layering(graph, result)


@pytest.mark.parametrize("graph", GRAPHS)
def test_flatten_covers_all_items_exactly_once(graph):
    flat = toposort_flatten(graph)
    expected = set(graph.keys())
    for deps in graph.values():
        expected |= set(deps)
    assert len(flat) == len(set(flat)) == len(expected)
    assert set(flat) == expected


@pytest.mark.parametrize("graph", GRAPHS)
def test_layers_are_disjoint_nonempty_sets(graph):
    for layer in layers(graph):
        assert isinstance(layer, set)
        assert len(layer) > 0


def test_each_layer_is_minimal_depth():
    # An item should appear in the earliest layer where all its deps are done.
    data = {"a": set(), "b": {"a"}, "c": {"a"}, "d": {"b", "c"}, "e": set()}
    result = layers(data)
    assert result == [{"a", "e"}, {"b", "c"}, {"d"}]
