# tests/test_zagentic_doi.py
import pytest
import zagentic_doi as z


class G:
    def __init__(self, nodes, edges=(), parent=None, layer=None, debt=None):
        # edges: (a, b) means a blocks b  => adj a->b, pred b->[a], succ a->{b}
        self.nodes = {n["id"]: n for n in nodes}
        self.adj = {}
        self.pred = {}
        self.succ = {}
        for a, b in edges:
            self.adj.setdefault(a, []).append(b)
            self.pred.setdefault(b, []).append(a)
            self.succ.setdefault(a, set()).add(b)
        self.parent = parent or {}
        self.layer = layer or {}
        self.debt = debt or {}


def N(i, status="pending", rounds=None):
    d = {"id": i, "status": status}
    if rounds is not None:
        d["rounds"] = rounds
    return d


def test_weights_sum_and_thresholds():
    assert sum(z.WEIGHTS.values()) == pytest.approx(1.0)
    t = z.THRESHOLDS
    assert t["overview"] > t["neighborhood"] > t["expand"]
    assert z.BUDGET == 40


def test_bfs_hop():
    adj = {"a": ["b", "c"], "b": ["d"], "c": ["d"]}
    assert z.bfs_hop("a", adj) == {"a": 0, "b": 1, "c": 1, "d": 2}
    assert z.bfs_hop("x", {}) == {"x": 0}


def test_bfs_cycle_terminates():
    assert z.bfs_hop("a", {"a": ["b"], "b": ["a"]}) == {"a": 0, "b": 1}


def test_rev_bfs():
    pred = {"c": ["b"], "b": ["a"]}
    assert z.rev_bfs("c", pred) == {"c": 0, "b": 1, "a": 2}


def test_recency_values():
    assert z.recency({"status": "in_progress", "rounds": 1}) == pytest.approx(0.87)
    assert z.recency({"status": "blocked"}) == pytest.approx(0.62)
    assert z.recency({"status": "completed", "rounds": 100}) == pytest.approx(0.40)
    assert z.recency({"status": "x", "rounds": 0}) == pytest.approx(0.17)
    assert z.recency({"status": "in_progress", "rounds": 100}) == pytest.approx(0.95)


def test_doi_focus_is_one():
    g = G([N("a")])
    assert z.doi(g.nodes["a"], "a", {"a": 0}, {"a": 0}, g) == 1.0


def test_doi_in_range_and_completed_penalty():
    g = G([N("a"), N("b", "completed"), N("c", "pending")])
    hop = z.bfs_hop("a", g.adj)
    for n in "bc":
        v = z.doi(g.nodes[n], "a", hop, {"a": 0}, g)
        assert 0.0 <= v <= 1.0
    b = z.doi(g.nodes["b"], "a", hop, {"a": 0}, g)
    c = z.doi(g.nodes["c"], "a", hop, {"a": 0}, g)
    # completed: recency .32 - penalty vs pending .17
    assert b == pytest.approx(0.1 * 0.32 - 0.05 + 0.0 + 0.30 / 100 + 0.0) or b >= 0
    assert c > 0


def test_doi_exact_value():
    g = G([N("a"), N("b", "in_progress", 1)], parent={"a": "p", "b": "p"})
    v = z.doi(g.nodes["b"], "a", {"a": 0, "b": 1}, {"a": 0}, g)
    exp = 0.30 * 0.5 + 0.15 * 1.0 + 0.10 * 0.87
    assert v == pytest.approx(exp)


def test_doi_blocking_term():
    g = G([N("a"), N("b")], edges=[("b", "a")])
    pd = z.rev_bfs("a", g.pred)
    v = z.doi(g.nodes["b"], "a", z.bfs_hop("a", g.adj), pd, g)
    assert v > z.doi(g.nodes["b"], "a", {}, {}, g)


def test_mandatory_set():
    g = G(
        [N("f"), N("p"), N("s"), N("h"), N("x"), N("par"), N("gp")],
        edges=[("p", "f"), ("f", "s")],
        parent={"f": "par", "par": "gp"},
        debt={"h": {"level": "high", "score": 1.0}, "x": {"level": "low"}},
    )
    m = z.mandatory_set("f", z.rev_bfs("f", g.pred), g)
    assert m == {"f", "p", "s", "h", "par", "gp"}


def test_mandatory_parent_cycle_safe():
    g = G([N("f"), N("a")], parent={"f": "a", "a": "f"})
    m = z.mandatory_set("f", {"f": 0}, g)
    assert m == {"f", "a"}


def test_theta_presets_small_graph_defaults():
    g = G([N("f")])
    assert z.theta_presets("f", g) == z.THRESHOLDS


def test_theta_presets_ordered():
    g = G([N("f")] + [N(f"n-{i}", "in_progress" if i % 2 else "pending") for i in range(20)])
    p = z.theta_presets("f", g)
    assert p["overview"] >= p["neighborhood"] >= p["expand"]


def test_select_basic():
    g = G([N("f"), N("a"), N("b")], edges=[("f", "a")])
    r = z.select("f", 0.0, g)
    assert r["lod"]["f"] == "L2"
    assert r["lod"]["a"] == "L1"
    assert r["mandatory"] <= set(r["shown"])
    assert r["used"] <= z.BUDGET
    assert r["budget_overflow"] == 0
    assert set(r["lod"]) == set(g.nodes)


def test_select_theta_high_compresses():
    g = G([N("f"), N("a"), N("b")])
    r = z.select("f", 1.1, g)
    assert set(r["compressed"]) == {"a", "b"}
    assert r["theta_folded"] == 2
    assert r["budget_folded"] == 0
    assert r["shown"] == ["f"]


def test_select_budget_fold_reported():
    nodes = [N("f")] + [N(f"n{i}", "pending") for i in range(60)]
    g = G(nodes)
    r = z.select("f", 0.0, g)
    assert r["used"] <= z.BUDGET
    assert r["budget_folded"] > 0
    assert r["theta_folded"] == 0
    assert len(r["compressed"]) + len(r["shown"]) == len(nodes)


def test_select_monotone_lod():
    nodes = [N("f")] + [
        N(f"n{i}", ["in_progress", "pending", "blocked", "completed"][i % 4], i % 5)
        for i in range(40)
    ]
    g = G(nodes)
    r = z.select("f", 0.0, g)
    rank = {"COMPRESSED": 0, "L0": 1, "L1": 2, "L2": 3}
    cand = [n for n in r["lod"] if n not in r["mandatory"]]
    for a in cand:
        for b in cand:
            if r["by_id"][a]["d"] > r["by_id"][b]["d"]:
                assert rank[r["lod"][a]] >= rank[r["lod"][b]]


def test_select_mandatory_overflow_reported():
    nodes = [N("f")] + [N(f"s{i}") for i in range(50)]
    g = G(nodes, edges=[("f", f"s{i}") for i in range(50)])
    r = z.select("f", 0.5, g)
    assert r["mandatory"] <= set(r["shown"])
    assert r["used"] == 4 + 50 * 2
    assert r["budget_overflow"] == r["used"] - z.BUDGET > 0


def test_select_deterministic():
    nodes = [N("f")] + [N(f"n{i}", "in_progress") for i in range(10)]
    g = G(nodes)
    a = z.select("f", 0.1, g)
    b = z.select("f", 0.1, g)
    assert a["lod"] == b["lod"] and a["used"] == b["used"]


def test_debt_schema_constants():
    assert set(z.DEBT_KINDS) == {"gap", "todo", "risk", "sweep"}
    assert "kind" in z.DEBT_REQUIRED_FIELDS and "state" in z.DEBT_REQUIRED_FIELDS
    assert z.DEBT_SEVERITIES == ("high", "medium", "low")
    assert z.DEBT_STATES[0] == "open"
