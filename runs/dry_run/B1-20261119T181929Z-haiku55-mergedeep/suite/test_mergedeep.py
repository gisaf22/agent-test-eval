# tests/test_mergedeep.py
from collections import Counter, OrderedDict
from types import MappingProxyType

import pytest

from mergedeep import Strategy, merge


ALL_STRATEGIES = list(Strategy)
TYPESAFE_STRATEGIES = [Strategy.TYPESAFE, Strategy.TYPESAFE_REPLACE]
TYPESAFE_ADDITIVE_STRATEGIES = [Strategy.TYPESAFE_ADDITIVE]


# ---------------------------------------------------------------------------
# Public API basics
# ---------------------------------------------------------------------------

class TestMergeBasics:
    def test_returns_destination_object_itself(self):
        dst = {"a": 1}
        result = merge(dst, {"b": 2})
        assert result is dst

    def test_mutates_destination_in_place(self):
        dst = {"a": 1}
        merge(dst, {"b": 2})
        assert dst == {"a": 1, "b": 2}

    def test_disjoint_keys_are_combined(self):
        assert merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_destination_only_keys_are_preserved(self):
        dst = {"a": 1, "keep": "me"}
        merge(dst, {"a": 2})
        assert dst["keep"] == "me"

    def test_no_sources_returns_destination_unchanged(self):
        dst = {"a": {"b": [1, 2]}}
        snapshot = {"a": {"b": [1, 2]}}
        result = merge(dst)
        assert result is dst
        assert dst == snapshot

    def test_empty_source_mapping_changes_nothing(self):
        dst = {"a": 1}
        merge(dst, {})
        assert dst == {"a": 1}

    def test_multiple_sources_applied_left_to_right_last_wins(self):
        dst = {}
        merge(dst, {"k": 1}, {"k": 2}, {"k": 3})
        assert dst == {"k": 3}

    def test_multiple_sources_merge_all_keys(self):
        dst = {"base": True}
        merge(dst, {"one": 1}, {"two": 2}, {"three": 3})
        assert dst == {"base": True, "one": 1, "two": 2, "three": 3}

    def test_source_only_keys_are_added(self):
        dst = {}
        merge(dst, {"new": {"deep": [1]}})
        assert dst == {"new": {"deep": [1]}}

    def test_source_only_values_are_deep_copied(self):
        src = {"new": {"deep": [1]}}
        dst = {}
        merge(dst, src)
        assert dst["new"] is not src["new"]
        assert dst["new"]["deep"] is not src["new"]["deep"]

    def test_source_is_not_mutated_by_later_destination_changes(self):
        src = {"a": {"k": [1]}}
        dst = {}
        merge(dst, src)
        dst["a"]["k"].append(99)
        assert src == {"a": {"k": [1]}}

    def test_accepts_any_mapping_as_source(self):
        src = MappingProxyType({"a": 1, "b": {"c": 2}})
        dst = {}
        merge(dst, src)
        assert dst == {"a": 1, "b": {"c": 2}}

    def test_accepts_ordered_dict_as_destination(self):
        dst = OrderedDict([("a", 1)])
        merge(dst, {"b": 2})
        assert dict(dst) == {"a": 1, "b": 2}

    def test_default_strategy_is_replace(self):
        dst = {"a": [1, 2]}
        merge(dst, {"a": [3]})
        assert dst == {"a": [3]}

    def test_strategy_is_keyword_argument(self):
        dst = {"a": [1]}
        merge(dst, {"a": [2]}, strategy=Strategy.ADDITIVE)
        assert dst == {"a": [1, 2]}

    @pytest.mark.parametrize("strategy", ALL_STRATEGIES)
    def test_every_strategy_merges_disjoint_keys(self, strategy):
        dst = {"a": 1}
        merge(dst, {"b": {"c": 2}}, strategy=strategy)
        assert dst == {"a": 1, "b": {"c": 2}}

    @pytest.mark.parametrize("strategy", ALL_STRATEGIES)
    def test_every_strategy_with_no_sources_is_noop(self, strategy):
        dst = {"a": [1]}
        assert merge(dst, strategy=strategy) is dst
        assert dst == {"a": [1]}

    def test_strategy_enum_has_expected_members(self):
        assert {s.name for s in Strategy} == {
            "REPLACE",
            "ADDITIVE",
            "TYPESAFE",
            "TYPESAFE_REPLACE",
            "TYPESAFE_ADDITIVE",
        }


# ---------------------------------------------------------------------------
# Recursive merging of nested mappings (strategy independent)
# ---------------------------------------------------------------------------

class TestNestedMappings:
    @pytest.mark.parametrize("strategy", ALL_STRATEGIES)
    def test_nested_dicts_are_merged_recursively(self, strategy):
        dst = {"a": {"b": {"c": 1}}}
        merge(dst, {"a": {"b": {"d": 2}}}, strategy=strategy)
        assert dst == {"a": {"b": {"c": 1, "d": 2}}}

    def test_nested_dict_identity_is_preserved(self):
        inner = {"x": 1}
        dst = {"a": inner}
        merge(dst, {"a": {"y": 2}})
        assert dst["a"] is inner
        assert inner == {"x": 1, "y": 2}

    def test_mapping_value_replaces_non_mapping_destination(self):
        dst = {"a": 5}
        merge(dst, {"a": {"x": 1}})
        assert dst == {"a": {"x": 1}}

    def test_non_mapping_value_replaces_mapping_destination(self):
        dst = {"a": {"x": 1}}
        merge(dst, {"a": None})
        assert dst == {"a": None}

    def test_replacement_mapping_is_deep_copied(self):
        src = {"a": {"x": {"y": [1]}}}
        dst = {"a": 0}
        merge(dst, src)
        assert dst["a"] is not src["a"]
        assert dst["a"]["x"] is not src["a"]["x"]

    def test_recursion_into_mapping_proxy_source(self):
        dst = {"a": {"x": 1}}
        merge(dst, {"a": MappingProxyType({"y": 2})})
        assert dst == {"a": {"x": 1, "y": 2}}

    def test_recursion_into_ordered_dict_destination(self):
        inner = OrderedDict([("x", 1)])
        dst = {"a": inner}
        merge(dst, {"a": {"y": 2}})
        assert dst["a"] is inner
        assert dict(inner) == {"x": 1, "y": 2}

    def test_deeply_nested_recursion_with_conflicting_leaf(self):
        dst = {"l1": {"l2": {"l3": {"leaf": "old", "keep": 1}}}}
        merge(dst, {"l1": {"l2": {"l3": {"leaf": "new"}}}})
        assert dst == {"l1": {"l2": {"l3": {"leaf": "new", "keep": 1}}}}


# ---------------------------------------------------------------------------
# REPLACE strategy
# ---------------------------------------------------------------------------

class TestReplaceStrategy:
    def test_scalar_is_overwritten(self):
        dst = {"a": 1}
        merge(dst, {"a": 2}, strategy=Strategy.REPLACE)
        assert dst == {"a": 2}

    def test_list_is_replaced_not_extended(self):
        dst = {"a": [1, 2]}
        merge(dst, {"a": [3]}, strategy=Strategy.REPLACE)
        assert dst == {"a": [3]}

    def test_tuple_is_replaced(self):
        dst = {"a": (1,)}
        merge(dst, {"a": (2, 3)}, strategy=Strategy.REPLACE)
        assert dst == {"a": (2, 3)}

    def test_set_is_replaced(self):
        dst = {"a": {1, 2}}
        merge(dst, {"a": {3}}, strategy=Strategy.REPLACE)
        assert dst == {"a": {3}}

    def test_none_source_overwrites_scalar(self):
        dst = {"a": 1}
        merge(dst, {"a": None}, strategy=Strategy.REPLACE)
        assert dst == {"a": None}

    def test_replaced_list_is_deep_copied(self):
        src_list = [{"k": 1}]
        dst = {"a": [0]}
        merge(dst, {"a": src_list}, strategy=Strategy.REPLACE)
        assert dst["a"] == src_list
        assert dst["a"] is not src_list
        dst["a"][0]["k"] = 99
        assert src_list == [{"k": 1}]

    def test_identical_object_is_kept_not_copied(self):
        shared = [1]
        dst = {"a": shared}
        merge(dst, {"a": shared}, strategy=Strategy.REPLACE)
        assert dst["a"] is shared
        assert shared == [1]

    def test_counter_values_are_replaced_per_key(self):
        dst = {"c": Counter(a=1, b=2)}
        merge(dst, {"c": Counter(b=5, c=3)}, strategy=Strategy.REPLACE)
        assert dst["c"] == Counter(a=1, b=5, c=3)
        assert isinstance(dst["c"], Counter)

    def test_counter_merge_mutates_destination_counter_in_place(self):
        original = Counter(a=1)
        dst = {"c": original}
        merge(dst, {"c": Counter(a=7)}, strategy=Strategy.REPLACE)
        assert dst["c"] is original
        assert original == Counter(a=7)

    def test_dict_source_merges_into_counter_destination_as_mapping(self):
        dst = {"c": Counter(x=1)}
        merge(dst, {"c": {"x": 5, "y": 2}}, strategy=Strategy.REPLACE)
        assert dst["c"] == Counter(x=5, y=2)
        assert isinstance(dst["c"], Counter)

    def test_list_in_nested_dict_replaced(self):
        dst = {"outer": {"items": [1, 2, 3]}}
        merge(dst, {"outer": {"items": [9]}}, strategy=Strategy.REPLACE)
        assert dst == {"outer": {"items": [9]}}


# ---------------------------------------------------------------------------
# ADDITIVE strategy
# ---------------------------------------------------------------------------

class TestAdditiveStrategy:
    def test_lists_are_extended_in_order(self):
        dst = {"a": [1, 2]}
        merge(dst, {"a": [3, 4]}, strategy=Strategy.ADDITIVE)
        assert dst == {"a": [1, 2, 3, 4]}

    def test_list_duplicates_are_kept(self):
        dst = {"a": [1]}
        merge(dst, {"a": [1]}, strategy=Strategy.ADDITIVE)
        assert dst == {"a": [1, 1]}

    def test_list_identity_is_preserved_when_extended(self):
        original = [1]
        dst = {"a": original}
        merge(dst, {"a": [2]}, strategy=Strategy.ADDITIVE)
        assert dst["a"] is original
        assert original == [1, 2]

    def test_extended_items_are_deep_copies(self):
        item = {"k": [1]}
        dst = {"a": []}
        merge(dst, {"a": [item]}, strategy=Strategy.ADDITIVE)
        dst["a"][0]["k"].append(2)
        assert item == {"k": [1]}

    def test_sets_are_unioned(self):
        dst = {"a": {1, 2}}
        merge(dst, {"a": {2, 3}}, strategy=Strategy.ADDITIVE)
        assert dst == {"a": {1, 2, 3}}

    def test_set_identity_is_preserved(self):
        original = {1}
        dst = {"a": original}
        merge(dst, {"a": {2}}, strategy=Strategy.ADDITIVE)
        assert dst["a"] is original
        assert original == {1, 2}

    def test_tuples_are_concatenated_into_new_tuple(self):
        original = (1, 2)
        dst = {"t": original}
        merge(dst, {"t": (3,)}, strategy=Strategy.ADDITIVE)
        assert dst["t"] == (1, 2, 3)
        assert dst["t"] is not original
        assert original == (1, 2)

    def test_counters_are_summed(self):
        dst = {"c": Counter(a=1, b=2)}
        merge(dst, {"c": Counter(b=3, c=4)}, strategy=Strategy.ADDITIVE)
        assert dst["c"] == Counter(a=1, b=5, c=4)
        assert isinstance(dst["c"], Counter)

    def test_counter_update_is_in_place(self):
        original = Counter(a=1)
        dst = {"c": original}
        merge(dst, {"c": Counter(a=1)}, strategy=Strategy.ADDITIVE)
        assert dst["c"] is original
        assert original == Counter(a=2)

    def test_list_into_tuple_falls_back_to_replace(self):
        dst = {"a": (1,)}
        merge(dst, {"a": [2]}, strategy=Strategy.ADDITIVE)
        assert dst == {"a": [2]}

    def test_tuple_into_list_falls_back_to_replace(self):
        dst = {"a": [1]}
        merge(dst, {"a": (2,)}, strategy=Strategy.ADDITIVE)
        assert dst == {"a": (2,)}

    def test_list_into_set_falls_back_to_replace(self):
        dst = {"a": {1}}
        merge(dst, {"a": [2]}, strategy=Strategy.ADDITIVE)
        assert dst == {"a": [2]}

    def test_scalars_are_replaced(self):
        dst = {"a": 1}
        merge(dst, {"a": 2}, strategy=Strategy.ADDITIVE)
        assert dst == {"a": 2}

    def test_list_replaces_scalar(self):
        dst = {"a": 1}
        merge(dst, {"a": [2]}, strategy=Strategy.ADDITIVE)
        assert dst == {"a": [2]}

    def test_scalar_replaces_list(self):
        dst = {"a": [1]}
        merge(dst, {"a": 2}, strategy=Strategy.ADDITIVE)
        assert dst == {"a": 2}

    def test_additive_nested_under_dicts(self):
        dst = {"a": {"items": [1], "tags": {"x"}}}
        merge(dst, {"a": {"items": [2], "tags": {"y"}}}, strategy=Strategy.ADDITIVE)
        assert dst == {"a": {"items": [1, 2], "tags": {"x", "y"}}}

    def test_additive_across_multiple_sources(self):
        dst = {"a": [0]}
        merge(dst, {"a": [1]}, {"a": [2]}, strategy=Strategy.ADDITIVE)
        assert dst == {"a": [0, 1, 2]}

    def test_identical_list_object_is_not_duplicated(self):
        shared = [1]
        dst = {"a": shared}
        merge(dst, {"a": shared}, strategy=Strategy.ADDITIVE)
        assert dst["a"] is shared
        assert shared == [1]

    def test_identical_tuple_object_is_not_duplicated(self):
        shared = (1,)
        dst = {"a": shared}
        merge(dst, {"a": shared}, strategy=Strategy.ADDITIVE)
        assert dst == {"a": (1,)}

    def test_source_lists_not_mutated(self):
        src = {"a": [3]}
        dst = {"a": [1]}
        merge(dst, src, strategy=Strategy.ADDITIVE)
        assert src == {"a": [3]}


# ---------------------------------------------------------------------------
# TYPESAFE and TYPESAFE_REPLACE strategies
# ---------------------------------------------------------------------------

class TestTypesafeReplace:
    @pytest.mark.parametrize("strategy", TYPESAFE_STRATEGIES)
    def test_same_type_scalars_are_replaced(self, strategy):
        dst = {"a": 1}
        merge(dst, {"a": 2}, strategy=strategy)
        assert dst == {"a": 2}

    @pytest.mark.parametrize("strategy", TYPESAFE_STRATEGIES)
    def test_mismatched_types_raise_type_error(self, strategy):
        dst = {"a": 1}
        with pytest.raises(TypeError, match='key: "a"'):
            merge(dst, {"a": "one"}, strategy=strategy)

    @pytest.mark.parametrize("strategy", TYPESAFE_STRATEGIES)
    def test_error_message_names_both_types(self, strategy):
        dst = {"a": 1}
        with pytest.raises(TypeError, match="destination type") as exc_info:
            merge(dst, {"a": "one"}, strategy=strategy)
        assert "int" in str(exc_info.value)
        assert "str" in str(exc_info.value)

    @pytest.mark.parametrize("strategy", TYPESAFE_STRATEGIES)
    def test_destination_unchanged_on_type_error(self, strategy):
        dst = {"a": 1}
        with pytest.raises(TypeError):
            merge(dst, {"a": "one"}, strategy=strategy)
        assert dst == {"a": 1}

    @pytest.mark.parametrize("strategy", TYPESAFE_STRATEGIES)
    def test_bool_and_int_are_considered_different(self, strategy):
        dst = {"a": True}
        with pytest.raises(TypeError):
            merge(dst, {"a": 1}, strategy=strategy)

    @pytest.mark.parametrize("strategy", TYPESAFE_STRATEGIES)
    def test_none_to_none_is_allowed(self, strategy):
        dst = {"a": None}
        merge(dst, {"a": None}, strategy=strategy)
        assert dst == {"a": None}

    @pytest.mark.parametrize("strategy", TYPESAFE_STRATEGIES)
    def test_list_to_list_is_replaced_not_extended(self, strategy):
        dst = {"a": [1]}
        merge(dst, {"a": [2]}, strategy=strategy)
        assert dst == {"a": [2]}

    @pytest.mark.parametrize("strategy", TYPESAFE_STRATEGIES)
    def test_mismatched_container_types_raise(self, strategy):
        dst = {"a": [1]}
        with pytest.raises(TypeError):
            merge(dst, {"a": (1,)}, strategy=strategy)

    @pytest.mark.parametrize("strategy", TYPESAFE_STRATEGIES)
    def test_scalar_destination_with_mapping_source_raises(self, strategy):
        dst = {"a": 1}
        with pytest.raises(TypeError):
            merge(dst, {"a": {"x": 1}}, strategy=strategy)

    @pytest.mark.parametrize("strategy", TYPESAFE_STRATEGIES)
    def test_mapping_destination_with_scalar_source_raises(self, strategy):
        dst = {"a": {"x": 1}}
        with pytest.raises(TypeError):
            merge(dst, {"a": 1}, strategy=strategy)

    @pytest.mark.parametrize("strategy", TYPESAFE_STRATEGIES)
    def test_missing_key_does_not_trigger_type_check(self, strategy):
        dst = {"a": 1}
        merge(dst, {"b": "anything"}, strategy=strategy)
        assert dst == {"a": 1, "b": "anything"}

    @pytest.mark.parametrize("strategy", TYPESAFE_STRATEGIES)
    def test_nested_mismatch_raises_with_inner_key(self, strategy):
        dst = {"x": {"y": 1}}
        with pytest.raises(TypeError, match='key: "y"'):
            merge(dst, {"x": {"y": "no"}}, strategy=strategy)

    @pytest.mark.parametrize("strategy", TYPESAFE_STRATEGIES)
    def test_same_type_counters_are_merged_like_replace(self, strategy):
        dst = {"c": Counter(a=1, b=2)}
        merge(dst, {"c": Counter(b=9, c=3)}, strategy=strategy)
        assert dst["c"] == Counter(a=1, b=9, c=3)

    @pytest.mark.parametrize("strategy", TYPESAFE_STRATEGIES)
    def test_mapping_types_differing_still_recurse_without_error(self, strategy):
        # Both sides are Mapping (and not both Counter), so the merge recurses
        # instead of performing the type check on the mapping itself.
        dst = {"a": {"x": 1}}
        merge(dst, {"a": OrderedDict([("y", 2)])}, strategy=strategy)
        assert dst == {"a": {"x": 1, "y": 2}}


class TestTypesafeAdditive:
    @pytest.mark.parametrize("strategy", TYPESAFE_ADDITIVE_STRATEGIES)
    def test_matching_lists_are_extended(self, strategy):
        dst = {"a": [1]}
        merge(dst, {"a": [2]}, strategy=strategy)
        assert dst == {"a": [1, 2]}

    @pytest.mark.parametrize("strategy", TYPESAFE_ADDITIVE_STRATEGIES)
    def test_matching_sets_are_unioned(self, strategy):
        dst = {"a": {1}}
        merge(dst, {"a": {2}}, strategy=strategy)
        assert dst == {"a": {1, 2}}

    @pytest.mark.parametrize("strategy", TYPESAFE_ADDITIVE_STRATEGIES)
    def test_matching_tuples_are_concatenated(self, strategy):
        dst = {"a": (1,)}
        merge(dst, {"a": (2,)}, strategy=strategy)
        assert dst == {"a": (1, 2)}

    @pytest.mark.parametrize("strategy", TYPESAFE_ADDITIVE_STRATEGIES)
    def test_matching_counters_are_summed(self, strategy):
        dst = {"c": Counter(a=1)}
        merge(dst, {"c": Counter(a=2, b=1)}, strategy=strategy)
        assert dst["c"] == Counter(a=3, b=1)

    @pytest.mark.parametrize("strategy", TYPESAFE_ADDITIVE_STRATEGIES)
    def test_same_type_scalars_are_replaced(self, strategy):
        dst = {"a": 1}
        merge(dst, {"a": 2}, strategy=strategy)
        assert dst == {"a": 2}

    @pytest.mark.parametrize("strategy", TYPESAFE_ADDITIVE_STRATEGIES)
    def test_list_and_tuple_mismatch_raises(self, strategy):
        dst = {"a": [1]}
        with pytest.raises(TypeError, match='key: "a"'):
            merge(dst, {"a": (2,)}, strategy=strategy)

    @pytest.mark.parametrize("strategy", TYPESAFE_ADDITIVE_STRATEGIES)
    def test_int_and_str_mismatch_raises(self, strategy):
        dst = {"a": 1}
        with pytest.raises(TypeError):
            merge(dst, {"a": "1"}, strategy=strategy)

    @pytest.mark.parametrize("strategy", TYPESAFE_ADDITIVE_STRATEGIES)
    def test_destination_unchanged_on_type_error(self, strategy):
        dst = {"a": [1]}
        with pytest.raises(TypeError):
            merge(dst, {"a": {2}}, strategy=strategy)
        assert dst == {"a": [1]}

    @pytest.mark.parametrize("strategy", TYPESAFE_ADDITIVE_STRATEGIES)
    def test_nested_additive_under_typesafe(self, strategy):
        dst = {"outer": {"items": [1]}}
        merge(dst, {"outer": {"items": [2]}}, strategy=strategy)
        assert dst == {"outer": {"items": [1, 2]}}

    @pytest.mark.parametrize("strategy", TYPESAFE_ADDITIVE_STRATEGIES)
    def test_missing_key_is_added_without_type_check(self, strategy):
        dst = {}
        merge(dst, {"new": [1]}, strategy=strategy)
        assert dst == {"new": [1]}


# ---------------------------------------------------------------------------
# Strategy-specific behaviour contrasted on the same input
# ---------------------------------------------------------------------------

class TestStrategyContrast:
    def test_replace_vs_additive_on_lists(self):
        base = {"a": [1]}
        rep = {"a": [1]}
        add = {"a": [1]}
        merge(rep, {"a": [2]}, strategy=Strategy.REPLACE)
        merge(add, {"a": [2]}, strategy=Strategy.ADDITIVE)
        assert rep == {"a": [2]}
        assert add == {"a": [1, 2]}
        assert base == {"a": [1]}

    def test_replace_ignores_type_mismatch_while_typesafe_raises(self):
        replaced = {"a": 1}
        merge(replaced, {"a": "x"}, strategy=Strategy.REPLACE)
        assert replaced == {"a": "x"}

        with pytest.raises(TypeError):
            merge({"a": 1}, {"a": "x"}, strategy=Strategy.TYPESAFE)

    def test_all_strategies_agree_on_scalar_same_type(self):
        for strategy in ALL_STRATEGIES:
            if strategy is Strategy.ADDITIVE or strategy is Strategy.TYPESAFE_ADDITIVE:
                # additive falls back to replace for scalars
                pass
            dst = {"a": 1}
            merge(dst, {"a": 2}, strategy=strategy)
            assert dst == {"a": 2}, strategy

    def test_all_strategies_agree_on_nested_recursion(self):
        for strategy in ALL_STRATEGIES:
            dst = {"a": {"b": {"c": 1}}}
            merge(dst, {"a": {"b": {"d": 2}}}, strategy=strategy)
            assert dst == {"a": {"b": {"c": 1, "d": 2}}}, strategy
