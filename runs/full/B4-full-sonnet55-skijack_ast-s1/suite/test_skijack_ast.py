# tests/test_skijack_ast.py
import dataclasses
from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest

import skijack_ast as ast
from skijack_ast import (
    Name, Num, App, Cell, Quote, Scry, Pick, Lambda, Case, NsLit, Path, Seg,
    TypeDecl, Ctor, Sig, Equation, Core, Macro, Def, Program, POLICY,
)

ALL_NODES = [
    Name, Num, App, Cell, Quote, Scry, Pick, Lambda, Case, NsLit, Path, Seg,
    TypeDecl, Ctor, Sig, Equation, Core, Macro, Def, Program,
]


def test_all_exports_exist():
    for n in ast.__all__:
        assert hasattr(ast, n)


@pytest.mark.parametrize("cls", ALL_NODES)
def test_dataclass_frozen(cls):
    assert is_dataclass(cls)
    assert cls.__dataclass_params__.frozen


def test_frozen_assignment_raises():
    n = Name("x")
    with pytest.raises(FrozenInstanceError):
        n.name = "y"
    with pytest.raises(FrozenInstanceError):
        Num(1).value = 2


def test_structural_equality_and_hash():
    a = App(App(Name("f"), Name("x")), Num(1))
    b = App(App(Name("f"), Name("x")), Num(1))
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1
    assert a != App(Name("f"), Num(1))


def test_different_types_not_equal():
    assert Name("x") != Sig("x", ())
    assert Num(1) != Name("1")


def test_app_left_assoc_shape():
    t = App(App(Name("f"), Name("x")), Name("y"))
    assert t.fn == App(Name("f"), Name("x"))
    assert t.arg == Name("y")


def test_cell_items_hashable():
    c = Cell((Num(1), Num(2), Num(3)))
    assert len(c.items) == 3
    assert hash(c) == hash(Cell((Num(1), Num(2), Num(3))))
    assert c != Cell((Num(1), Cell((Num(2), Num(3)))))


def test_quote_defaults():
    q = Quote(Name("t"))
    assert q.fuel is None
    assert q.interp is None


def test_quote_fuel_variants():
    assert Quote(Name("t"), 5) != Quote(Name("t"))
    assert Quote(Name("t"), POLICY).fuel == "policy"
    assert Quote(Name("t"), POLICY) != Quote(Name("t"), 5)
    assert Quote(Name("t"), 0) != Quote(Name("t"), None)
    q = Quote(Name("t"), 3, Name("E"))
    assert q.interp == Name("E")


def test_policy_constant():
    assert POLICY == "policy"


def test_seg_and_path():
    assert Seg("a").payload is None
    p = Path((Seg("a"), Seg("b", Num(1))))
    assert p == Path((Seg("a"), Seg("b", Num(1))))
    assert p != Path((Seg("a"), Seg("b")))
    assert Scry(p).path is p


def test_pick_lambda():
    assert Pick(2, Name("p")).axis == 2
    assert Lambda("x", Name("x")) == Lambda("x", Name("x"))
    assert Lambda("x", Name("x")) != Lambda("y", Name("x"))


def test_case_and_nslit():
    c = Case(Name("e"), (("Zero", (), Num(0)), ("Suc", ("n",), Name("n"))))
    assert c.branches[1][1] == ("n",)
    assert hash(c)
    ns = NsLit(((Path((Seg("a"),)), Num(1)),))
    assert hash(ns)
    assert ns == NsLit(((Path((Seg("a"),)), Num(1)),))


def test_ctor_defaults_and_arity():
    assert Ctor("Zero").fields == ()
    assert len(Ctor("Suc", ("nat",)).fields) == 1


def test_typedecl():
    t = TypeDecl("nat", (Ctor("Zero"), Ctor("Suc", ("nat",))))
    assert [c.name for c in t.ctors] == ["Zero", "Suc"]
    assert hash(t)


def test_core_defaults():
    c = Core("loop", (Equation("f", ("a",), Name("a")),))
    assert c.params == ()
    c2 = Core("loop", c.equations, ("p",))
    assert c2 != c


def test_macro_default_hygienic():
    m = Macro("m", ("x",), Name("x"))
    assert m.capturing is False
    assert Macro("m", ("x",), Name("x"), True) != m


def test_def_and_program():
    d = Def("x", Num(1))
    p = Program((d, Sig("f", ("a", "b"))))
    assert p == Program((Def("x", Num(1)), Sig("f", ("a", "b"))))
    assert hash(p) == hash(Program((Def("x", Num(1)), Sig("f", ("a", "b")))))
    assert p.decls[0] is d


def test_replace_creates_new():
    n = Num(1)
    m = dataclasses.replace(n, value=2)
    assert n.value == 1 and m.value == 2


def test_no_lexicon_field():
    for cls in ALL_NODES:
        assert "lexicon" not in {f.name for f in fields(cls)}


def test_positional_required_args():
    with pytest.raises(TypeError):
        Name()
    with pytest.raises(TypeError):
        App(Name("f"))
