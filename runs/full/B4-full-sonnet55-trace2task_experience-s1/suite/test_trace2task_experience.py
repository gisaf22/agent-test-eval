# tests/test_trace2task_experience.py
import pytest

import trace2task_experience as m
from trace2task_experience import ExperienceMatch, route_experience


def task(path, task_id, confirmed=True, **kw):
    d = {"path": path, "task_id": task_id, "confirmed": confirmed}
    d.update(kw)
    return d


def test_to_payload():
    em = ExperienceMatch("p", "t", 1.5, 0.6, ("a", "b"), "r")
    assert em.to_payload() == {
        "task_path": "p",
        "task_id": "t",
        "score": 1.5,
        "confidence": 0.6,
        "matched_terms": ["a", "b"],
        "reason": "r",
    }


def test_frozen():
    em = ExperienceMatch("p", "t", 1.0, 0.6, (), "r")
    with pytest.raises(Exception):
        em.score = 2


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_empty_instruction(text):
    with pytest.raises(ValueError):
        route_experience(text, [task("a", "open_notepad")])


def test_no_confirmed():
    with pytest.raises(ValueError):
        route_experience("open notepad", [task("a", "open_notepad", confirmed=False)])
    with pytest.raises(ValueError):
        route_experience("open notepad", [])


def test_task_id_match():
    r = route_experience(
        "please open_notepad now",
        [task("a", "open_notepad"), task("b", "close_window")],
    )
    assert r.task_path == "a"
    assert r.task_id == "open_notepad"
    assert r.score >= 8.0
    assert any(t.startswith("任务名称:") for t in r.matched_terms)
    assert 0.5 < r.confidence <= 0.99
    assert "open_notepad" in r.reason


def test_unconfirmed_ignored():
    r = route_experience(
        "open_notepad",
        [task("a", "open_notepad", confirmed=False), task("b", "open_notepad")],
    )
    assert r.task_path == "b"


def test_low_score_rejected():
    with pytest.raises(ValueError):
        route_experience("zzzz qqqq", [task("a", "open_notepad")])


def test_ambiguous():
    with pytest.raises(ValueError):
        route_experience(
            "open_notepad",
            [task("a", "open_notepad"), task("b", "open_notepad")],
        )


def test_example_match_and_chinese():
    t = task(
        "a",
        "t1",
        experience_examples=["打开记事本"],
        experience_intent="记事本",
    )
    r = route_experience("帮我打开记事本", [t, task("b", "other")])
    assert r.task_path == "a"
    assert any(x.startswith("示例:") for x in r.matched_terms)
    assert any(x.startswith("经验意图:") for x in r.matched_terms)


def test_non_matching_and_short_examples_skipped():
    t = task(
        "a",
        "open_notepad",
        experience_examples=["totally different phrase", "ab"],
    )
    r = route_experience("open_notepad", [t])
    assert not any(x.startswith("示例:") for x in r.matched_terms)
    assert r.task_path == "a"


def test_message_cue_bonus():
    msg = task("a", "send", process_name="WeChat.exe")
    other = task("b", "zzz")
    r = route_experience("用微信发消息", [msg, other])
    assert r.task_path == "a"
    assert any(x.startswith("消息场景:") for x in r.matched_terms)
    assert r.score >= 5.0


def test_type_text_action_counts_as_message_task():
    msg = task("a", "x1", actions=["type_text"])
    r = route_experience("发消息给张三", [msg, task("b", "y1")])
    assert r.task_path == "a"


def test_confidence_cap_and_rounding():
    r = route_experience(
        "open_notepad",
        [task("a", "open_notepad", experience_examples=["open_notepad"])],
    )
    assert r.confidence <= 0.99
    assert r.score == round(r.score, 2)


def test_whitespace_normalized_and_case_insensitive():
    r = route_experience("  OPEN_NOTEPAD   ", [task("a", "open_notepad")])
    assert r.task_path == "a"


def test_single_candidate_no_ambiguity_check():
    r = route_experience("open_notepad", [task("a", "open_notepad")])
    assert r.task_path == "a"


def test_internal_helpers():
    assert m._compact("A b-C!") == "abc"
    assert m._terms("你好吗") == {"你好", "好吗"}
    assert m._terms("我") == {"我"}
    assert "open_x" in m._terms("Open_X")
