# tests/test_zagentic_doi.py
import pytest
import zagentic_doi as z


class G:
    def __init__(self, nodes, edges=(), parent=None, layer=None, debt=None):
        # edges: (a, b) means a blocks b  -> adj a->b, pred b has a, succ a has b
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


def N(i, status="pending", rounds=1):
    return {"id": i, "status": status, "rounds": rounds}


def test_weights_sum():
    assert sum(z.WEIGHTS.values()) == pytest.approx(1.0)


def test_thresholds_strictly_decreasing():
    t = z.THRESHOLDS
    assert t["overview"] > t["neighborhood"] > t["expand"]


def test_bfs_hop():
    adj = {"a": ["b", "c"], "b": ["d"], "c": ["d"]}
    assert z.bfs_hop("a", adj) == {"a": 0, "b": 1, "c": 1, "d": 2}
    assert z.bfs_hop("x", {}) == {"x": 0}


def test_bfs_handles_cycle():
    assert z.bfs_hop("a", {"a": ["b"], "b": ["a"]}) == {"a": 0, "b": 1}


def test_rev_bfs():
    pred = {"c": ["b"], "b": ["a"]}
    assert z.rev_bfs("c", pred) == {"c": 0, "b": 1, "a": 2}


def test_recency_values():
    assert z.recency({"status": "in_progress", "rounds": 1}) == pytest.approx(0.87)
    assert z.recency({"status": "blocked"}) == pytest.approx(0.62)
    assert z.recency({"status": "completed", "rounds": 1}) == pytest.approx(0.32)
    assert z.recency({"status": "pending", "rounds": 1}) == pytest.approx(0.17)
    assert z.recency({"status": "in_progress", "rounds": 100}) == pytest.approx(0.95)
    assert z.recency({"status": "in_progress", "rounds": 100}) <= 1.0
    assert z.recency({"status": "pending", "rounds": None}) == pytest.approx(0.17)


def test_doi_focus_is_one():
    g = G([N("a")])
    assert z.doi(g.nodes["a"], "a", {"a": 0}, {"a": 0}, g) == 1.0


def test_doi_bounds_and_stability_penalty():
    g = G([N("f"), N("x", "completed")])
    hop = z.bfs_hop("f", g.adj)
    d = z.doi(g.nodes["x"], "f", hop, {"f": 0}, g)
    assert 0.0 <= d <= 1.0


def test_doi_blocking_pred_higher_than_unrelated():
    g = G([N("f"), N("p"), N("u")], edges=[("p", "f")])
    hop = z.bfs_hop("f", g.adj)
    pd = z.rev_bfs("f", g.pred)
    assert z.doi(g.nodes["p"], "f", hop, pd, g) > z.doi(g.nodes["u"], "f", hop, pd, g)


def test_doi_sibling_shared_context():
    g = G([N("r"), N("f"), N("s"), N("o")],
          parent={"f": "r", "s": "r", "o": "q"},
          layer={"f": 1, "s": 1, "o": 2})
    hop = z.bfs_hop("f", g.adj)
    assert z.doi(g.nodes["s"], "f", hop, {"f": 0}, g) > z.doi(g.nodes["o"], "f", hop, {"f": 0}, g)


def test_doi_debt_raises():
    g = G([N("f"), N("a"), N("b")], debt={"a": {"score": 1.0}})
    hop = z.bfs_hop("f", g.adj)
    assert z.doi(g.nodes["a"], "f", hop, {"f": 0}, g) > z.doi(g.nodes["b"], "f", hop, {"f": 0}, g)


def test_mandatory_set():
    g = G([N("f"), N("p"), N("s"), N("h"), N("u"), N("root"), N("mid")],
          edges=[("p", "f"), ("f", "s")],
          parent={"f": "mid", "mid": "root"},
          debt={"h": {"level": "high", "score": 1.0}, "u": {"level": "low", "score": .1}})
    pd = z.rev_bfs("f", g.pred)
    m = z.mandatory_set("f", pd, g)
    assert m == {"f", "p", "s", "h", "mid", "root"}


def test_mandatory_parent_cycle_terminates():
    g = G([N("f"), N("a")], parent={"f": "a", "a": "f"})
    m = z.mandatory_set("f", {"f": 0}, g)
    assert {"f", "a"} <= m


def test_theta_presets_empty_candidates():
    g = G([N("f")])
    assert z.theta_presets("f", g) == z.THRESHOLDS


def test_theta_presets_ordered():
    g = G([N("f")] + [N(f"n{i}", "in_progress" if i % 2 else "pending") for i in range(20)],
          edges=[("f", "n0"), ("n0", "n1")])
    t = z.theta_presets("f", g)
    assert t["overview"] >= t["neighborhood"] >= t["expand"]


def test_select_basic():
    g = G([N("f"), N("p"), N("s"), N("x")], edges=[("p", "f"), ("f", "s")])
    r = z.select("f", 0.0, g)
    assert r["lod"]["f"] == "L2"
    assert r["lod"]["p"] == "L1" and r["lod"]["s"] == "L1"
    assert r["mandatory"] <= set(r["shown"])
    assert r["budget_overflow"] == 0
    assert r["used"] <= z.BUDGET


def test_select_theta_high_compresses():
    g = G([N("f"), N("x"), N("y")])
    r = z.select("f", 2.0, g)
    assert set(r["compressed"]) == {"x", "y"}
    assert r["theta_folded"] == 2 and r["budget_folded"] == 0


def test_select_budget_folding_reported():
    g = G([N("f")] + [N(f"n{i}", "in_progress") for i in range(100)])
    r = z.select("f", 0.0, g)
    assert r["used"] <= z.BUDGET
    assert r["budget_folded"] > 0
    assert len(r["lod"]) == 101
    assert r["theta_folded"] + r["budget_folded"] == len(r["compressed"])
    assert r["budget_overflow"] == 0


def test_select_mandatory_overflow_explicit():
    n = 20
    nodes = [N("f")] + [N(f"s{i}") for i in range(n)]
    g = G(nodes, edges=[("f", f"s{i}") for i in range(n)])
    r = z.select("f", 0.0, g)
    assert r["used"] == 4 + 2 * n
    assert r["budget_overflow"] == r["used"] - z.BUDGET > 0
    assert r["mandatory"] <= set(r["shown"])


def test_select_lod_monotonic_in_doi():
    nodes = [N("f")] + [N(f"n{i}", ["pending", "in_progress", "blocked", "completed"][i % 4], i % 7)
                        for i in range(30)]
    g = G(nodes, edges=[("f", "n0"), ("n1", "n2")])
    r = z.select("f", 0.0, g)
    rank = {"COMPRESSED": 0, "L0": 1, "L1": 2, "L2": 3}
    cand = [i for i in r["lod"] if i not in r["mandatory"]]
    for a in cand:
        for b in cand:
            if r["by_id"][a]["d"] > r["by_id"][b]["d"]:
                assert rank[r["lod"][a]] >= rank[r["lod"][b]]


def test_select_deterministic_and_shown_unique():
    g = G([N("f")] + [N(f"n{i}") for i in range(10)])
    a = z.select("f", 0.0, g)
    b = z.select("f", 0.0, g)
    assert a["lod"] == b["lod"]
    assert len(a["shown"]) == len(set(a["shown"]))


def test_schema_constants():
    assert set(z.DEBT_KINDS) == {"gap", "todo", "risk", "sweep"}
    assert "kind" in z.DEBT_REQUIRED_FIELDS and "state" in z.DEBT_REQUIRED_FIELDS
    assert z.DEBT_STATES[0] == "open"
    assert z.COST == {"L2": 4, "L1": 2, "L0": 1}
    assert z.BUDGET == 40
