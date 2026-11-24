# tests/test_skijack_ast.py
import dataclasses
from dataclasses import FrozenInstanceError

import pytest

import skijack_ast as A


def sample_path():
    return A.Path((A.Seg("a"), A.Seg("b", A.Num(1))))


ALL_NODES = [
    A.Name("x"),
    A.Num(5),
    A.App(A.Name("f"), A.Name("x")),
    A.Cell((A.Num(1), A.Num(2))),
    A.Quote(A.Name("t")),
    A.Seg("a"),
    sample_path(),
    A.Scry(sample_path()),
    A.Pick(2, A.Name("p")),
    A.Lambda("x", A.Name("x")),
    A.Case(A.Name("e"), (("Zero", (), A.Num(0)),)),
    A.NsLit(((sample_path(), A.Num(1)),)),
    A.Ctor("Suc", ("nat",)),
    A.TypeDecl("nat", (A.Ctor("Zero"), A.Ctor("Suc", ("nat",)))),
    A.Sig("f", ("s", "t")),
    A.Equation("f", ("x",), A.Name("x")),
    A.Core("c", (A.Equation("f", (), A.Num(1)),)),
    A.Macro("m", ("a",), A.Name("a")),
    A.Def("d", A.Num(1)),
    A.Program((A.Def("d", A.Num(1)),)),
]


@pytest.mark.parametrize("node", ALL_NODES, ids=lambda n: type(n).__name__)
def test_frozen_hashable_equal(node):
    assert dataclasses.is_dataclass(node)
    first = dataclasses.fields(node)[0].name
    with pytest.raises(FrozenInstanceError):
        setattr(node, first, None)
    clone = dataclasses.replace(node)
    assert clone == node
    assert hash(clone) == hash(node)
    assert len({node, clone}) == 1


def test_all_exports_exist():
    for n in A.__all__:
        assert hasattr(A, n)


def test_name_num_equality():
    assert A.Name("a.b") == A.Name("a.b")
    assert A.Name("a") != A.Name("b")
    assert A.Num(5) == A.Num(5)
    assert A.Num(5) != A.Num(6)
    assert A.Name("x") != A.Num(1)


def test_app_left_assoc_structure():
    f, x, y = A.Name("f"), A.Name("x"), A.Name("y")
    t = A.App(A.App(f, x), y)
    assert t.fn == A.App(f, x)
    assert t.arg == y
    assert t != A.App(f, A.App(x, y))


def test_cell_items_flat():
    c = A.Cell((A.Num(1), A.Num(2), A.Num(3)))
    assert len(c.items) == 3
    assert c != A.Cell((A.Num(1), A.Cell((A.Num(2), A.Num(3)))))


def test_quote_defaults():
    q = A.Quote(A.Name("t"))
    assert q.fuel is None and q.interp is None
    assert A.Quote(A.Name("t"), 3) != A.Quote(A.Name("t"), A.POLICY)
    assert A.Quote(A.Name("t"), None) == q
    assert A.POLICY == "policy"
    assert A.Quote(A.Name("t"), A.POLICY, A.Name("i")).interp == A.Name("i")


def test_seg_payload_default():
    assert A.Seg("a").payload is None
    assert A.Seg("a") != A.Seg("a", A.Num(1))


def test_path_and_scry():
    assert A.Scry(sample_path()) == A.Scry(sample_path())
    assert A.Scry(A.Path(())) != A.Scry(sample_path())


def test_ctor_arity_and_default():
    assert A.Ctor("Zero").fields == ()
    assert len(A.Ctor("Suc", ("nat",)).fields) == 1


def test_core_params_default():
    c = A.Core("c", ())
    assert c.params == ()
    assert A.Core("c", (), ("p",)) != c


def test_macro_capturing_default():
    assert A.Macro("m", (), A.Num(1)).capturing is False
    assert A.Macro("m", (), A.Num(1), True) != A.Macro("m", (), A.Num(1))


def test_case_branches_hashable():
    c = A.Case(A.Name("e"), (("Suc", ("n",), A.Name("n")),))
    assert c.branches[0][1] == ("n",)
    assert hash(c) == hash(A.Case(A.Name("e"), (("Suc", ("n",), A.Name("n")),)))


def test_program_equality_structural():
    d = A.Def("x", A.Num(1))
    assert A.Program((d,)) == A.Program((A.Def("x", A.Num(1)),))
    assert A.Program((d,)) != A.Program(())


def test_no_lexicon_field():
    for n in ALL_NODES:
        assert all("lex" not in f.name for f in dataclasses.fields(n))
