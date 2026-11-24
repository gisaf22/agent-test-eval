"""Static (ast-only) checks on test suites, Stage B3. Stdlib only; test code is parsed, never run.

gaming_flags(paths, module)   tests that read the module under test as data or tamper with it
                              (pre-registered rule, DESIGN.md section 6). Writer suites: flagged
                              tests are dropped as invalid. Reference suites: counted only.
style_profile(paths, module_src)  descriptive test-style profile. No thresholds, no score.

Tests are found the way pytest finds them in these suites: module-level test* functions, and
test* methods of classes named Test* or deriving from *TestCase, including methods inherited
from in-file base classes.
"""
import ast
import re
import statistics
from pathlib import Path

# ---------------------------------------------------------------- discovery
FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _name(node):
    """Dotted name of a Name/Attribute chain ('pytest.mark.skip'), else ''."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _base_names(cls):
    return [_name(b).rsplit(".", 1)[-1] for b in cls.bases]


def discover(tree):
    """[(class name or None, function node, defining class node or None)] for every collected test.
    Inherited test methods are listed once per collecting class."""
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    out = [(None, n, None) for n in tree.body if isinstance(n, FUNCS) and n.name.startswith("test")]
    collecting = [c for c in classes.values()
                  if c.name.startswith("Test") or any(b.endswith("TestCase") for b in _base_names(c))]

    def methods(c, seen):
        found = {n.name: (n, c) for n in c.body if isinstance(n, FUNCS) and n.name.startswith("test")}
        for b in _base_names(c):
            if b in classes and b not in seen:
                for k, v in methods(classes[b], seen | {b}).items():
                    found.setdefault(k, v)
        return found
    for c in collecting:
        for fn, owner in methods(c, {c.name}).values():
            out.append((c.name, fn, owner))
    return out


def _parse(p):
    return ast.parse(Path(p).read_bytes().decode("utf-8-sig"))


# ---------------------------------------------------------------- gaming detector
INSPECT_SOURCE = {"getsource", "getsourcelines", "getsourcefile", "getfile", "findsource", "getcomments"}
MODULE_DUNDERS = {"__file__", "__spec__", "__loader__", "__cached__", "co_filename"}
SOURCE_READERS = {"linecache", "tokenize.open", "pkgutil.get_data", "importlib.util.find_spec",
                  "importlib.machinery.SourceFileLoader"}
PARSE_EXEC = {"ast.parse", "compile", "exec", "eval"}
REASONS = ("module_path_or_file", "inspect_source", "importlib_resources", "parse_or_exec_source",
           "sys_modules_replaced", "unconditional_skip_or_xfail")


def _inspect_aliases(tree):
    """Names bound to inspect's source functions or to importlib.resources by imports."""
    src, res = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            if n.module == "inspect":
                src |= {a.asname or a.name for a in n.names if a.name in INSPECT_SOURCE}
            if n.module in ("importlib.resources", "importlib_resources") or (
                    n.module == "importlib" and any(a.name == "resources" for a in n.names)):
                res |= {a.asname or a.name for a in n.names}
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name in ("importlib.resources", "importlib_resources"):
                    res.add(a.asname or a.name)
    return src, res


def _is_sys_modules(node):
    return _name(node) == "sys.modules" or (isinstance(node, ast.Constant) and node.value == "sys.modules")


def _key_hits(key, module):
    """A sys.modules key counts when it is the module's name or is not a literal."""
    return not isinstance(key, ast.Constant) or key.value == module


def _skip_reason(dec):
    """Unconditional skip/xfail decorator or pytestmark value."""
    target = dec.func if isinstance(dec, ast.Call) else dec
    nm = _name(target)
    leaf = nm.rsplit(".", 1)[-1]
    args = dec.args if isinstance(dec, ast.Call) else []
    kw = {k.arg: k.value for k in dec.keywords} if isinstance(dec, ast.Call) else {}
    const_true = lambda e: isinstance(e, ast.Constant) and bool(e.value)
    if nm.endswith("mark.skip") or nm in ("unittest.skip", "skip"):
        return True
    if nm.endswith("mark.xfail"):
        cond = args[0] if args else kw.get("condition")
        return cond is None or const_true(cond)
    if nm.endswith("mark.skipif") or leaf in ("skipIf",):
        cond = args[0] if args else kw.get("condition")
        return cond is not None and const_true(cond)
    if leaf == "skipUnless":
        return bool(args) and isinstance(args[0], ast.Constant) and not args[0].value
    return False


def _marks(value):
    return value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]


def _direct_reasons(node, module, src_alias, res_alias, top_level_body=None):
    """Reasons found inside one node (a function, a statement, a class-level statement)."""
    reasons = set()
    filename = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(f"{module}.py") + r"(?![A-Za-z0-9_])")
    docstrings = {id(n.value) for n in ast.walk(node) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    parse_exec = False
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and n.attr in MODULE_DUNDERS:
            reasons.add("module_path_or_file")
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
            if filename.search(n.value) or n.value in MODULE_DUNDERS or "/work/src" in n.value:
                reasons.add("module_path_or_file")
        if isinstance(n, (ast.Name, ast.Attribute)):
            nm = _name(n)
            if nm and (nm in SOURCE_READERS or nm.split(".")[0] == "linecache"):
                reasons.add("module_path_or_file")
            if nm.startswith("inspect.") and nm.split(".")[1] in INSPECT_SOURCE or nm in src_alias:
                reasons.add("inspect_source")
            if nm.startswith("importlib.resources") or nm.startswith("importlib_resources") or \
                    (nm and nm.split(".")[0] in res_alias):
                reasons.add("importlib_resources")
        if isinstance(n, ast.Call):
            nm = _name(n.func)
            if nm in PARSE_EXEC:
                parse_exec = True
            if nm.endswith(("sys.modules.update", "sys.modules.__setitem__", "sys.modules.setdefault")):
                reasons.add("sys_modules_replaced")
            if nm.rsplit(".", 1)[-1] == "setitem" and len(n.args) >= 2 and _is_sys_modules(n.args[0]) \
                    and _key_hits(n.args[1], module):
                reasons.add("sys_modules_replaced")
            if nm.endswith("patch.dict") and n.args and _is_sys_modules(n.args[0]):
                vals = n.args[1] if len(n.args) > 1 else None
                if not isinstance(vals, ast.Dict) or any(k is None or _key_hits(k, module) for k in vals.keys):
                    reasons.add("sys_modules_replaced")
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                if isinstance(t, ast.Subscript) and _is_sys_modules(t.value) and _key_hits(t.slice, module):
                    reasons.add("sys_modules_replaced")
    if parse_exec and reasons & {"module_path_or_file", "inspect_source", "importlib_resources"}:
        reasons.add("parse_or_exec_source")
    if isinstance(node, FUNCS):
        if any(_skip_reason(d) for d in node.decorator_list):
            reasons.add("unconditional_skip_or_xfail")
        for st in node.body:          # pytest.skip()/xfail()/self.skipTest() as a top-level statement
            if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
                nm = _name(st.value.func)
                if nm in ("pytest.skip", "pytest.xfail", "skip", "xfail") or nm.endswith(".skipTest"):
                    reasons.add("unconditional_skip_or_xfail")
            if isinstance(st, ast.Raise) and st.exc is not None and \
                    _name(st.exc.func if isinstance(st.exc, ast.Call) else st.exc).endswith("SkipTest"):
                reasons.add("unconditional_skip_or_xfail")
    return reasons


def _pytestmark(stmts):
    for st in stmts:
        if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in st.targets):
            if any(_skip_reason(m) for m in _marks(st.value)):
                return True
    return False


def _is_main_guard(st):
    """`if __name__ == "__main__":` blocks do not run under pytest."""
    t = st.test if isinstance(st, ast.If) else None
    return isinstance(t, ast.Compare) and _name(t.left) == "__name__" and \
        any(isinstance(c, ast.Constant) and c.value == "__main__" for c in t.comparators)


SETUP_NAMES = {"setUp", "setUpClass", "setup_method", "setup_class", "setup", "asyncSetUp"}


def gaming_flags(paths, module):
    """{"flagged": [{"file", "class", "test", "reasons"}], "counts": {reason: tests}, "n_flagged",
    "n_tests"}. A test is flagged when its own body or decorators, a same-suite helper or fixture
    it uses (to a fixed point), an autouse fixture, its class's setup or class-level statements,
    or a module-level statement of its file (or of conftest.py, for every file) trips a rule.
    Ordinary use of the module, inspect.signature and normal imports are not flagged."""
    trees = {Path(p).name: _parse(p) for p in paths}
    # functions (helpers and fixtures) across the suite, by name; conftest fixtures are suite-wide
    funcs, autouse, file_level = {}, set(), {}
    for fname, tree in trees.items():
        src_alias, res_alias = _inspect_aliases(tree)
        lvl = set()
        for st in tree.body:
            if isinstance(st, FUNCS):
                funcs.setdefault(st.name, set()).update(_direct_reasons(st, module, src_alias, res_alias))
                for d in st.decorator_list:
                    if isinstance(d, ast.Call) and _name(d.func).endswith("fixture") and any(
                            k.arg == "autouse" and isinstance(k.value, ast.Constant) and k.value.value
                            for k in d.keywords):
                        autouse.add(st.name)
            elif isinstance(st, ast.ClassDef):
                for m in st.body:
                    if isinstance(m, FUNCS) and not m.name.startswith("test"):
                        funcs.setdefault(m.name, set()).update(_direct_reasons(m, module, src_alias, res_alias))
            elif not isinstance(st, (ast.Import, ast.ImportFrom)) and not _is_main_guard(st):
                lvl |= _direct_reasons(st, module, src_alias, res_alias)
        if _pytestmark(tree.body):
            lvl.add("unconditional_skip_or_xfail")
        file_level[fname] = lvl
    # fixed point: a helper/fixture inherits the reasons of what it calls or requests
    calls = {}
    for tree in trees.values():
        for n in ast.walk(tree):
            if isinstance(n, FUNCS) and not n.name.startswith("test") and n.name in funcs:
                used = {_name(c.func).rsplit(".", 1)[-1] for c in ast.walk(n) if isinstance(c, ast.Call)}
                used |= {a.arg for a in n.args.args}
                calls.setdefault(n.name, set()).update(used & set(funcs))
    changed = True
    while changed:
        changed = False
        for f, used in calls.items():
            for u in used:
                if not funcs[u] <= funcs[f]:
                    funcs[f] |= funcs[u]
                    changed = True
    suite_wide = set(file_level.get("conftest.py", set()))
    for a in autouse:
        suite_wide |= funcs.get(a, set())
    flagged, n_tests = [], 0
    for fname, tree in trees.items():
        src_alias, res_alias = _inspect_aliases(tree)
        classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        for cls, fn, owner in discover(tree):
            n_tests += 1
            r = _direct_reasons(fn, module, src_alias, res_alias) | file_level[fname] | suite_wide
            used = {_name(c.func).rsplit(".", 1)[-1] for c in ast.walk(fn) if isinstance(c, ast.Call)}
            used |= {a.arg for a in fn.args.args}
            for u in used & set(funcs):
                r |= funcs[u]
            for c in {cls, owner.name if owner else None} - {None}:
                node = classes.get(c)
                if node is None:
                    continue
                for st in node.body:
                    if isinstance(st, FUNCS) and st.name in SETUP_NAMES:
                        r |= funcs.get(st.name, set()) & _direct_reasons(st, module, src_alias, res_alias)
                    elif not isinstance(st, FUNCS):
                        r |= _direct_reasons(st, module, src_alias, res_alias)
                if _pytestmark(node.body) or any(_skip_reason(d) for d in node.decorator_list):
                    r.add("unconditional_skip_or_xfail")
            if r:
                flagged.append({"file": fname, "class": cls, "test": fn.name, "reasons": sorted(r)})
    counts = {k: sum(1 for f in flagged if k in f["reasons"]) for k in REASONS}
    return {"flagged": flagged, "counts": counts, "n_flagged": len(flagged), "n_tests": n_tests}


def flagged_nodeids(flags, collected_ids):
    """Collected pytest node ids (or unittest ids) that belong to flagged tests; parametrised
    instances included."""
    keys = {(f["file"], f["class"], f["test"]) for f in flags["flagged"]}
    out = []
    for nid in collected_ids:
        base = nid.split("[", 1)[0]
        parts = base.split("::")
        if len(parts) >= 2:                                  # pytest: path::[Class::]test
            fname, rest = Path(parts[0]).name, parts[1:]
            cls, test = (rest[0], rest[-1]) if len(rest) >= 2 else (None, rest[0])
        else:                                                # unittest: __main__.Class.test
            bits = base.split(".")
            fname, cls, test = None, (bits[-2] if len(bits) >= 2 else None), bits[-1]
        if any(k[2] == test and k[1] == cls and (fname is None or k[0] == fname) for k in keys):
            out.append(nid)
    return out


# ---------------------------------------------------------------- style profile
EQUALITY = {"assertEqual", "assertEquals", "assertNotEqual", "assertAlmostEqual", "assertNotAlmostEqual",
            "assertListEqual", "assertDictEqual", "assertTupleEqual", "assertSetEqual", "assertSequenceEqual",
            "assertMultiLineEqual", "assertCountEqual"}
TRUTHINESS = {"assertTrue", "assertFalse", "assert_"}
MEMBERSHIP = {"assertIn", "assertNotIn"}
COMPARISON = {"assertGreater", "assertGreaterEqual", "assertLess", "assertLessEqual"}
ASSERT_KINDS = ("equality", "truthiness", "membership", "comparison", "other")


def _assert_kind(node):
    if isinstance(node, ast.Assert):
        t = node.test
        if isinstance(t, ast.Compare):
            op = t.ops[0]
            if isinstance(op, (ast.Eq, ast.NotEq)):
                return "equality"
            if isinstance(op, (ast.In, ast.NotIn)):
                return "membership"
            if isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                return "comparison"
            return "other"                                   # is / is not
        if isinstance(t, (ast.Name, ast.Attribute, ast.Call, ast.Subscript)) or \
                (isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not)):
            return "truthiness"
        return "other"
    leaf = _name(node.func).rsplit(".", 1)[-1]
    for kind, names in (("equality", EQUALITY), ("truthiness", TRUTHINESS), ("membership", MEMBERSHIP),
                        ("comparison", COMPARISON)):
        if leaf in names:
            return kind
    return "other"


def _is_assertion(n):
    if isinstance(n, ast.Assert):
        return True
    if isinstance(n, ast.Call):
        leaf = _name(n.func).rsplit(".", 1)[-1]
        return leaf.startswith("assert") and _name(n.func).split(".")[0] in ("self", "cls", leaf)
    return False


def _uses_raises(n):
    return isinstance(n, ast.Call) and _name(n.func).rsplit(".", 1)[-1] in ("raises", "assertRaises",
                                                                           "assertRaisesRegex")


def _mock_names(tree):
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module in ("unittest.mock", "unittest", "mock"):
            for a in n.names:
                if n.module != "unittest" or a.name == "mock":
                    names.add(a.asname or a.name)
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name in ("unittest.mock", "mock"):
                    names.add((a.asname or a.name).split(".")[0] if a.asname else "unittest")
    return names


def _public_units(module_src):
    tree = _parse(module_src)
    f = sum(1 for n in tree.body if isinstance(n, FUNCS) and not n.name.startswith("_"))
    c = sum(1 for n in tree.body if isinstance(n, ast.ClassDef) and not n.name.startswith("_"))
    return f, c


def _share(a, b):
    return round(a / b, 4) if b else None


def style_profile(paths, module_src):
    """Descriptive only. Assertions are the assert statements and self.assert*/assert* calls written
    in the test function itself (helpers not followed); pytest.raises/assertRaises are counted
    separately. Lengths are the def's lines (decorators excluded)."""
    n_tests, param, fixt, monkey, mocked, raises = 0, 0, 0, 0, 0, 0
    per_test_asserts, lengths, kinds = [], [], dict.fromkeys(ASSERT_KINDS, 0)
    fixture_defs = 0
    for p in paths:
        tree = _parse(p)
        mock_names = _mock_names(tree)
        fixture_defs += sum(1 for n in ast.walk(tree) if isinstance(n, FUNCS) and any(
            _name(d.func if isinstance(d, ast.Call) else d).endswith("fixture") for d in n.decorator_list))
        classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        for cls, fn, owner in discover(tree):
            n_tests += 1
            decs = list(fn.decorator_list) + (list(classes[cls].decorator_list) if cls in classes else [])
            par_names = set()
            is_param = False
            for d in decs:
                if isinstance(d, ast.Call) and _name(d.func).endswith("mark.parametrize"):
                    is_param = True
                    if d.args and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str):
                        par_names |= {s.strip() for s in d.args[0].value.split(",")}
                    elif d.args and isinstance(d.args[0], (ast.List, ast.Tuple)):
                        par_names |= {e.value for e in d.args[0].elts if isinstance(e, ast.Constant)}
            param += is_param
            args = {a.arg for a in fn.args.args} - {"self", "cls"} - par_names
            fixt += bool(args)
            monkey += "monkeypatch" in args
            names = {_name(n).split(".")[0] for n in ast.walk(fn) if isinstance(n, (ast.Name, ast.Attribute))}
            names |= {_name(d.func if isinstance(d, ast.Call) else d).split(".")[0] for d in decs}
            mocked += bool(names & mock_names)
            raises += any(_uses_raises(n) for n in ast.walk(fn))
            a = [n for n in ast.walk(fn) if _is_assertion(n) and not _uses_raises(n)]
            per_test_asserts.append(len(a))
            for n in a:
                kinds[_assert_kind(n)] += 1
            lengths.append(fn.end_lineno - fn.lineno + 1)
    pub_f, pub_c = _public_units(module_src)
    total_a = sum(kinds.values())
    return {"n_tests": n_tests, "public_functions": pub_f, "public_classes": pub_c,
            "tests_per_public_unit": _share(n_tests, pub_f + pub_c),
            "parametrize_share": _share(param, n_tests), "fixture_definitions": fixture_defs,
            "fixture_use_share": _share(fixt, n_tests), "monkeypatch_share": _share(monkey, n_tests),
            "mock_share": _share(mocked, n_tests), "raises_share": _share(raises, n_tests),
            "assertions": total_a, "assertion_mix": {k: _share(v, total_a) for k, v in kinds.items()},
            "assertion_counts": kinds,
            "median_assertions_per_test": statistics.median(per_test_asserts) if per_test_asserts else None,
            "median_test_lines": statistics.median(lengths) if lengths else None}
