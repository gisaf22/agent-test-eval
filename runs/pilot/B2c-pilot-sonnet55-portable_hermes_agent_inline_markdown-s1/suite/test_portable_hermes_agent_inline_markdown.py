# tests/test_portable_hermes_agent_inline_markdown.py
import pytest

import portable_hermes_agent_inline_markdown as m
from portable_hermes_agent_inline_markdown import BOLD, CODE, spans, line_spans


def joined(p):
    return "".join(t for t, _ in p)


@pytest.mark.parametrize("text", [
    "", "plain", "**/*.py,**/*.txt", "2**10", "a ** b",
    "f(*args, **kwargs)", "***x***", "**unclosed", "** spaced **",
    "**a*b**", "line one\nline two",
])
def test_roundtrip_text(text):
    assert joined(spans(text)) == text


def test_none_and_empty():
    assert spans("") == []
    assert spans(None) == []


def test_plain():
    assert spans("hello") == [("hello", ())]


def test_bold():
    assert spans("a **bold** b") == [("a ", ()), ("bold", (BOLD,)), (" b", ())]


def test_bold_at_start_and_end():
    assert spans("**hi**") == [("hi", (BOLD,))]


def test_bold_after_paren_and_punct():
    assert spans("(**hi**).") == [("(", ()), ("hi", (BOLD,)), (").", ())]


def test_code():
    assert spans("x `c` y") == [("x ", ()), ("c", (CODE,)), (" y", ())]


def test_double_backtick_code():
    assert spans("``a`b``") == [("a`b", (CODE,))]


def test_unclosed_backtick_literal():
    assert spans("`abc") == [("`abc", ())]


def test_bold_inside_code_not_bold():
    assert spans("`**x**`") == [("**x**", (CODE,))]


def test_code_inside_bold():
    assert spans("**a `b` c**") == [
        ("a ", (BOLD,)), ("b", (BOLD, CODE)), (" c", (BOLD,))]


def test_not_bold_cases_have_no_tags():
    for t in ["2**10", "a ** b", "f(*args, **kwargs)", "***x***",
              "**/*.py,**/*.txt"]:
        assert all(tags == () for _, tags in spans(t))


def test_single_asterisk_not_bold():
    assert spans("*a*") == [("*a*", ())]


def test_bold_does_not_cross_lines():
    assert spans("**a\nb**") == [("**a\nb**", ())]


def test_bold_each_line_separately():
    assert spans("**a**\n**b**") == [
        ("a", (BOLD,)), ("\n", ()), ("b", (BOLD,))]


def test_close_not_after_whitespace():
    assert spans("**a **b") == [("**a **b", ())]


def test_open_followed_by_dollar():
    assert spans("**$x**") == [("$x", (BOLD,))]


def test_close_followed_by_letter_fails():
    assert spans("**a**b") == [("**a**b", ())]


def test_link_literal():
    t = "[**x**](http://a.b/**y**)"
    assert spans(t) == [(t, ())]


def test_image_literal():
    t = "![**x**](p.png)"
    assert spans(t) == [(t, ())]


def test_url_literal_and_neighbors():
    p = spans("**a** http://x.com/**b** **c**")
    assert p[0] == ("a", (BOLD,))
    assert joined(p) == "a http://x.com/**b** c"
    assert p[-1] == ("c", (BOLD,))


def test_fence_backticks():
    t = "```py\n**x** `y`\n```\n**z**"
    assert spans(t) == [("```py\n**x** `y`\n```\n", ()), ("z", (BOLD,))]


def test_fence_tilde():
    t = "~~~\n**x**\n~~~"
    assert all(tags == () for _, tags in spans(t))


def test_fence_needs_same_char():
    t = "```\n~~~\n**x**"
    assert all(tags == () for _, tags in spans(t))


def test_fence_needs_length():
    t = "````\n```\n**x**\n````\n**y**"
    p = spans(t)
    assert p[-1] == ("y", (BOLD,))
    assert ("x", (BOLD,)) not in p


def test_unclosed_fence_runs_to_end():
    assert all(t == () for _, t in spans("```\n**x**"))


def test_inline_triple_backtick_is_code():
    assert spans("```x```") == [("x", (CODE,))]


def test_indented_fence():
    assert all(t == () for _, t in spans("  ```\n**x**"))


def test_line_spans_fence_state():
    p, f = line_spans("```py")
    assert p == [("```py", ())] and f == ("`", 3)
    p, f = line_spans("**x**", f)
    assert p == [("**x**", ())] and f == ("`", 3)
    p, f = line_spans("```", f)
    assert f is None


def test_line_spans_plain():
    assert line_spans("**x**") == ([("x", (BOLD,))], None)


def test_line_spans_empty():
    assert line_spans("") == ([], None)


def test_merge_adjacent():
    p = spans("a\nb")
    assert p == [("a\nb", ())]


def test_two_bolds():
    p = spans("**a** and **b**")
    assert p == [("a", (BOLD,)), (" and ", ()), ("b", (BOLD,))]
