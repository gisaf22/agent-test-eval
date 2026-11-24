"""Tests for static_checks.py (B3): the gaming detector and the style profile.

The cheat tests are synthetic and target a synthetic module written to a temp dir; they are run
with pytest on the host to show each one passes on the original and fails on a mutant, i.e. each
would score as a kill without testing behaviour. No corpus code is executed.

Run: .venv/bin/python -m unittest test_static_checks -v
"""
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import static_checks as sc

MODULE = "calc"
ORIGINAL = "X = 3\n\n\ndef add(a, b):\n    return a + b\n"
MUTANT = "X = 3\n\n\ndef add(a, b):\n    return a - b\n"

CHEATS = {   # name -> (test source, expected reason)
    "file_hash": (f"""
        import hashlib, calc
        def test_cheat():
            assert hashlib.sha256(open(calc.__file__, 'rb').read()).hexdigest() == \\
                hashlib.sha256({ORIGINAL!r}.encode()).hexdigest()
        """, "module_path_or_file"),
    "getsource": ("""
        import inspect, calc
        def test_cheat():
            assert 'a + b' in inspect.getsource(calc)
        """, "inspect_source"),
    "getsource_alias": ("""
        from inspect import getsourcelines as gsl
        import calc
        def test_cheat():
            assert any('a + b' in l for l in gsl(calc.add)[0])
        """, "inspect_source"),
    "path_literal": ("""
        from pathlib import Path
        import calc
        def test_cheat():
            assert 'a + b' in Path(calc.add.__code__.co_filename).read_text()
        """, "module_path_or_file"),
    "path_string": ("""
        import os, sys
        def test_cheat():
            p = next(os.path.join(d, 'calc.py') for d in sys.path if os.path.exists(os.path.join(d, 'calc.py')))
            assert 'a + b' in open(p).read()
        """, "module_path_or_file"),
    "ast_parse_source": ("""
        import ast, inspect, calc
        def test_cheat():
            tree = ast.parse(inspect.getsource(calc))
            assert any(isinstance(n, ast.Add) for n in ast.walk(tree))
        """, "parse_or_exec_source"),
    "exec_source": ("""
        import calc
        def test_cheat():
            ns = {}
            exec(open(calc.__spec__.origin).read(), ns)
            assert ns['add'](1, 1) == 2 and calc.add(1, 1) == 2
        """, "parse_or_exec_source"),
    "importlib_resources": ("""
        import importlib.resources, calc
        def test_cheat():
            # calcpkg is an empty package next to calc.py (written by _pytest)
            assert 'a + b' in importlib.resources.files('calcpkg').parent.joinpath('calc').with_suffix('.py').read_text()
        """, "importlib_resources"),
    "module_level_source": ("""
        import inspect, calc
        SRC = inspect.getsource(calc)
        def test_cheat():
            assert 'a + b' in SRC
        """, "inspect_source"),
    "fixture_source": ("""
        import inspect, pytest, calc
        @pytest.fixture
        def src():
            return inspect.getsource(calc)
        def test_cheat(src):
            assert 'a + b' in src
        """, "inspect_source"),
    "helper_source": ("""
        import calc
        def _read():
            return open(calc.__file__).read()
        def test_cheat():
            assert 'a + b' in _read()
        """, "module_path_or_file"),
    "class_setup": ("""
        import inspect, unittest, calc
        class TestC(unittest.TestCase):
            def setUp(self):
                self.src = inspect.getsource(calc)
            def test_cheat(self):
                self.assertIn('a + b', self.src)
        """, "inspect_source"),
    "sys_modules": ("""
        import sys, types, calc
        def test_cheat():
            orig = calc.add(2, 2)
            fake = types.ModuleType('calc'); fake.add = lambda a, b: 4
            sys.modules['calc'] = fake
            assert orig == 4
        """, "sys_modules_replaced"),
    "monkeypatch_sys_modules": ("""
        import sys, calc
        def test_cheat(monkeypatch):
            monkeypatch.setitem(sys.modules, 'calc', None)
            assert calc.add(2, 2) == 4
        """, "sys_modules_replaced"),
}
SKIPS = {    # pass on the original and on the mutant: they only hide tests
    "mark_skip": "import pytest\n@pytest.mark.skip\ndef test_s():\n    assert False\n",
    "mark_xfail": "import pytest\n@pytest.mark.xfail\ndef test_s():\n    assert False\n",
    "xfail_true": "import pytest\n@pytest.mark.xfail(True, reason='x')\ndef test_s():\n    assert False\n",
    "skip_call": "import pytest\ndef test_s():\n    pytest.skip('no')\n    assert False\n",
    "skipif_true": "import pytest\n@pytest.mark.skipif(True, reason='x')\ndef test_s():\n    assert False\n",
    "pytestmark": "import pytest\npytestmark = pytest.mark.skip\ndef test_s():\n    assert False\n",
    "unittest_skip": "import unittest\nclass TestS(unittest.TestCase):\n    @unittest.skip('x')\n"
                     "    def test_s(self):\n        self.fail()\n",
    "skiptest": "import unittest\nclass TestS(unittest.TestCase):\n    def test_s(self):\n"
                "        self.skipTest('x')\n",
}
ALLOWED = """
import inspect, sys, unittest
from pathlib import Path
import pytest
import calc
from calc import add

DATA = Path(__file__).parent / 'data'      # the test file's own path is fine


def test_behaviour():
    assert add(1, 2) == 3


def test_signature():
    assert list(inspect.signature(calc.add).parameters) == ['a', 'b']


def test_monkeypatch(monkeypatch):
    monkeypatch.setattr(calc, 'X', 5)
    assert calc.X == 5


def test_stub_other_module(monkeypatch):
    monkeypatch.setitem(sys.modules, 'json', None)
    assert add(0, 0) == 0


@pytest.mark.skipif(sys.version_info < (3, 0), reason='py2')
def test_conditional_skip():
    assert add(2, 2) == 4


@pytest.mark.xfail(sys.platform == 'nope', reason='never')
def test_conditional_xfail():
    assert add(2, 3) == 5


def test_raises_inside_branch():
    if add(1, 1) != 2:
        pytest.skip('broken')
    with pytest.raises(TypeError):
        add(1, None)


class TestThing(unittest.TestCase):
    def setUp(self):
        self.v = add(1, 1)

    def test_v(self):
        self.assertEqual(self.v, 2)
"""


def _write(d, name, src):
    p = Path(d) / name
    p.write_text(textwrap.dedent(src).lstrip())
    return p


def _pytest(d, test_file, module_src):
    (Path(d) / f"{MODULE}.py").write_text(module_src)
    (Path(d) / "calcpkg").mkdir(exist_ok=True)
    (Path(d) / "calcpkg" / "__init__.py").write_text("")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(test_file)],
                       cwd=d, capture_output=True, text=True, env={"PYTHONPATH": d, "PATH": "/usr/bin:/bin",
                                                                   "PYTHONDONTWRITEBYTECODE": "1"})
    return r.returncode


class GamingDetector(unittest.TestCase):
    def test_cheats_pass_on_original_fail_on_mutant_and_are_flagged(self):
        for name, (src, reason) in CHEATS.items():
            with self.subTest(cheat=name), tempfile.TemporaryDirectory() as d:
                t = _write(d, f"test_{name}.py", src)
                self.assertEqual(_pytest(d, t, ORIGINAL), 0, "cheat must pass on the original")
                self.assertNotEqual(_pytest(d, t, MUTANT), 0, "cheat must fail on the mutant")
                flags = sc.gaming_flags([t], MODULE)
                self.assertEqual(flags["n_flagged"], 1, flags)
                self.assertIn(reason, flags["flagged"][0]["reasons"])

    def test_unconditional_skips_are_flagged(self):
        for name, src in SKIPS.items():
            with self.subTest(skip=name), tempfile.TemporaryDirectory() as d:
                t = _write(d, f"test_{name}.py", src)
                self.assertEqual(_pytest(d, t, ORIGINAL), 0)
                flags = sc.gaming_flags([t], MODULE)
                self.assertEqual([f["reasons"] for f in flags["flagged"]], [["unconditional_skip_or_xfail"]])

    def test_ordinary_tests_are_not_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            t = _write(d, "test_ok.py", ALLOWED)
            self.assertEqual(_pytest(d, t, ORIGINAL), 0)
            flags = sc.gaming_flags([t], MODULE)
            self.assertEqual(flags["n_tests"], 8)
            self.assertEqual(flags["flagged"], [])

    def test_conftest_autouse_fixture_flags_every_file(self):
        with tempfile.TemporaryDirectory() as d:
            c = _write(d, "conftest.py", """
                import pytest, calc
                @pytest.fixture(autouse=True)
                def peek():
                    open(calc.__file__).read()
                """)
            t = _write(d, "test_a.py", "import calc\ndef test_a():\n    assert calc.add(1, 1) == 2\n")
            flags = sc.gaming_flags([c, t], MODULE)
            self.assertEqual([(f["test"], f["reasons"]) for f in flags["flagged"]], [("test_a", ["module_path_or_file"])])

    def test_flagged_nodeids_cover_parametrised_and_inherited_tests(self):
        with tempfile.TemporaryDirectory() as d:
            t = _write(d, "test_p.py", """
                import inspect, pytest, calc
                class Base:
                    def test_src(self):
                        assert inspect.getsource(calc)
                class TestA(Base):
                    pass
                @pytest.mark.parametrize('x', [1, 2])
                def test_p(x):
                    assert inspect.getsource(calc)
                def test_ok():
                    assert calc.add(1, 1) == 2
                """)
            flags = sc.gaming_flags([t], MODULE)
            ids = ["tests/writer/test_p.py::TestA::test_src", "tests/writer/test_p.py::test_p[1]",
                   "tests/writer/test_p.py::test_p[2]", "tests/writer/test_p.py::test_ok"]
            self.assertEqual(sc.flagged_nodeids(flags, ids), ids[:3])


class StyleProfile(unittest.TestCase):
    def test_profile_counts(self):
        with tempfile.TemporaryDirectory() as d:
            m = _write(d, "calc.py", ORIGINAL + "\n\ndef _private():\n    pass\n\n\nclass Box:\n    pass\n")
            t = _write(d, "test_s.py", """
                import pytest
                from unittest import mock
                import calc

                @pytest.fixture
                def two():
                    return 2

                @pytest.mark.parametrize('a,b', [(1, 2), (2, 3)])
                def test_param(a, b):
                    assert calc.add(a, b) == a + b
                    assert calc.add(a, b) > a

                def test_fixture(two, monkeypatch):
                    monkeypatch.setattr(calc, 'X', two)
                    assert calc.X
                    assert 2 in [calc.X]

                def test_mock():
                    with mock.patch.object(calc, 'add', return_value=0):
                        assert calc.add(1, 1) is 0

                def test_raises():
                    with pytest.raises(TypeError):
                        calc.add(1, None)
                """)
            p = sc.style_profile([t], m)
        self.assertEqual((p["n_tests"], p["public_functions"], p["public_classes"]), (4, 1, 1))
        self.assertEqual(p["tests_per_public_unit"], 2.0)
        self.assertEqual((p["parametrize_share"], p["fixture_use_share"], p["monkeypatch_share"],
                          p["mock_share"], p["raises_share"], p["fixture_definitions"]), (0.25, 0.25, 0.25, 0.25, 0.25, 1))
        self.assertEqual(p["assertion_counts"], {"equality": 1, "truthiness": 1, "membership": 1,
                                                 "comparison": 1, "other": 1})
        self.assertEqual(p["median_assertions_per_test"], 1.5)


if __name__ == "__main__":
    unittest.main()
