# tests/test_trace2task_experience_runtime.py
import copy

import pytest

from trace2task_experience_runtime import known_state_ids, project_experience


def make_source(with_guidance=True):
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
                    {"id": "x2", "source_state_id": "s1", "target_type": "terminal", "target_id": "tm1"},
                    {"id": "x3", "source_state_id": "s2", "target_type": "state", "target_id": "s3"},
                ],
                "terminals": [
                    {"id": "tm1", "name": "End"},
                    {"id": "tm2", "name": "Other"},
                ],
            },
        },
    }
    if with_guidance:
        src["human_guidance"] = {
            "revision": 3,
            "summary": "sum",
            "rules": [
                {"id": "r1", "scope": {"type": "global"}},
                {"id": "r2", "scope": {"type": "state", "id": "s1"}},
                {"id": "r3", "scope": {"type": "state", "id": "s2"}},
                {"id": "r4", "scope": {"type": "transition", "id": "x1"}},
                {"id": "r5", "scope": {"type": "transition", "id": "x3"}},
                {"id": "r6", "scope": {"type": "terminal", "id": "tm1"}},
                {"id": "r7", "scope": {"type": "terminal", "id": "tm2"}},
            ],
        }
    return src


def rule_ids(p):
    return [r["id"] for r in p["human_guidance"]["rules"]]


def test_none():
    assert project_experience(None) is None
    assert known_state_ids(None) == set()


def test_trace_sequence_copy():
    s = {"kind": "trace_sequence", "steps": [1]}
    p = project_experience(s)
    assert p == s and p is not s
    assert known_state_ids(s) == set()


def test_default_entry():
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
    assert [t["id"] for t in p["candidate_terminals"]] == ["tm1"]
    assert rule_ids(p) == ["r1", "r2", "r4", "r6"]
    assert p["human_guidance"]["revision"] == 3
    assert p["human_guidance"]["summary"] == "sum"


def test_valid_hint():
    p = project_experience(make_source(), "s2")
    assert p["candidate_state"]["id"] == "s2"
    assert [s["id"] for s in p["nearby_states"]] == ["s3"]
    assert p["candidate_terminals"] == []
    assert rule_ids(p) == ["r1", "r3", "r5"]


def test_invalid_hint_falls_back_to_entry():
    p = project_experience(make_source(), "bogus")
    assert p["candidate_state"]["id"] == "s1"


def test_none_hint_uses_entry():
    assert project_experience(make_source(), None)["candidate_state"]["id"] == "s1"


def test_unknown_hint():
    p = project_experience(make_source(), "unknown")
    assert p["candidate_state"] is None
    assert p["nearby_states"] == []
    assert p["outgoing_transitions"] == []
    assert p["candidate_terminals"] == []
    assert rule_ids(p) == ["r1"]
    assert len(p["state_index"]) == 3


def test_state_without_outgoing():
    p = project_experience(make_source(), "s3")
    assert p["candidate_state"]["id"] == "s3"
    assert p["outgoing_transitions"] == []
    assert rule_ids(p) == ["r1"]


def test_no_guidance():
    p = project_experience(make_source(False))
    assert p["human_guidance"] is None


def test_guidance_missing_summary():
    s = make_source()
    del s["human_guidance"]["summary"]
    assert project_experience(s)["human_guidance"]["summary"] == ""


def test_empty_rules():
    s = make_source()
    s["human_guidance"]["rules"] = []
    assert project_experience(s)["human_guidance"]["rules"] == []


def test_does_not_mutate():
    s = make_source()
    before = copy.deepcopy(s)
    project_experience(s, "s2")
    assert s == before


def test_known_state_ids():
    assert known_state_ids(make_source()) == {"s1", "s2", "s3"}


def test_missing_semantic_raises():
    with pytest.raises(KeyError):
        project_experience({"task_id": "x"})
