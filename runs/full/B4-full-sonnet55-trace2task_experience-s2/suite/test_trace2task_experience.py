# tests/test_trace2task_experience.py
import pytest

import trace2task_experience as m
from trace2task_experience import ExperienceMatch, route_experience


def task(path, task_id, **kw):
    d = {"path": path, "task_id": task_id, "confirmed": True}
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
    em = ExperienceMatch("p", "t", 1.0, 0.5, (), "r")
    with pytest.raises(Exception):
        em.score = 2.0


def test_compact_and_terms():
    assert m._compact("Hello, 世界! _x") == "hello世界_x"
    assert m._terms("你") == {"你"}
    assert m._terms("你好吗") == {"你好", "好吗"}
    assert "open_file.txt" in m._terms("Open_File.txt")
    assert m._terms("a") == set()


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_instruction(text):
    with pytest.raises(ValueError):
        route_experience(text, [task("p", "abc")])


def test_no_confirmed():
    with pytest.raises(ValueError, match="已确认"):
        route_experience("open notepad", [task("p", "open notepad", confirmed=False)])
    with pytest.raises(ValueError):
        route_experience("open notepad", [])


def test_low_score():
    with pytest.raises(ValueError, match="足够匹配"):
        route_experience("completely different", [task("p", "zzzz qqqq")])


def test_exact_match_selected():
    tasks = [
        task("a.json", "open_notepad"),
        task("b.json", "close_window"),
    ]
    r = route_experience("please open_notepad now", tasks)
    assert r.task_path == "a.json"
    assert r.task_id == "open_notepad"
    assert r.score >= 8.0
    assert 0.5 < r.confidence <= 0.99
    assert any(t.startswith("任务名称:") for t in r.matched_terms)
    assert "open_notepad" in r.reason
    assert isinstance(r.matched_terms, tuple)


def test_whitespace_normalized():
    r = route_experience("  open_notepad \n  now ", [task("a", "open_notepad")])
    assert r.task_id == "open_notepad"


def test_example_match():
    t = task("a", "zz", experience_examples=["export report"])
    r = route_experience("export report today", [t])
    assert any(x.startswith("示例:") for x in r.matched_terms)


def test_example_not_contained_or_too_short():
    t = task("a", "open_notepad", experience_examples=["zzzzzz", "ab"])
    s, matched = m._score("open_notepad", t)
    assert not any(x.startswith("示例:") for x in matched)
    assert any(x.startswith("任务名称:") for x in matched)


def test_unconfirmed_ignored():
    tasks = [
        task("a", "open_notepad", confirmed=False),
        task("b", "open_notepad"),
    ]
    assert route_experience("open_notepad", tasks).task_path == "b"


def test_ambiguous():
    tasks = [task("a", "open_notepad"), task("b", "open_notepad")]
    with pytest.raises(ValueError, match="同样接近"):
        route_experience("open_notepad", tasks)


def test_message_scene_bonus():
    t = task("a", "send", process_name="WeChat.exe")
    s, matched = m._score("发消息 send", t)
    assert any(x.startswith("消息场景:") for x in matched)
    t2 = task("a", "send")
    s2, _ = m._score("发消息 send", t2)
    assert s - s2 == 5.0


def test_type_text_action_counts_as_message():
    t = task("a", "x", actions=["type_text"])
    _, matched = m._score("微信 hi", t)
    assert "消息场景:微信" in matched


def test_chinese_match_and_confidence_cap():
    t = task("a", "打开记事本", experience_examples=["打开记事本"], experience_intent="打开记事本")
    r = route_experience("请打开记事本", [t, task("b", "关闭")])
    assert r.task_path == "a"
    assert r.confidence == 0.99
    assert r.score == round(r.score, 2)


def test_tie_broken_not_needed_when_margin_ok():
    tasks = [task("b", "open_notepad"), task("a", "zzzz")]
    assert route_experience("open_notepad", tasks).task_path == "b"
