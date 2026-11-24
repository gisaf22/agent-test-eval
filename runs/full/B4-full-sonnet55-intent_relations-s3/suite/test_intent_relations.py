# tests/test_intent_relations.py
import pytest
import intent_relations as ir


def mk(**spec):
    """mk(a=("open", [("part_of","b")]), ...)"""
    out = {}
    for k, (status, rels) in spec.items():
        out[k] = {"id": k, "what": "w" + k, "status": status,
                  "relations": [{"type": t, "intent": o} for t, o in rels]}
    return out


def test_words():
    assert ir.words("part_of") == "part of"


def test_active_entries_skips_removed_and_handles_missing():
    assert ir.active_entries({}) == []
    assert ir.active_entries({"relations": None}) == []
    i = {"relations": [{"type": "part_of", "intent": "x"},
                       {"type": "succeeds", "intent": "y", "removed_at": "t"}]}
    assert ir.active_entries(i) == [i["relations"][0]]


def test_active_relations():
    g = mk(a=("open", [("depends_on", "b")]), b=("open", []))
    g["a"]["relations"].append({"type": "succeeds", "intent": "b", "removed_at": "t"})
    assert list(ir.active_relations(g)) == [("a", "depends_on", "b")]


@pytest.mark.parametrize("kind,s,t,exp", [
    ("part_of", "done", "open", "done"),
    ("part_of", "cancelled", "open", "dropped"),
    ("part_of", "open", "done", "orphaned"),
    ("part_of", "open", "cancelled", "orphaned"),
    ("part_of", "open", "open", "in_progress"),
    ("succeeds", "open", "done", "handed_over"),
    ("succeeds", "open", "open", "pending"),
    ("depends_on", "open", "done", "satisfied"),
    ("depends_on", "open", "cancelled", "broken"),
    ("depends_on", "open", "open", "blocked"),
    ("conflicts_with", "open", "open", "unresolved"),
    ("conflicts_with", "done", "open", "resolved"),
    ("conflicts_with", "open", "cancelled", "resolved"),
    ("derived_from", "open", "open", None),
])
def test_state(kind, s, t, exp):
    assert ir.state(kind, {"status": s}, {"status": t}) == exp


def test_view_both_directions_and_order():
    g = mk(a=("open", [("depends_on", "b"), ("part_of", "c")]),
           b=("done", []), c=("open", []),
           d=("open", [("succeeds", "a"), ("conflicts_with", "a")]))
    rows = ir.view(g, "a")
    assert [(r["direction"], r["type"]) for r in rows] == [
        ("out", "part_of"), ("out", "depends_on"),
        ("in", "succeeds"), ("in", "conflicts_with")]
    assert rows[1]["state"] == "satisfied"
    assert rows[0]["intent"] == {"id": "c", "what": "wc", "status": "open"}
    assert rows[2]["intent"]["id"] == "d"


def test_view_skips_dangling_and_unrelated():
    g = mk(a=("open", [("depends_on", "zzz")]), b=("open", []))
    assert ir.view(g, "a") == []
    assert ir.view(g, "b") == []


def test_violation_basic():
    g = mk(a=("open", []), b=("open", []))
    assert ir.violation(g, "a", "bogus", "b")[0] == "INVALID_INPUT"
    assert ir.violation(g, "a", "part_of", "a")[0] == "INVALID_RELATION"
    assert ir.violation(g, "a", "part_of", "x")[0] == "OBJECT_NOT_FOUND"
    assert ir.violation(g, "a", "part_of", "b") is None


def test_violation_duplicate_pair_any_direction():
    g = mk(a=("open", [("depends_on", "b")]), b=("open", []))
    code, msg = ir.violation(g, "b", "conflicts_with", "a")
    assert code == "INVALID_RELATION"
    assert "already related" in msg and "unrelate b a" in msg


def test_withdrawn_does_not_block():
    g = mk(a=("open", []), b=("open", []))
    g["a"]["relations"].append({"type": "depends_on", "intent": "b", "removed_at": "t"})
    assert ir.violation(g, "a", "succeeds", "b") is None


def test_second_parent_rejected():
    g = mk(a=("open", [("part_of", "b")]), b=("open", []), c=("open", []))
    assert "already has a parent" in ir.violation(g, "a", "derived_from", "c")[1]


def test_part_of_ended_target():
    g = mk(a=("open", []), b=("done", []))
    assert "ended" in ir.violation(g, "a", "part_of", "b")[1]
    assert ir.violation(g, "a", "derived_from", "b") is None


@pytest.mark.parametrize("kind", ["depends_on", "succeeds", "part_of"])
def test_cycle(kind):
    g = mk(a=("open", []), b=("open", [(kind, "c")]), c=("open", [(kind, "a")]))
    code, msg = ir.violation(g, "a", kind, "b")
    assert code == "INVALID_RELATION" and "cycle" in msg


def test_cycle_across_parent_types():
    g = mk(a=("open", [("part_of", "b")]),
           b=("open", [("derived_from", "c")]),
           c=("open", []))
    code, msg = ir.violation(g, "c", "part_of", "a")
    assert code == "INVALID_RELATION" and "cycle" in msg


def test_families_independent():
    g = mk(a=("open", []), b=("open", [("depends_on", "c")]), c=("open", []))
    assert ir.violation(g, "c", "succeeds", "a") is None
    assert ir.violation(g, "c", "conflicts_with", "a") is None


def test_reachability_diamond_no_cycle():
    g = mk(a=("open", [("depends_on", "b"), ("depends_on", "c")]),
           b=("open", [("depends_on", "d")]),
           c=("open", [("depends_on", "d")]),
           d=("open", []), z=("open", []))
    assert ir.violation(g, "z", "depends_on", "a") is None
    assert "cycle" in ir.violation(g, "d", "depends_on", "a")[1]


def test_graph_issues_clean():
    g = mk(a=("open", [("part_of", "b")]), b=("open", []))
    assert ir.graph_issues(g) == []


def test_graph_issues_self_and_missing():
    g = mk(a=("open", [("depends_on", "a"), ("depends_on", "zz")]))
    assert ir.graph_issues(g) == [("a", "Relates to itself.")]


def test_graph_issues_duplicate_and_two_parents():
    g = mk(a=("open", [("part_of", "b"), ("derived_from", "c")]),
           b=("open", [("depends_on", "a")]), c=("open", []))
    msgs = ir.graph_issues(g)
    assert ("a", "Has more than one parent intent.") in msgs
    assert ("b", "Has more than one active relation with a.") in msgs


def test_graph_issues_cycle():
    g = mk(a=("open", [("depends_on", "b")]), b=("open", [("depends_on", "a")]))
    issues = ir.graph_issues(g)
    subs = {i for i, m in issues if "cycle" in m}
    assert subs == {"a", "b"}
    assert any("depends on" in m for _, m in issues)


def test_graph_issues_parent_cycle_message():
    g = mk(a=("open", [("part_of", "b")]), b=("open", [("derived_from", "a")]))
    msgs = [m for _, m in ir.graph_issues(g) if "cycle" in m]
    assert msgs and "derived from / part of" in msgs[0]


def test_attention_states():
    assert "blocked" in ir.ATTENTION_STATES
    assert "in_progress" not in ir.ATTENTION_STATES
