# tests/test_intent_relations.py
import pytest
import intent_relations as ir


def mk(id, status="open", what=None, rels=None):
    d = {"id": id, "status": status, "what": what or id}
    if rels is not None:
        d["relations"] = rels
    return d


def rel(kind, target, **kw):
    return {"type": kind, "intent": target, **kw}


def graph(*items):
    return {i["id"]: i for i in items}


# ---- helpers
def test_words():
    assert ir.words("part_of") == "part of"


def test_active_entries_filters_removed_and_missing():
    assert ir.active_entries({}) == []
    assert ir.active_entries({"relations": None}) == []
    i = {"relations": [rel("part_of", "b"), rel("depends_on", "c", removed_at="x")]}
    assert ir.active_entries(i) == [rel("part_of", "b")]


def test_active_relations():
    g = graph(mk("a", rels=[rel("part_of", "b"), rel("succeeds", "c", removed_at="t")]), mk("b"))
    assert list(ir.active_relations(g)) == [("a", "part_of", "b")]


# ---- state
@pytest.mark.parametrize("s,t,exp", [
    ("done", "open", "done"),
    ("done", "done", "done"),
    ("cancelled", "open", "dropped"),
    ("open", "done", "orphaned"),
    ("open", "cancelled", "orphaned"),
    ("open", "open", "in_progress"),
])
def test_state_part_of(s, t, exp):
    assert ir.state("part_of", {"status": s}, {"status": t}) == exp


def test_state_derived_from_none():
    assert ir.state("derived_from", {"status": "open"}, {"status": "done"}) is None


@pytest.mark.parametrize("t,exp", [("done", "handed_over"), ("cancelled", "handed_over"), ("open", "pending")])
def test_state_succeeds(t, exp):
    assert ir.state("succeeds", {"status": "open"}, {"status": t}) == exp


@pytest.mark.parametrize("t,exp", [("done", "satisfied"), ("cancelled", "broken"), ("open", "blocked"), (None, "blocked")])
def test_state_depends_on(t, exp):
    assert ir.state("depends_on", {"status": "open"}, {"status": t}) == exp


@pytest.mark.parametrize("s,t,exp", [
    ("open", "open", "unresolved"),
    ("done", "open", "resolved"),
    ("open", "cancelled", "resolved"),
])
def test_state_conflicts(s, t, exp):
    assert ir.state("conflicts_with", {"status": s}, {"status": t}) == exp


def test_attention_states_cover_problem_states():
    assert {"orphaned", "pending", "blocked", "broken", "unresolved"} == ir.ATTENTION_STATES


# ---- view
def test_view_both_directions_and_states():
    g = graph(
        mk("a", rels=[rel("depends_on", "b")]),
        mk("b", "done", what="B"),
        mk("c", rels=[rel("part_of", "a")]),
    )
    rows = ir.view(g, "a")
    assert [(r["direction"], r["type"]) for r in rows] == [("out", "depends_on"), ("in", "part_of")]
    assert rows[0]["state"] == "satisfied"
    assert rows[0]["intent"] == {"id": "b", "what": "B", "status": "done"}
    assert rows[1]["intent"]["id"] == "c"
    assert rows[1]["state"] == "in_progress"


def test_view_sorted_by_type_order():
    g = graph(
        mk("a", rels=[rel("conflicts_with", "b"), rel("depends_on", "c"), rel("part_of", "d")]),
        mk("b"), mk("c"), mk("d"),
    )
    assert [r["type"] for r in ir.view(g, "a")] == ["part_of", "depends_on", "conflicts_with"]


def test_view_skips_removed_dangling_and_unrelated():
    g = graph(
        mk("a", rels=[rel("part_of", "zzz"), rel("depends_on", "b", removed_at="t")]),
        mk("b"), mk("x", rels=[rel("depends_on", "b")]),
    )
    assert ir.view(g, "a") == []
    assert len(ir.view(g, "b")) == 1


# ---- violation
def test_violation_unknown_type():
    assert ir.violation({}, "a", "bogus", "b")[0] == "INVALID_INPUT"


def test_violation_self():
    g = graph(mk("a"))
    assert ir.violation(g, "a", "depends_on", "a")[0] == "INVALID_RELATION"


def test_violation_missing_target():
    g = graph(mk("a"))
    assert ir.violation(g, "a", "depends_on", "b")[0] == "OBJECT_NOT_FOUND"


def test_violation_ok():
    g = graph(mk("a"), mk("b"))
    for k in ir.RELATION_TYPES:
        assert ir.violation(g, "a", k, "b") is None


def test_violation_duplicate_pair_either_direction():
    g = graph(mk("a", rels=[rel("depends_on", "b")]), mk("b"))
    for subj, tgt in (("a", "b"), ("b", "a")):
        code, msg = ir.violation(g, subj, "conflicts_with", tgt)
        assert code == "INVALID_RELATION"
        assert "already related" in msg and "unrelate" in msg


def test_withdrawn_relation_does_not_block():
    g = graph(mk("a", rels=[rel("depends_on", "b", removed_at="t")]), mk("b"))
    assert ir.violation(g, "b", "succeeds", "a") is None


def test_violation_second_parent():
    g = graph(mk("a", rels=[rel("part_of", "b")]), mk("b"), mk("c"))
    code, msg = ir.violation(g, "a", "derived_from", "c")
    assert code == "INVALID_RELATION" and "parent" in msg


def test_removed_parent_allows_new():
    g = graph(mk("a", rels=[rel("part_of", "b", removed_at="t")]), mk("b"), mk("c"))
    assert ir.violation(g, "a", "part_of", "c") is None


def test_part_of_ended_target():
    for st in ("done", "cancelled"):
        g = graph(mk("a"), mk("b", st))
        assert "ended" in ir.violation(g, "a", "part_of", "b")[1]


def test_derived_from_ended_target_allowed():
    g = graph(mk("a"), mk("b", "done"))
    assert ir.violation(g, "a", "derived_from", "b") is None


def test_cycle_detection_transitive():
    g = graph(mk("a", rels=[rel("depends_on", "b")]),
              mk("b", rels=[rel("depends_on", "c")]), mk("c"))
    code, msg = ir.violation(g, "c", "depends_on", "a")
    assert code == "INVALID_RELATION" and "cycle" in msg


def test_cycle_parent_family_mixed_types():
    g = graph(mk("a"), mk("b", rels=[rel("derived_from", "c")]), mk("c", rels=[rel("part_of", "a")]))
    assert "cycle" in ir.violation(g, "a", "part_of", "b")[1]


def test_no_cycle_across_families():
    g = graph(mk("a", rels=[rel("depends_on", "b")]), mk("b", rels=[rel("succeeds", "c")]), mk("c"))
    assert ir.violation(g, "c", "succeeds", "a") is None


def test_conflicts_exempt_from_cycles():
    g = graph(mk("a", rels=[rel("conflicts_with", "b")]), mk("b"), mk("c"))
    assert ir.violation(g, "c", "conflicts_with", "a") is None


def test_diamond_is_not_a_cycle():
    g = graph(
        mk("a", rels=[rel("depends_on", "b"), rel("depends_on", "c")]),
        mk("b", rels=[rel("depends_on", "d")]),
        mk("c", rels=[rel("depends_on", "d")]),
        mk("d"), mk("e"),
    )
    assert ir.violation(g, "e", "depends_on", "a") is None
    assert "cycle" in ir.violation(g, "d", "depends_on", "a")[1]
    assert ir.graph_issues(g) == []


# ---- graph_issues
def test_clean_graph():
    g = graph(mk("a", rels=[rel("part_of", "b")]), mk("b"))
    assert ir.graph_issues(g) == []


def test_issue_self():
    g = graph(mk("a", rels=[rel("depends_on", "a")]))
    assert ir.graph_issues(g) == [("a", "Relates to itself.")]


def test_issue_dangling_ignored():
    g = graph(mk("a", rels=[rel("depends_on", "x")]))
    assert ir.graph_issues(g) == []


def test_issue_duplicate_pair():
    g = graph(mk("a", rels=[rel("depends_on", "b")]), mk("b", rels=[rel("conflicts_with", "a")]))
    issues = ir.graph_issues(g)
    assert any("more than one active relation" in m for _, m in issues)


def test_issue_two_parents():
    g = graph(mk("a", rels=[rel("part_of", "b"), rel("derived_from", "c")]), mk("b"), mk("c"))
    assert ("a", "Has more than one parent intent.") in ir.graph_issues(g)


def test_issue_cycle_reported_for_each_member():
    g = graph(mk("a", rels=[rel("succeeds", "b")]), mk("b", rels=[rel("succeeds", "a")]))
    issues = ir.graph_issues(g)
    cyc = [(i, m) for i, m in issues if "cycle" in m]
    assert sorted(i for i, _ in cyc) == ["a", "b"]
    assert all("succeeds" in m for _, m in cyc)


def test_issue_cycle_message_parent_family():
    g = graph(mk("a", rels=[rel("part_of", "b")]), mk("b", rels=[rel("derived_from", "a")]))
    msgs = [m for _, m in ir.graph_issues(g) if "cycle" in m]
    assert msgs and "derived from / part of" in msgs[0]


def test_removed_relations_ignored_in_issues():
    g = graph(mk("a", rels=[rel("succeeds", "b")]), mk("b", rels=[rel("succeeds", "a", removed_at="t")]))
    assert ir.graph_issues(g) == []
