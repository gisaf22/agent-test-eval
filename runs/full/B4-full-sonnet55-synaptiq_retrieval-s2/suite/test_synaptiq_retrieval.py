# tests/test_synaptiq_retrieval.py
import pytest

from synaptiq_retrieval import (
    DEFAULT_RRF_K,
    fuse_and_rank,
    reciprocal_rank_fusion,
)


def test_default_k():
    assert DEFAULT_RRF_K == 60


def test_single_ranking_scores():
    s = reciprocal_rank_fusion([["a", "b", "c"]])
    assert s == {
        "a": pytest.approx(1 / 61),
        "b": pytest.approx(1 / 62),
        "c": pytest.approx(1 / 63),
    }


def test_multiple_rankings_sum():
    s = reciprocal_rank_fusion([["a", "b"], ["b", "a"]])
    assert s["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert s["b"] == pytest.approx(1 / 61 + 1 / 62)


def test_custom_k():
    s = reciprocal_rank_fusion([["a", "b"]], k=10)
    assert s["a"] == pytest.approx(1 / 11)
    assert s["b"] == pytest.approx(1 / 12)


def test_weights():
    s = reciprocal_rank_fusion([["a"], ["b"]], weights=[2.0, 0.5])
    assert s["a"] == pytest.approx(2 / 61)
    assert s["b"] == pytest.approx(0.5 / 61)


def test_weights_accepts_generator_and_rankings_generator():
    s = reciprocal_rank_fusion((r for r in [["a"], ["b"]]), weights=(w for w in [1, 3]))
    assert s["b"] == pytest.approx(3 / 61)


def test_weights_length_mismatch():
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"], ["b"]], weights=[1.0])
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], weights=[1.0, 2.0])


def test_duplicates_count_once_at_best_rank():
    s = reciprocal_rank_fusion([["a", "b", "a"]])
    assert s["a"] == pytest.approx(1 / 61)
    assert s["b"] == pytest.approx(1 / 62)


def test_duplicates_across_rankings_still_accumulate():
    s = reciprocal_rank_fusion([["a", "a"], ["a"]])
    assert s["a"] == pytest.approx(2 / 61)


def test_empty_inputs():
    assert reciprocal_rank_fusion([]) == {}
    assert reciprocal_rank_fusion([[], []]) == {}
    assert fuse_and_rank([]) == []


def test_multi_ranking_beats_single_first():
    # b is 2nd in both; a is 1st in only one
    assert fuse_and_rank([["a", "b"], ["c", "b"]])[0] == "b"


def test_fuse_orders_descending():
    assert fuse_and_rank([["a", "b", "c"]]) == ["a", "b", "c"]


def test_limit():
    r = [["a", "b", "c", "d"]]
    assert fuse_and_rank(r, limit=2) == ["a", "b"]
    assert fuse_and_rank(r, limit=0) == []
    assert fuse_and_rank(r, limit=10) == ["a", "b", "c", "d"]
    assert fuse_and_rank(r, limit=None) == ["a", "b", "c", "d"]


def test_tie_break_by_first_ranking_order():
    assert fuse_and_rank([["a", "b"], ["b", "a"]]) == ["a", "b"]
    assert fuse_and_rank([["b", "a"], ["a", "b"]]) == ["b", "a"]


def test_tie_break_equal_scores_distinct_rankings():
    assert fuse_and_rank([["a"], ["b"]]) == ["a", "b"]
    assert fuse_and_rank([["b"], ["a"]]) == ["b", "a"]


def test_weights_change_order():
    r = [["a"], ["b"]]
    assert fuse_and_rank(r, weights=[1, 5]) == ["b", "a"]


def test_deterministic():
    r = [["a", "b", "c"], ["c", "d", "a"], ["e", "b"]]
    assert fuse_and_rank(r) == fuse_and_rank(r)


def test_all_ids_returned_once():
    out = fuse_and_rank([["a", "b", "a"], ["c", "b"]])
    assert sorted(out) == ["a", "b", "c"]


def test_generator_rankings_in_fuse_and_rank():
    out = fuse_and_rank(iter([["a", "b"], ["b"]]))
    assert out == ["b", "a"]


def test_fuse_weights_mismatch_raises():
    with pytest.raises(ValueError):
        fuse_and_rank([["a"]], weights=[1, 2])
