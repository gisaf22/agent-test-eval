# tests/test_portable_hermes_agent_inline_markdown.py
import pytest

import portable_hermes_agent_inline_markdown as m
from portable_hermes_agent_inline_markdown import spans, line_spans, BOLD, CODE


def joined(p):
    return "".join(t for t, _ in p)


def test_empty_and_none():
    assert spans("") == []
    assert spans(None) == []


def test_plain():
    assert spans("hello world") == [("hello world", ())]


def test_bold():
    assert spans("a **b** c") == [("a ", ()), ("b", (BOLD,)), (" c", ())]


def test_bold_at_start_and_end():
    assert spans("**hi**") == [("hi", (BOLD,))]


def test_code():
    assert spans("x `y` z") == [("x ", ()), ("y", (CODE,)), (" z", ())]


def test_code_blocks_bold():
    assert spans("`**a**`") == [("**a**", (CODE,))]


def test_double_backtick_code():
    assert spans("``a`b``") == [("a`b", (CODE,))]


def test_unclosed_backtick_literal():
    assert spans("a `b") == [("a `b", ())]


def test_mismatched_backtick_runs():
    assert spans("`a``") == [("`a``", ())]


@pytest.mark.parametrize("s", [
    "**/*.py,**/*.txt", "2**10", "a ** b", "f(*args, **kwargs)",
    "***x***", "**bold *x* **", "**a", "a**", "** a**",
])
def test_literal_cases(s):
    assert spans(s) == [(s, ())]


def test_bold_no_star_inside():
    assert spans("**a*b**") == [("**a*b**", ())]


def test_opener_chars():
    assert spans('("**x**")')[1] == ("x", (BOLD,))
    assert spans("**$x**") == [("$x", (BOLD,))]


def test_close_followed_by_punct():
    assert spans("**x**.") == [("x", (BOLD,)), (".", ())]


def test_close_followed_by_letter_fails():
    assert spans("**x**y") == [("**x**y", ())]


def test_bold_not_cross_line():
    assert spans("**a\nb**") == [("**a\nb**", ())]


def test_fence_literal():
    t = "```\n**a**\n```\n**b**"
    assert spans(t) == [("```\n**a**\n```\n", ()), ("b", (BOLD,))]


def test_tilde_fence_needs_same_char():
    t = "~~~\n```\n**a**\n~~~"
    assert spans(t) == [(t, ())]


def test_longer_fence_needs_longer_close():
    t = "````\n```\n**a**\n````\n**b**"
    p = spans(t)
    assert p[-1] == ("b", (BOLD,))
    assert ("**a**" in p[0][0]) and p[0][1] == ()


def test_inline_triple_backtick_is_code():
    assert spans("```x```") == [("x", (CODE,))]


def test_fence_with_info():
    assert line_spans("```python") == ([("```python", ())], ("`", 3))


def test_unclosed_fence_stays_open():
    assert spans("```\n**a**") == [("```\n**a**", ())]


def test_link_literal():
    s = "[**a**](http://x.com/**b**)"
    assert spans(s) == [(s, ())]


def test_image_literal():
    s = "![**a**](u)"
    assert spans(s) == [(s, ())]


def test_url_literal():
    s = "see http://a.com/**x** now"
    assert spans(s) == [(s, ())]


def test_bold_near_link():
    p = spans("**a** [t](u)")
    assert p == [("a", (BOLD,)), (" [t](u)", ())]


def test_line_spans_fence_state():
    p, f = line_spans("```")
    assert f == ("`", 3)
    p, f = line_spans("**x**", f)
    assert p == [("**x**", ())] and f == ("`", 3)
    p, f = line_spans("```", f)
    assert f is None


def test_line_spans_plain():
    assert line_spans("**x**") == ([("x", (BOLD,))], None)


def test_indented_fence():
    assert line_spans("  ~~~")[1] == ("~", 3)


def test_text_preserved():
    t = "a **b** `c`\n```\nz\n```\n2**3 **x**"
    assert joined(spans(t)) == t.replace("**b**", "b").replace("`c`", "c").replace("**x**", "x")


def test_merged_neighbors():
    p = spans("a\n\nb")
    assert p == [("a\n\nb", ())]
