# tests/test_trace2task_experience_runtime.py
import copy

import pytest

from trace2task_experience_runtime import known_state_ids, project_experience


def make_source(guidance=True):
    src = {
        "task_id": "t1",
        "semantic": {
            "goal": "do it",
            "completion": "done when X",
            "state_graph": {
                "entry_state_id": "s1",
                "states": [
                    {"id": "s1", "name": "One", "visual_anchors": ["a"]},
                    {"id": "s2", "name": "Two", "visual_anchors": ["b"]},
                    {"id": "s3", "name": "Three", "visual_anchors": ["c"]},
                ],
                "transitions": [
                    {"id": "x1", "source_state_id": "s1", "target_type": "state", "target_id": "s2"},
                    {"id": "x2", "source_state_id": "s1", "target_type": "terminal", "target_id": "done"},
                    {"id": "x3", "source_state_id": "s2", "target_type": "state", "target_id": "s3"},
                ],
                "terminals": [
                    {"id": "done", "name": "Done"},
                    {"id": "fail", "name": "Fail"},
                ],
            },
        },
    }
    if guidance:
        src["human_guidance"] = {
            "revision": 4,
            "summary": "sum",
            "rules": [
                {"id": "g", "scope": {"type": "global"}},
                {"id": "rs1", "scope": {"type": "state", "id": "s1"}},
                {"id": "rs2", "scope": {"type": "state", "id": "s2"}},
                {"id": "rt1", "scope": {"type": "transition", "id": "x1"}},
                {"id": "rt3", "scope": {"type": "transition", "id": "x3"}},
                {"id": "rd", "scope": {"type": "terminal", "id": "done"}},
                {"id": "rf", "scope": {"type": "terminal", "id": "fail"}},
            ],
        }
    return src


def rule_ids(p):
    return [r["id"] for r in p["human_guidance"]["rules"]]


def test_none():
    assert project_experience(None) is None
    assert known_state_ids(None) == set()


def test_trace_sequence_passthrough_copy():
    src = {"kind": "trace_sequence", "steps": [1]}
    out = project_experience(src, "x")
    assert out == src and out is not src
    assert known_state_ids(src) == set()


def test_default_entry_state():
    p = project_experience(make_source())
    assert p["candidate_state"]["id"] == "s1"
    assert p["candidate_is_unverified"] is True
    assert p["task_id"] == "t1"
    assert p["goal"] == "do it"
    assert p["completion"] == "done when X"
    assert [s["id"] for s in p["state_index"]] == ["s1", "s2", "s3"]
    assert p["state_index"][0] == {"id": "s1", "name": "One", "visual_anchors": ["a"]}
    assert [s["id"] for s in p["nearby_states"]] == ["s2"]
    assert [t["id"] for t in p["outgoing_transitions"]] == ["x1", "x2"]
    assert [t["id"] for t in p["candidate_terminals"]] == ["done"]


def test_valid_hint():
    p = project_experience(make_source(), "s2")
    assert p["candidate_state"]["id"] == "s2"
    assert [s["id"] for s in p["nearby_states"]] == ["s3"]
    assert p["candidate_terminals"] == []


def test_invalid_hint_falls_back_to_entry():
    assert project_experience(make_source(), "zzz")["candidate_state"]["id"] == "s1"
    assert project_experience(make_source(), None)["candidate_state"]["id"] == "s1"


def test_unknown_hint():
    p = project_experience(make_source(), "unknown")
    assert p["candidate_state"] is None
    assert p["outgoing_transitions"] == []
    assert p["nearby_states"] == []
    assert p["candidate_terminals"] == []
    assert rule_ids(p) == ["g"]


def test_rule_scoping_entry():
    p = project_experience(make_source())
    assert rule_ids(p) == ["g", "rs1", "rt1", "rd"]
    assert p["human_guidance"]["revision"] == 4
    assert p["human_guidance"]["summary"] == "sum"


def test_rule_scoping_s2():
    assert rule_ids(project_experience(make_source(), "s2")) == ["g", "rs2", "rt3"]


def test_no_guidance():
    p = project_experience(make_source(guidance=False))
    assert p["human_guidance"] is None


def test_missing_summary_default():
    s = make_source()
    del s["human_guidance"]["summary"]
    assert project_experience(s)["human_guidance"]["summary"] == ""


def test_known_state_ids():
    assert known_state_ids(make_source()) == {"s1", "s2", "s3"}


def test_no_mutation():
    s = make_source()
    c = copy.deepcopy(s)
    project_experience(s, "s2")
    assert s == c


def test_missing_semantic_raises():
    with pytest.raises(KeyError):
        project_experience({"task_id": "x"})
