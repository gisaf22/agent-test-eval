# tests/test_skijack_ast.py
import dataclasses
import pytest

import skijack_ast as A
from skijack_ast import (
    Name, Num, App, Cell, Quote, Scry, Pick, Lambda, Case, NsLit, Path, Seg,
    TypeDecl, Ctor, Sig, Equation, Core, Macro, Def, Program, POLICY,
)

ALL_NODES = [Name, Num, App, Cell, Quote, Scry, Pick, Lambda, Case, NsLit,
             Path, Seg, TypeDecl, Ctor, Sig, Equation, Core, Macro, Def,
             Program]


def sample_nodes():
    x = Name("x")
    p = Path((Seg("a"), Seg("b", x)))
    return [
        x, Num(5), App(x, Num(1)), Cell((x, Num(2))),
        Quote(x, 3, x), Scry(p), Pick(2, x), Lambda("x", x),
        Case(x, (("Zero", (), x), ("Suc", ("n",), Name("n")))),
        NsLit(((p, x),)), p, Seg("t"),
        TypeDecl("nat", (Ctor("Zero"), Ctor("Suc", ("nat",)))),
        Sig("f", ("a", "b")), Equation("f", ("a",), x),
        Core("c", (Equation("f", (), x),)), Macro("m", ("a",), x),
        Def("d", x), Program((Def("d", x),)),
    ]


def test_all_exports_exist():
    for n in A.__all__:
        assert hasattr(A, n)


@pytest.mark.parametrize("cls", ALL_NODES)
def test_frozen_dataclass(cls):
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen


def test_frozen_assignment_raises():
    n = Name("a")
    with pytest.raises(dataclasses.FrozenInstanceError):
        n.name = "b"


def test_structural_equality_and_hash():
    for node in sample_nodes():
        copy = dataclasses.replace(node)
        assert node == copy
        assert hash(node) == hash(copy)
    assert len({Name("a"), Name("a"), Name("b")}) == 2


def test_inequality():
    assert Name("a") != Name("b")
    assert Num(1) != Num(2)
    assert Name("a") != Def("a", Name("a"))
    assert App(Name("f"), Name("x")) != App(Name("x"), Name("f"))


def test_application_left_assoc_shape():
    f, x, y = Name("f"), Name("x"), Name("y")
    t = App(App(f, x), y)
    assert t.fn == App(f, x) and t.arg == y


def test_qualified_name_is_text():
    assert Name("a.b").name == "a.b"


def test_quote_defaults():
    q = Quote(Name("t"))
    assert q.fuel is None and q.interp is None
    assert Quote(Name("t"), POLICY).fuel == "policy"
    assert POLICY == "policy"
    assert Quote(Name("t"), 0) != Quote(Name("t"))


def test_seg_default_payload():
    assert Seg("a").payload is None
    assert Seg("a") != Seg("a", Name("x"))


def test_ctor_defaults_and_arity():
    assert Ctor("Zero").fields == ()
    assert len(Ctor("Suc", ("nat",)).fields) == 1


def test_core_defaults():
    c = Core("c", ())
    assert c.params == ()
    assert Core("c", (), ("p",)) != c


def test_macro_default_hygienic():
    assert Macro("m", (), Name("x")).capturing is False
    assert Macro("m", (), Name("x"), True) != Macro("m", (), Name("x"))


def test_nested_trees_equal_and_hashable():
    def build():
        return Program((
            TypeDecl("nat", (Ctor("Zero"), Ctor("Suc", ("nat",)))),
            Def("x", Case(Name("n"), (("Suc", ("m",), Num(1)),))),
        ))
    a, b = build(), build()
    assert a == b and hash(a) == hash(b)


def test_sample_nodes_hashable():
    for n in sample_nodes():
        hash(n)


def test_tuple_vs_list_field_not_equal():
    assert Cell((Name("a"),)) != Cell([Name("a")])


def test_no_lexicon_field():
    for cls in ALL_NODES:
        for f in dataclasses.fields(cls):
            assert "lex" not in f.name.lower()
