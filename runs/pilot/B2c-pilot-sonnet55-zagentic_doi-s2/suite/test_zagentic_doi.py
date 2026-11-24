# tests/test_zagentic_doi.py
import pytest
import zagentic_doi as z


class G:
    def __init__(self, nodes, edges=(), parent=None, layer=None, debt=None):
        # edges: (a, b) means a blocks b  (a is predecessor of b)
        self.nodes = {n["id"]: n for n in nodes}
        self.adj = {}
        self.pred = {}
        self.succ = {}
        for a, b in edges:
            self.adj.setdefault(a, []).append(b)
            self.adj.setdefault(b, []).append(a)
            self.pred.setdefault(b, []).append(a)
            self.succ.setdefault(a, set()).add(b)
        self.parent = parent or {}
        self.layer = layer or {}
        self.debt = debt or {}


def N(i, status="pending", rounds=1):
    return {"id": i, "status": status, "rounds": rounds}


def test_weights_sum_and_thresholds():
    assert sum(z.WEIGHTS.values()) == pytest.approx(1.0)
    t = z.THRESHOLDS
    assert t["overview"] > t["neighborhood"] > t["expand"]


def test_bfs_hop():
    adj = {"a": ["b"], "b": ["c"]}
    assert z.bfs_hop("a", adj) == {"a": 0, "b": 1, "c": 2}
    assert z.bfs_hop("x", {}) == {"x": 0}


def test_rev_bfs_handles_cycle():
    pred = {"a": ["b"], "b": ["a"]}
    assert z.rev_bfs("a", pred) == {"a": 0, "b": 1}


def test_recency():
    assert z.recency({"status": "in_progress", "rounds": 1}) == pytest.approx(0.87)
    assert z.recency({"status": "blocked", "rounds": 1}) == pytest.approx(0.62)
    assert z.recency({"status": "completed"}) == pytest.approx(0.32)
    assert z.recency({"status": "x", "rounds": 100}) == pytest.approx(0.25)
    assert z.recency({"status": "in_progress", "rounds": 100}) == pytest.approx(0.95)
    assert z.recency({"status": "in_progress", "rounds": 100}) <= 1.0


def test_doi_focus_is_one():
    g = G([N("a")])
    assert z.doi(g.nodes["a"], "a", {}, {}, g) == 1.0


def test_doi_bounds_and_completed_penalty():
    g = G([N("a"), N("b", "completed"), N("c", "pending")])
    hop = z.bfs_hop("a", g.adj)
    db = z.doi(g.nodes["b"], "a", hop, {}, g)
    dc = z.doi(g.nodes["c"], "a", hop, {}, g)
    assert 0 <= db <= 1 and 0 <= dc <= 1
    assert db < dc


def test_doi_siblings_and_debt_raise():
    g = G([N("a"), N("b"), N("c")], parent={"a": "p", "b": "p", "c": "q"},
          layer={"a": 1, "b": 1, "c": 2})
    hop = z.bfs_hop("a", g.adj)
    assert z.doi(g.nodes["b"], "a", hop, {}, g) > z.doi(g.nodes["c"], "a", hop, {}, g)
    g.debt["c"] = {"score": 1.0}
    base = z.doi(g.nodes["c"], "a", hop, {}, G([N("a"), N("c")]))
    assert z.doi(g.nodes["c"], "a", hop, {}, g) > base


def test_doi_blocking_pred_higher():
    g = G([N("a"), N("b"), N("c")], edges=[("b", "a")])
    hop = z.bfs_hop("a", g.adj)
    pd = z.rev_bfs("a", g.pred)
    assert z.doi(g.nodes["b"], "a", hop, pd, g) > z.doi(g.nodes["c"], "a", hop, pd, g)


def test_mandatory_set():
    g = G([N("f"), N("p"), N("s"), N("d"), N("o"), N("par"), N("gp")],
          edges=[("p", "f"), ("f", "s")],
          parent={"f": "par", "par": "gp"},
          debt={"d": {"level": "high", "score": 1}, "o": {"level": "low"}})
    pd = z.rev_bfs("f", g.pred)
    m = z.mandatory_set("f", pd, g)
    assert m == {"f", "p", "s", "d", "par", "gp"}


def test_mandatory_parent_cycle_terminates():
    g = G([N("a"), N("b")], parent={"a": "b", "b": "a"})
    m = z.mandatory_set("a", {}, g)
    assert m == {"a", "b"}


def test_theta_presets_small_graph():
    g = G([N("a")])
    assert z.theta_presets("a", g) == z.THRESHOLDS


def test_theta_presets_ordered():
    nodes = [N("n%d" % i, "completed" if i % 2 else "pending") for i in range(20)]
    g = G([N("f")] + nodes, edges=[("f", "n%d" % i) for i in range(0, 20, 5)])
    t = z.theta_presets("f", g)
    assert t["overview"] >= t["neighborhood"] >= t["expand"]


def test_select_basic():
    g = G([N("f", "in_progress"), N("p"), N("s"), N("x")],
          edges=[("p", "f"), ("f", "s")])
    r = z.select("f", 0.0, g)
    assert r["lod"]["f"] == "L2"
    assert r["lod"]["p"] == "L1" and r["lod"]["s"] == "L1"
    assert r["mandatory"] <= set(r["shown"])
    assert r["used"] <= z.BUDGET
    assert r["budget_overflow"] == 0


def test_select_high_theta_compresses():
    g = G([N("f"), N("x"), N("y")])
    r = z.select("f", 2.0, g)
    assert r["lod"]["x"] == "COMPRESSED" and r["lod"]["y"] == "COMPRESSED"
    assert r["theta_folded"] == 2 and r["budget_folded"] == 0
    assert r["shown"] == ["f"]


def test_select_budget_fold_reported():
    nodes = [N("n%d" % i) for i in range(100)]
    g = G([N("f")] + nodes)
    r = z.select("f", 0.0, g)
    assert r["used"] <= z.BUDGET
    assert r["budget_folded"] > 0
    assert len(r["compressed"]) == r["theta_folded"] + r["budget_folded"]
    assert len(r["lod"]) == 101


def test_select_overflow_reported():
    preds = [N("p%d" % i) for i in range(30)]
    g = G([N("f")] + preds, edges=[("p%d" % i, "f") for i in range(30)])
    r = z.select("f", 0.0, g)
    assert set(r["shown"]) == r["mandatory"]
    assert r["used"] == 4 + 30 * 2
    assert r["budget_overflow"] == r["used"] - z.BUDGET


def test_select_monotonic_lod():
    rank = {"COMPRESSED": 0, "L0": 1, "L1": 2, "L2": 3}
    nodes = [N("n%d" % i, ["pending", "blocked", "in_progress", "completed"][i % 4], i % 5)
             for i in range(40)]
    g = G([N("f")] + nodes, edges=[("f", "n%d" % i) for i in range(0, 40, 7)])
    r = z.select("f", 0.0, g)
    cand = [i for i in r["lod"] if i not in r["mandatory"]]
    for a in cand:
        for b in cand:
            if r["by_id"][a]["d"] > r["by_id"][b]["d"]:
                assert rank[r["lod"][a]] >= rank[r["lod"][b]]


def test_select_deterministic():
    nodes = [N("n%d" % i) for i in range(30)]
    g = G([N("f")] + nodes)
    assert z.select("f", 0.1, g)["lod"] == z.select("f", 0.1, g)["lod"]


def test_debt_constants():
    assert "kind" in z.DEBT_REQUIRED_FIELDS and "state" in z.DEBT_REQUIRED_FIELDS
    assert set(z.DEBT_KINDS) == {"gap", "todo", "risk", "sweep"}
    assert z.DEBT_SEVERITIES == ("high", "medium", "low")
    assert "open" in z.DEBT_STATES
