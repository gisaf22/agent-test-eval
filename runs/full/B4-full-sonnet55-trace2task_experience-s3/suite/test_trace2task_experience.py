# tests/test_trace2task_experience.py
import pytest

import trace2task_experience as m
from trace2task_experience import ExperienceMatch, route_experience


def task(path, task_id, **kw):
    d = {"path": path, "task_id": task_id, "confirmed": True}
    d.update(kw)
    return d


def test_to_payload():
    em = ExperienceMatch("p", "t", 1.5, 0.8, ("a", "b"), "r")
    assert em.to_payload() == {
        "task_path": "p",
        "task_id": "t",
        "score": 1.5,
        "confidence": 0.8,
        "matched_terms": ["a", "b"],
        "reason": "r",
    }


def test_dataclass_frozen():
    em = ExperienceMatch("p", "t", 1.0, 0.5, (), "r")
    with pytest.raises(Exception):
        em.score = 2.0


def test_compact():
    assert m._compact("Hello, World!") == "helloworld"
    assert m._compact("打开 微信！") == "打开微信"


def test_terms():
    assert m._terms("打开微信") == {"打开", "开微", "微信"}
    assert m._terms("好") == {"好"}
    t = m._terms("Open file_name.txt")
    assert "open" in t and "file_name.txt" in t
    assert m._terms("a") == set()


def test_empty_instruction():
    with pytest.raises(ValueError):
        route_experience("   \n ", [task("p", "x")])


def test_no_confirmed():
    with pytest.raises(ValueError):
        route_experience("hello", [task("p", "hello", confirmed=False)])
    with pytest.raises(ValueError):
        route_experience("hello", [])


def test_low_score():
    with pytest.raises(ValueError, match="足够匹配"):
        route_experience("zzzz qqqq", [task("p", "export_report")])


def test_basic_match():
    r = route_experience(
        "please export_report now",
        [task("a.json", "export_report"), task("b.json", "other_thing")],
    )
    assert r.task_path == "a.json"
    assert r.task_id == "export_report"
    assert r.score >= 8.0
    assert r.matched_terms[0] == "任务名称:export_report"
    assert "export_report" in r.reason
    assert 0.5 < r.confidence <= 0.99


def test_exact_score():
    score, matched = m._score("export_report", task("a", "export_report"))
    assert score == pytest.approx(22.75)
    assert matched == (
        "任务名称:export_report",
        "经验意图:export_report",
        "模糊表达:export_report",
        "export_report",
    )


def test_confidence_capped_and_rounded():
    r = route_experience(
        "export_report",
        [task("a", "export_report", experience_examples=["export_report"])],
    )
    assert r.confidence == 0.99
    assert r.score == round(r.score, 2)


def test_ambiguous():
    ts = [task("a", "export_report"), task("b", "export_report")]
    with pytest.raises(ValueError, match="同样接近"):
        route_experience("export_report", ts)


def test_single_candidate_no_ambiguity():
    r = route_experience("export_report", [task("a", "export_report")])
    assert r.task_path == "a"


def test_unconfirmed_ignored():
    r = route_experience(
        "export_report",
        [task("a", "export_report", confirmed=False), task("b", "export_report")],
    )
    assert r.task_path == "b"


def test_examples_match():
    t = task("a", "zzz", experience_examples=["整理桌面文件"])
    score, matched = m._score("请帮我整理桌面文件", t)
    assert any(x.startswith("示例:") for x in matched)
    assert score >= 6.0


def test_example_not_matching_or_too_short():
    t = task("a", "zzz", experience_examples=["完全无关的内容", "ab"])
    score, matched = m._score("请帮我整理桌面文件", t)
    assert not any(x.startswith("示例:") for x in matched)
    t2 = task("a", "zzz", experience_examples=["桌面"])
    _, matched2 = m._score("整理桌面", t2)
    assert not any(x.startswith("示例:") for x in matched2)


def test_message_scenario():
    t = task("a", "zzz", process_name="WeChat.exe")
    score, matched = m._score("给张三发消息", t)
    assert score >= 5.0
    assert "消息场景:发消息" in matched
    t2 = task("a", "zzz", actions=["type_text"])
    assert "消息场景:发消息" in m._score("发消息", t2)[1]
    t3 = task("a", "zzz", process_name="notepad.exe")
    assert m._score("发消息", t3)[0] < 5.0


def test_message_routing_chooses_message_task():
    r = route_experience(
        "用微信发消息给老王",
        [
            task("w", "send", process_name="weixin.exe"),
            task("n", "note", process_name="notepad.exe"),
        ],
    )
    assert r.task_path == "w"


def test_matched_terms_dedup():
    score, matched = m._score(
        "alpha beta gamma delta epsilon",
        task("p", "alpha beta gamma delta epsilon"),
    )
    assert len(matched) == len(set(matched))


def test_tie_raises():
    with pytest.raises(ValueError):
        route_experience("open_app", [task("b", "open_app"), task("a", "open_app")])


def test_deterministic():
    ts = [task("a", "export_report"), task("b", "zzzz")]
    assert route_experience("export_report", ts) == route_experience("export_report", ts)
