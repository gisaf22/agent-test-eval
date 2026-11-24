# tests/test_wtftd_war_thunder_full_t_blk.py
import pytest
import wtftd_war_thunder_full_t_blk as m


def test_scalars():
    out = m.dumps({"a": True, "b": False, "c": 5, "d": 1.5, "e": "hi"})
    assert out.splitlines() == ["a:b=yes", "b:b=no", "c:i=5", "d:r=1.5", 'e:t="hi"']


def test_num_direct():
    assert m._num(True) == "yes"
    assert m._num(False) == "no"
    assert m._num(5) == "5"


def test_float_integer_valued():
    assert m.dumps({"a": 2.0}) == "a:r=2\n"


def test_float_nan_inf():
    assert m.dumps({"a": float("nan")}) == "a:r=0\n"
    assert m.dumps({"a": float("inf")}) == "a:r=0\n"


def test_small_float_no_exponent():
    out = m.dumps({"a": 1e-7})
    assert "e" not in out
    assert out.startswith("a:r=0.0000001")


def test_tiny_and_huge_float():
    assert m._num(1e-15) == "0.000000000001" or m._num(1e-15).startswith("0.")
    assert m._num(1e-20) == "0.0"
    big = m._num(1e20)
    assert big.startswith("1000") and big.endswith(".0") and "e" not in big


def test_string_quotes():
    assert m.dumps({"a": 'say "x"'}) == "a:t='say \"x\"'\n"
    assert m.dumps({"a": "it's \"x\""}) == "a:t=\"it's 'x'\"\n"


def test_none():
    assert m.dumps({"a": None}) == 'a:t=""\n'


def test_other_type():
    assert m.dumps({"a": (1, 2)}) == 'a:t="(1, 2)"\n'


def test_key_quoting():
    assert m.dumps({"a b": 1}) == '"a b":i=1\n'
    assert m.dumps({"a.b-c": 1}) == "a.b-c:i=1\n"


def test_nested_and_empty():
    assert m.dumps({"a": {"b": 1}}) == "a{\n  b:i=1\n}\n"
    assert m.dumps({"a": {}}) == "a{}\n"


def test_vectors():
    assert m.dumps({"a": [1, 2]}) == "a:ip2=1, 2\n"
    assert m.dumps({"a": [1, 2.5, 3]}) == "a:p3=1, 2.5, 3\n"
    assert m.dumps({"a": [1, 2, 3, 4]}) == "a:ip4=1, 2, 3, 4\n"


def test_color():
    assert m.dumps({"color": [1, 2, 3, 4]}) == "color:c=1, 2, 3, 4\n"


def test_matrix():
    v = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]]
    out = m.dumps({"tm": v})
    assert out == "tm:m=[[1, 0, 0] [0, 1, 0] [0, 0, 1] [0, 0, 0]]\n"
    assert m.loads(out) == {"tm": [[float(x) for x in r] for r in v]}


def test_repeated():
    assert m.dumps({"a": ["x", "y"]}) == 'a:t="x"\na:t="y"\n'
    assert m.dumps({"a": [{"b": 1}, {"b": 2}]}).count("a{") == 2


def test_loads_basic():
    t = 'a:i=1\nb:r=2.5\nc:t="hi"\nd:b=yes\ne:p2=1, 2\nf:ip3=1,2,3\n'
    assert m.loads(t) == {"a": 1, "b": 2.5, "c": "hi", "d": True,
                          "e": [1.0, 2.0], "f": [1, 2, 3]}


def test_loads_block_repeat():
    r = m.loads("a{x:i=1}\na{x:i=2}\na{x:i=3}")
    assert r == {"a": [{"x": 1}, {"x": 2}, {"x": 3}]}


def test_loads_comments():
    t = "/* a /* nested */ still */ a:i=1 // c\nb:i=2 /* x */\n"
    assert m.loads(t) == {"a": 1, "b": 2}


def test_unterminated_comment():
    assert m.loads("a:i=1\n/* never closed") == {"a": 1}


def test_loads_same_line_and_semicolon():
    assert m.loads("a:i=1; b:i=2") == {"a": 1, "b": 2}
    assert m.loads("a:i=1 b:i=2") == {"a": 1, "b": 2}
    assert m.loads('a:t="x"; b:i=2') == {"a": "x", "b": 2}


def test_loads_quoted_number():
    assert m.loads('a:r="1000.0"') == {"a": 1000.0}


def test_loads_include():
    assert m.loads('include "b.blk"') == {"@include": "b.blk"}


def test_loads_bool_variants():
    r = m.loads("a:b=true b:b=no c:b=on")
    assert r == {"a": True, "b": False, "c": True}


def test_unknown_type_and_i64():
    assert m.loads("a:zz=foo") == {"a": "foo"}
    assert m.loads("a:i64=123") == {"a": 123}


def test_loads_error():
    with pytest.raises(ValueError):
        m.loads("a=1")


def test_loads_error_leading():
    with pytest.raises(ValueError):
        m.loads("=1")


def test_roundtrip():
    d = {"a": {"b": 1, "c": [1.5, 2.5], "d": "s", "e": [{"x": 1}, {"x": 2}]},
         "f": True, "g": [1, 2, 3]}
    assert m.loads(m.dumps(d)) == d
