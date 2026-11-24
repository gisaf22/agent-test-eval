# tests/test_portable_hermes_agent_inline_markdown.py
import pytest

from portable_hermes_agent_inline_markdown import (
    BOLD, CODE, spans, line_spans,
)


def joined(p):
    return "".join(t for t, _ in p)


def test_empty_and_none():
    assert spans("") == []
    assert spans(None) == []


def test_plain():
    assert spans("hello") == [("hello", ())]


def test_bold():
    assert spans("a **b** c") == [("a ", ()), ("b", (BOLD,)), (" c", ())]


def test_bold_at_start_and_end():
    assert spans("**hi**") == [("hi", (BOLD,))]


def test_code():
    assert spans("x `y` z") == [("x ", ()), ("y", (CODE,)), (" z", ())]


def test_double_backtick_code_holds_single():
    assert spans("``a`b``") == [("a`b", (CODE,))]


def test_unclosed_backtick_literal():
    assert spans("a `b") == [("a `b", ())]


def test_bold_inside_code_not_bold():
    assert spans("`**x**`") == [("**x**", (CODE,))]


def test_code_inside_bold():
    assert spans("**a `b` c**") == [
        ("a ", (BOLD,)), ("b", (BOLD, CODE)), (" c", (BOLD,))]


@pytest.mark.parametrize("s", [
    "**/*.py,**/*.txt", "2**10", "a ** b", "f(*args, **kwargs)",
    "***x***", "**x", "x**", "*x*", "** x**", "**x **",
])
def test_stays_literal(s):
    assert spans(s) == [(s, ())]


def test_bold_cannot_contain_star():
    s = "**a*b**"
    assert spans(s) == [(s, ())]


def test_open_after_paren_and_quote():
    assert spans('("**x**")') == [('("', ()), ("x", (BOLD,)), ('")', ())]


def test_close_before_punctuation():
    assert spans("**x**.") == [("x", (BOLD,)), (".", ())]


def test_styling_does_not_cross_lines():
    s = "**a\nb**"
    assert spans(s) == [(s, ())]


def test_fence_literal():
    s = "```\n**x** `y`\n```\n**z**"
    assert spans(s) == [("```\n**x** `y`\n```\n", ()), ("z", (BOLD,))]


def test_tilde_fence():
    s = "~~~py\n**x**\n~~~"
    assert spans(s) == [(s, ())]


def test_fence_needs_long_enough_close():
    s = "````\n```\n**x**\n````\n**y**"
    out = spans(s)
    assert out[-1] == ("y", (BOLD,))
    assert ("**x**" in out[0][0])


def test_different_char_does_not_close():
    s = "```\n~~~\n**x**"
    assert spans(s) == [(s, ())]


def test_unclosed_fence_runs_to_end():
    s = "```\n**x**"
    assert spans(s) == [(s, ())]


def test_inline_triple_backtick_is_code():
    assert spans("```x```") == [("x", (CODE,))]


def test_links_and_urls_literal():
    for s in ["[**a**](http://x)", "![**a**](u)", "see http://a.b/**x**"]:
        assert spans(s) == [(s, ())]


def test_bold_beside_link():
    assert spans("**a** [t](u)") == [("a", (BOLD,)), (" [t](u)", ())]


def test_newlines_preserved():
    assert joined(spans("a\n\n**b**")) == "a\n\nb"


def test_line_spans_basic():
    p, f = line_spans("**a**")
    assert p == [("a", (BOLD,))] and f is None


def test_line_spans_fence_state():
    p, f = line_spans("```py")
    assert p == [("```py", ())] and f == ("`", 3)
    p, f = line_spans("**x**", f)
    assert p == [("**x**", ())] and f == ("`", 3)
    p, f = line_spans("```", f)
    assert f is None


def test_indented_fence():
    p, f = line_spans("  ~~~~")
    assert f == ("~", 4)


def test_merge_adjacent():
    out = spans("a\nb")
    assert out == [("a\nb", ())]
