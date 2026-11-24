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


def graph(*intents):
    return {i["id"]: i for i in intents}


# ---- helpers
def test_words():
    assert ir.words("part_of") == "part of"
    assert ir.words("x") == "x"


def test_active_entries():
    assert ir.active_entries({}) == []
    assert ir.active_entries({"relations": None}) == []
    a, b = rel("part_of", "x"), rel("succeeds", "y", removed_at="t")
    assert ir.active_entries({"relations": [a, b]}) == [a]


def test_active_relations():
    g = graph(mk("a", rels=[rel("depends_on", "b"), rel("succeeds", "c", removed_at="t")]), mk("b"))
    assert list(ir.active_relations(g)) == [("a", "depends_on", "b")]


# ---- state
@pytest.mark.parametrize("ss,ts,exp", [
    ("done", "open", "done"),
    ("done", "done", "done"),
    ("cancelled", "open", "dropped"),
    ("open", "done", "orphaned"),
    ("open", "cancelled", "orphaned"),
    ("open", "open", "in_progress"),
])
def test_state_part_of(ss, ts, exp):
    assert ir.state("part_of", {"status": ss}, {"status": ts}) == exp


@pytest.mark.parametrize("ts,exp", [
    ("done", "handed_over"), ("cancelled", "handed_over"),
    ("open", "pending"), (None, "pending")])
def test_state_succeeds(ts, exp):
    assert ir.state("succeeds", {"status": "open"}, {"status": ts}) == exp


@pytest.mark.parametrize("ts,exp", [
    ("done", "satisfied"), ("cancelled", "broken"),
    ("open", "blocked"), (None, "blocked")])
def test_state_depends_on(ts, exp):
    assert ir.state("depends_on", {"status": "open"}, {"status": ts}) == exp


@pytest.mark.parametrize("ss,ts,exp", [
    ("open", "open", "unresolved"),
    ("done", "open", "resolved"),
    ("open", "cancelled", "resolved"),
])
def test_state_conflicts(ss, ts, exp):
    assert ir.state("conflicts_with", {"status": ss}, {"status": ts}) == exp


def test_state_derived_from_none():
    assert ir.state("derived_from", {"status": "open"}, {"status": "open"}) is None
    assert ir.state("bogus", {}, {}) is None


def test_attention_states_constant():
    assert "pending" in ir.ATTENTION_STATES
    assert "in_progress" not in ir.ATTENTION_STATES


# ---- view
def test_view_both_directions_and_fields():
    g = graph(
        mk("a", rels=[rel("depends_on", "b")]),
        mk("b", what="B goal", status="done"),
        mk("c", rels=[rel("part_of", "a")]),
    )
    rows = ir.view(g, "a")
    assert [(r["type"], r["direction"]) for r in rows] == [("depends_on", "out"), ("part_of", "in")]
    assert rows[0]["intent"] == {"id": "b", "what": "B goal", "status": "done"}
    assert rows[0]["state"] == "satisfied"
    assert rows[1]["intent"]["id"] == "c"
    assert rows[1]["state"] == "in_progress"


def test_view_sorting_type_order():
    g = graph(
        mk("a", rels=[rel("conflicts_with", "b"), rel("depends_on", "c"), rel("part_of", "d")]),
        mk("b"), mk("c"), mk("d"),
        mk("e", rels=[rel("part_of", "a")]),
        mk("f", rels=[rel("derived_from", "a")]),
    )
    rows = ir.view(g, "a")
    assert [(r["direction"], r["type"]) for r in rows] == [
        ("out", "part_of"), ("out", "depends_on"), ("out", "conflicts_with"),
        ("in", "part_of"), ("in", "derived_from")]


def test_view_skips_withdrawn_missing_and_unrelated():
    g = graph(
        mk("a", rels=[rel("depends_on", "b", removed_at="t"), rel("succeeds", "ghost")]),
        mk("b"), mk("z", rels=[rel("depends_on", "b")]),
    )
    assert ir.view(g, "a") == []
    assert len(ir.view(g, "b")) == 1


def test_view_missing_what():
    g = graph(mk("a", rels=[rel("succeeds", "b")]), {"id": "b", "status": "open"})
    assert ir.view(g, "a")[0]["intent"]["what"] is None


# ---- violation
def test_violation_unknown_type():
    assert ir.violation({}, "a", "nope", "b")[0] == "INVALID_INPUT"


def test_violation_self():
    g = graph(mk("a"))
    assert ir.violation(g, "a", "depends_on", "a")[0] == "INVALID_RELATION"


def test_violation_target_missing():
    g = graph(mk("a"))
    assert ir.violation(g, "a", "depends_on", "x")[0] == "OBJECT_NOT_FOUND"


def test_violation_ok():
    g = graph(mk("a"), mk("b"))
    for k in ir.RELATION_TYPES:
        assert ir.violation(g, "a", k, "b") is None


def test_violation_duplicate_pair_either_direction():
    g = graph(mk("a", rels=[rel("depends_on", "b")]), mk("b"))
    for s, t in (("a", "b"), ("b", "a")):
        code, msg = ir.violation(g, s, "conflicts_with", t)
        assert code == "INVALID_RELATION"
        assert "already related" in msg
        assert "a depends on b" in msg
        assert f"itt intent unrelate {s} {t}" in msg


def test_violation_withdrawn_pair_allowed():
    g = graph(mk("a", rels=[rel("depends_on", "b", removed_at="t")]), mk("b"))
    assert ir.violation(g, "a", "succeeds", "b") is None


def test_violation_second_parent():
    g = graph(mk("a", rels=[rel("part_of", "b")]), mk("b"), mk("c"))
    code, msg = ir.violation(g, "a", "derived_from", "c")
    assert code == "INVALID_RELATION" and "already has a parent" in msg


def test_violation_withdrawn_parent_ok():
    g = graph(mk("a", rels=[rel("part_of", "b", removed_at="t")]), mk("b"), mk("c"))
    assert ir.violation(g, "a", "part_of", "c") is None


def test_violation_part_of_ended_target():
    for st in ("done", "cancelled"):
        g = graph(mk("a"), mk("b", st))
        code, msg = ir.violation(g, "a", "part_of", "b")
        assert code == "INVALID_RELATION" and "ended" in msg


def test_violation_derived_from_ended_ok():
    g = graph(mk("a"), mk("b", "done"))
    assert ir.violation(g, "a", "derived_from", "b") is None


def test_violation_cycles():
    g = graph(
        mk("a", rels=[rel("depends_on", "b")]),
        mk("b", rels=[rel("depends_on", "c")]),
        mk("c"),
    )
    code, msg = ir.violation(g, "c", "depends_on", "a")
    assert code == "INVALID_RELATION" and "cycle" in msg
    assert ir.violation(g, "a", "depends_on", "c") is None


def test_violation_diamond_no_cycle():
    g = graph(
        mk("a", rels=[rel("depends_on", "b"), rel("depends_on", "c")]),
        mk("b", rels=[rel("depends_on", "d")]),
        mk("c", rels=[rel("depends_on", "d")]),
        mk("d"), mk("x"),
    )
    assert ir.violation(g, "x", "depends_on", "a") is None
    code, msg = ir.violation(g, "d", "depends_on", "a")
    assert "cycle" in msg


def test_violation_parent_cycle_across_types():
    g = graph(mk("a"), mk("b", rels=[rel("derived_from", "a")]),
              mk("c", rels=[rel("part_of", "b")]))
    code, msg = ir.violation(g, "a", "part_of", "c")
    assert code == "INVALID_RELATION" and "cycle" in msg


def test_violation_succeeds_cycle():
    g = graph(mk("a", rels=[rel("succeeds", "b")]), mk("b"), mk("c", rels=[rel("succeeds", "a")]))
    assert "cycle" in ir.violation(g, "b", "succeeds", "c")[1]


def test_families_independent():
    g = graph(mk("a", rels=[rel("depends_on", "b")]), mk("b"), mk("c", rels=[rel("succeeds", "a")]))
    assert ir.violation(g, "b", "succeeds", "c") is None


def test_conflicts_symmetric_exempt():
    g = graph(mk("a", rels=[rel("conflicts_with", "b")]), mk("b"), mk("c"))
    assert ir.violation(g, "b", "conflicts_with", "c") is None


# ---- graph_issues
def test_graph_issues_clean():
    g = graph(mk("a", rels=[rel("part_of", "b")]), mk("b"))
    assert ir.graph_issues(g) == []


def test_graph_issues_self():
    g = graph(mk("a", rels=[rel("depends_on", "a")]))
    assert ir.graph_issues(g) == [("a", "Relates to itself.")]


def test_graph_issues_missing_target_ignored():
    g = graph(mk("a", rels=[rel("depends_on", "ghost")]))
    assert ir.graph_issues(g) == []


def test_graph_issues_duplicate_pair():
    g = graph(mk("a", rels=[rel("depends_on", "b")]), mk("b", rels=[rel("conflicts_with", "a")]))
    issues = ir.graph_issues(g)
    assert ("b", "Has more than one active relation with a.") in issues


def test_graph_issues_two_parents():
    g = graph(mk("a", rels=[rel("part_of", "b"), rel("derived_from", "c")]), mk("b"), mk("c"))
    assert ("a", "Has more than one parent intent.") in ir.graph_issues(g)


def test_graph_issues_withdrawn_ignored():
    g = graph(mk("a", rels=[rel("part_of", "b", removed_at="t"), rel("part_of", "c")]), mk("b"), mk("c"))
    assert ir.graph_issues(g) == []


def test_graph_issues_cycle():
    g = graph(mk("a", rels=[rel("depends_on", "b")]), mk("b", rels=[rel("depends_on", "a")]))
    msgs = [(i, m) for i, m in ir.graph_issues(g) if "cycle" in m]
    assert {i for i, _ in msgs} == {"a", "b"}
    assert "depends on" in msgs[0][1]


def test_graph_issues_cycle_message_parent_family():
    g = graph(mk("a", rels=[rel("part_of", "b")]), mk("b", rels=[rel("derived_from", "c")]),
              mk("c", rels=[rel("part_of", "a")]))
    msgs = [m for i, m in ir.graph_issues(g) if "cycle" in m]
    assert len(msgs) == 3
    assert all("derived from / part of" in m for m in msgs)


def test_graph_issues_three_cycle_succeeds():
    g = graph(mk("a", rels=[rel("succeeds", "b")]), mk("b", rels=[rel("succeeds", "c")]),
              mk("c", rels=[rel("succeeds", "a")]))
    assert {i for i, m in ir.graph_issues(g) if "cycle" in m} == {"a", "b", "c"}
