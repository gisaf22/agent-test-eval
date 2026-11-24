# tests/test_trace2task_experience_runtime.py
import copy

import pytest

from trace2task_experience_runtime import known_state_ids, project_experience


def make_source(with_guidance=True):
    src = {
        "task_id": "t1",
        "semantic": {
            "goal": "do it",
            "completion": "done",
            "state_graph": {
                "entry_state_id": "s1",
                "states": [
                    {"id": "s1", "name": "One", "visual_anchors": ["a"]},
                    {"id": "s2", "name": "Two", "visual_anchors": ["b"]},
                    {"id": "s3", "name": "Three", "visual_anchors": ["c"]},
                ],
                "transitions": [
                    {"id": "x1", "source_state_id": "s1",
                     "target_type": "state", "target_id": "s2"},
                    {"id": "x2", "source_state_id": "s1",
                     "target_type": "terminal", "target_id": "end"},
                    {"id": "x3", "source_state_id": "s2",
                     "target_type": "state", "target_id": "s3"},
                ],
                "terminals": [
                    {"id": "end", "name": "End"},
                    {"id": "other", "name": "Other"},
                ],
            },
        },
    }
    if with_guidance:
        src["human_guidance"] = {
            "revision": 3,
            "summary": "sum",
            "rules": [
                {"id": "g", "scope": {"type": "global"}},
                {"id": "rs1", "scope": {"type": "state", "id": "s1"}},
                {"id": "rs2", "scope": {"type": "state", "id": "s2"}},
                {"id": "rt1", "scope": {"type": "transition", "id": "x1"}},
                {"id": "rt3", "scope": {"type": "transition", "id": "x3"}},
                {"id": "re", "scope": {"type": "terminal", "id": "end"}},
                {"id": "ro", "scope": {"type": "terminal", "id": "other"}},
            ],
        }
    return src


def test_none():
    assert project_experience(None) is None
    assert project_experience(None, "s1") is None


def test_trace_sequence_copy():
    src = {"kind": "trace_sequence", "steps": [1]}
    out = project_experience(src)
    assert out == src and out is not src


def test_default_entry_state():
    out = project_experience(make_source())
    assert out["candidate_state"]["id"] == "s1"
    assert out["candidate_is_unverified"] is True
    assert out["task_id"] == "t1"
    assert out["goal"] == "do it"
    assert out["completion"] == "done"
    assert [t["id"] for t in out["outgoing_transitions"]] == ["x1", "x2"]
    assert [s["id"] for s in out["nearby_states"]] == ["s2"]
    assert [t["id"] for t in out["candidate_terminals"]] == ["end"]


def test_state_index():
    out = project_experience(make_source())
    assert out["state_index"] == [
        {"id": "s1", "name": "One", "visual_anchors": ["a"]},
        {"id": "s2", "name": "Two", "visual_anchors": ["b"]},
        {"id": "s3", "name": "Three", "visual_anchors": ["c"]},
    ]


def test_hint_valid():
    out = project_experience(make_source(), "s2")
    assert out["candidate_state"]["id"] == "s2"
    assert [t["id"] for t in out["outgoing_transitions"]] == ["x3"]
    assert [s["id"] for s in out["nearby_states"]] == ["s3"]
    assert out["candidate_terminals"] == []


def test_hint_invalid_falls_back_to_entry():
    assert project_experience(make_source(), "zzz")["candidate_state"]["id"] == "s1"


def test_hint_unknown():
    out = project_experience(make_source(), "unknown")
    assert out["candidate_state"] is None
    assert out["outgoing_transitions"] == []
    assert out["nearby_states"] == []
    assert out["candidate_terminals"] == []
    ids = [r["id"] for r in out["human_guidance"]["rules"]]
    assert ids == ["g"]


def test_guidance_filtering_entry():
    out = project_experience(make_source())
    g = out["human_guidance"]
    assert g["revision"] == 3 and g["summary"] == "sum"
    assert [r["id"] for r in g["rules"]] == ["g", "rs1", "rt1", "re"]


def test_guidance_filtering_s2():
    out = project_experience(make_source(), "s2")
    assert [r["id"] for r in out["human_guidance"]["rules"]] == ["g", "rs2", "rt3"]


def test_no_guidance():
    assert project_experience(make_source(False))["human_guidance"] is None


def test_summary_default():
    src = make_source()
    del src["human_guidance"]["summary"]
    assert project_experience(src)["human_guidance"]["summary"] == ""


def test_source_not_mutated():
    src = make_source()
    before = copy.deepcopy(src)
    project_experience(src, "s2")
    assert src == before


def test_known_state_ids():
    assert known_state_ids(None) == set()
    assert known_state_ids({"kind": "trace_sequence"}) == set()
    assert known_state_ids(make_source()) == {"s1", "s2", "s3"}


def test_missing_semantic_raises():
    with pytest.raises(KeyError):
        project_experience({"task_id": "x"})
