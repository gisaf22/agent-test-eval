#!/usr/bin/env python3
"""Mutation-score measurement loop (harness A2).

Suites per module (each suite is a directory of one or more test files):
  null      tests/<m>/null_test.py      imports the module, asserts nothing; defines
                                        which mutants are trivially killed
  strong    tests/<m>/strong_test.py    constructed control (AI-generated, strength-by-design)
  weak      tests/<m>/weak_test.py      constructed control (AI-generated, strength-by-design)
  upstream  tests/<m>/upstream_test.py  the project's own tests, unedited (corpus/metadata.json)

Per module, in one long-lived offline container:
  1. Test-level validity: every suite runs VALIDITY_RUNS times on the original code, each run
     in a seeded random test order with its own PYTHONHASHSEED, without failfast. A test that
     fails (or is missing from) any run is dropped: "wrong" if it fails every run, "flaky" if
     only some. `valid_file_level` keeps the old strict view (every run of the whole suite passed).
  2. Scoring runs use pytest's own order and PYTHONHASHSEED=0, on the kept tests only:
     3 fixed-order baseline runs (all must pass), coverage, then mutants.
  3. Mutants: cosmic-ray, sampled once per module, stratified by operator category, seeded,
     capped at --max-mutants (default 100); the same set is used for every suite. Each mutant
     is applied to the pristine file, tested and reverted; the revert is checked.
  4. Optional mutmut 2 cross-check (--mutmut) on the same suites, all mutmut mutants.
Rows go to results.jsonl (append-only, one run_id per invocation), per-mutant records to
results_mutants.jsonl and mutmut rows to results_mutmut.jsonl. Repeatability is checked
against the previous run with the same harness_version.

Metrics: mutation_score = killed / mutants_used (timeouts count as killed);
mutation_score_nontrivial excludes mutants the null suite kills; assertion_kill_rate(_nontrivial);
kill causes killed_by_{assertion,test_exception,collection_error,crash} + timeouts;
mutation_by_category; coverage (line, branch), function/class share, weak-assertion rates
and test counts are reported as outcomes only.

env_id = sha256(base_image_digest, dockerfile_sha256, packages_sha256); its inputs are
recorded in `env_id_inputs`. Host side is stdlib only. Usage: python3 run_eval.py [--help]
"""
import argparse
import ast
import hashlib
import io
import json
import random
import re
import subprocess
import sys
import tarfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import static_checks

ROOT = Path(__file__).resolve().parent
SANDBOX = ROOT / "sandbox"
IMAGE = "agent-test-eval-sandbox:a2"
HARNESS_VERSION = "A2.1"   # A2.1: static test discovery follows in-file base classes; 0/0 shares are null
# B3: additive scorer revision. Scores of existing suite types are unchanged (DECISIONS.md, Stage B3),
# so HARNESS_VERSION and the stored-null key stay A2.1; rows record the revision separately.
SCORER_REVISION = "B3"
PREREG_TAG = "prereg-v1"
REFERENCE_TAGS = {"full"}          # reference-mode runs may be tagged only for the pre-registered run
CONSTANT_OPERATORS = {"core/NumberReplacer"}   # number-constant replacements (logic score excludes them)
MODULES = ["toposort", "heapdict", "mergedeep", "addict"]
NULL_LABEL = "null_test.py"
CONTROL_LABELS = ["strong_test.py", "weak_test.py"]
SEED = 20261117
MAX_MUTANTS = 100
VALIDITY_RUNS = 10
BASELINE_RUNS = 3
MODULE_BUDGET_S = 20 * 60  # stop rule: everything for one module together
RESULTS = ROOT / "results.jsonl"
DETAILS = ROOT / "results_mutants.jsonl"
MUTMUT_RESULTS = ROOT / "results_mutmut.jsonl"
METADATA = ROOT / "corpus" / "metadata.json"     # Stage 0 upstream-test details
CORPUS_FINAL = ROOT / "corpus_final.json"         # every usable corpus module (B2a/B2b)
NULL_STORE = ROOT / "results_null.jsonl"          # null rows scored once per module, reused (B2b)
HARNESS_FILES = ["runner.py", "killtype_plugin.py", "suite_plugin.py", "script_wrapper.py", "alias_plugin.py",
                 "as_user.py"]
KILL_KINDS = ["assertion", "test_exception", "collection_error", "crash"]
RUN_SCHEMA_NULLS = {"model_id": None, "effort": None, "prompt_hash": None,
                    "tokens_in": None, "tokens_out": None, "estimated_cost": None}

DOCKER_RUN_FLAGS = [
    "--network", "none",
    "--user", "10001:10001",
    "--read-only",
    "--tmpfs", "/work:rw,nosuid,nodev,size=64m,uid=10001,gid=10001,mode=0700",
    "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,uid=10001,gid=10001,mode=0700",
    "--memory", "512m", "--memory-swap", "512m",
    "--cpus", "1",
    "--pids-limit", "128",
    "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges",
]
# B3 scoring sandbox: /work is root-owned and the runner is exec'd as root with only the
# capabilities it needs to start the test processes as uid 10001 and to kill them (SETUID, SETGID,
# KILL). Test processes have no capabilities and cannot write the module, the harness or the
# suites, or read /work/ctl (mutant list). The writer's feedback sandbox keeps DOCKER_RUN_FLAGS.
SCORING_RUN_FLAGS = [
    "--network", "none",
    "--user", "10001:10001",
    "--read-only",
    "--tmpfs", "/work:rw,nosuid,nodev,size=64m,uid=0,gid=0,mode=0755",
    "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
    "--memory", "512m", "--memory-swap", "512m",
    "--cpus", "1",
    "--pids-limit", "128",
    "--cap-drop", "ALL",
    "--cap-add", "SETUID", "--cap-add", "SETGID", "--cap-add", "KILL",
    "--security-opt", "no-new-privileges",
]


class InfraError(RuntimeError):
    pass


def sh(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        raise InfraError(f"{cmd[:4]} exited {r.returncode}: {(r.stderr or '')[-500:]}")
    return r.stdout


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def normalise_freeze(text):
    return "\n".join(sorted((ln.strip() for ln in text.splitlines() if ln.strip()),
                            key=str.lower)) + "\n"


def environment_identity():
    """Stable identifier computed from pinned inputs, not from the build output."""
    dockerfile = (SANDBOX / "Dockerfile").read_bytes()
    froms = re.findall(rb"^FROM\s+(\S+)", dockerfile, re.M)
    if len(froms) != 1 or b"@sha256:" not in froms[0]:
        raise InfraError(f"Dockerfile must have one FROM pinned by digest, got {froms}")
    base = froms[0].decode()
    lock = normalise_freeze((SANDBOX / "requirements.lock").read_text())
    inputs = {"base_image_digest": base.split("@", 1)[1],
              "dockerfile_sha256": sha256(dockerfile),
              "packages_sha256": sha256(lock.encode())}
    ident = {**inputs, "base_image_ref": base, "env_id_inputs": inputs}
    ident["env_id"] = sha256(json.dumps(
        [inputs["base_image_digest"], inputs["dockerfile_sha256"], inputs["packages_sha256"]]
    ).encode())
    return ident, lock


def build_and_verify_image():
    ident, lock = environment_identity()
    sh(["docker", "build", "-q", "-t", IMAGE, str(SANDBOX)])
    freeze = sh(["docker", "run", "--rm", "--network", "none", IMAGE,
                 "pip", "freeze", "--all", "--exclude", "pip"])
    if normalise_freeze(freeze) != lock:
        raise InfraError("built image's pip freeze does not match sandbox/requirements.lock")
    return ident


# ---------------------------------------------------------------- suites
def module_meta(module):
    """Metadata for any usable corpus module: module file, sha256 and the fixed mutant set's
    sha256 from corpus_final.json; upstream-test details from corpus/metadata.json (Stage 0)."""
    final = json.loads(CORPUS_FINAL.read_text())
    entry = next((m for m in final["primary"] + final["baseline"] if m["name"] == module), None)
    if entry is None:
        raise InfraError(f"{module}: not a usable module in {CORPUS_FINAL.name}")
    stage0 = {e["name"]: e for e in json.loads(METADATA.read_text())}.get(module, {})
    return {"name": module, "module_path": ROOT / entry["module_file"], "module_sha256": entry["module_sha256"],
            "mutant_set_sha256": entry["mutant_set_sha256"], "set": "primary" if entry in final["primary"] else "baseline",
            "upstream_tests": stage0.get("upstream_tests"), "entry": entry}


def upstream_aliases(entry, test_path):
    """{repo dotted name: flat module name} for the upstream test's imports of the module (ast only).
    Candidates are the dotted suffixes of the module's repo path (src/trace2task/experience.py ->
    trace2task.experience, ...); a candidate counts when the test imports it, or imports a name
    from its parent package (`from wtftd import blk`)."""
    parts = Path(entry["path"]).with_suffix("").parts
    cands = {".".join(parts[i:]) for i in range(len(parts) - 1)}
    tree = ast.parse(test_path.read_bytes().decode("utf-8-sig"))
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            imported.add(n.module)
            imported |= {f"{n.module}.{a.name}" for a in n.names}
    return {c: entry["name"] for c in sorted(cands & imported)}


def upstream_spec(module):
    """B3: the upstream reference suite of a non-Stage-0 module whose upstream test passed standalone
    in the B2a smoke check (corpus_final.json upstream_smoke.passed), or None. The file is used
    unedited; it is placed as tests/upstream/upstream_test.py and imports the scored module through
    alias_plugin. Stage 0 upstream suites keep their corpus/metadata.json wiring."""
    e = module_meta(module)["entry"]
    path = ROOT / "corpus" / module / "upstream_test.txt"
    if e["stage0"] or not (e.get("upstream_smoke") or {}).get("passed") or not path.exists():
        return None
    aliases = upstream_aliases(e, path)
    if not aliases:
        return None
    return {"label": "upstream", "suite": "upstream", "paths": [path], "dest": {path.name: "upstream_test.py"},
            "mode": "pytest", "upstream_path": e["upstream_test"], "not_runnable": None, "aliases": aliases}


def prereg_commit():
    """Commit of the prereg-v1 tag, or None while the tag does not exist (B3: design_commit)."""
    r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", f"refs/tags/{PREREG_TAG}^{{commit}}"],
                       capture_output=True, text=True)
    return r.stdout.strip() or None if r.returncode == 0 else None


def suite_specs(module, writer=None):
    """[{label, suite, paths, mode, upstream_path, not_runnable}], null suite first.
    A suite's paths may be one file or a directory's *.py files. Reference mode: null, then
    strong/weak where they exist (Stage 0), then upstream (Stage 0 metadata). Writer mode
    (`writer` = a writer.py meta.json dict): null, then the writer suite, scored exactly like
    the others; evaluate_module drops the null when a stored null row can be reused."""
    def files(p):
        return sorted(p.glob("*.py")) if p.is_dir() else [p]
    base = ROOT / "tests" / module
    spec = lambda s: {"label": f"{s}_test.py", "suite": s, "paths": files(base / f"{s}_test.py"),
                      "mode": "pytest", "upstream_path": None, "not_runnable": None}
    specs = [spec("null")]
    if writer:
        return specs + [{"label": "writer", "suite": "writer", "paths": files(ROOT / writer["suite_dir"]),
                         "mode": "pytest", "upstream_path": None, "not_runnable": None}]
    specs += [spec(s) for s in ("strong", "weak") if (base / f"{s}_test.py").exists()]
    up = module_meta(module)["upstream_tests"]
    if up:
        specs.append({"label": "upstream", "suite": "upstream", "paths": files(base / "upstream_test.py"),
                      "mode": up["runner"], "upstream_path": up["path"],
                      "not_runnable": up.get("not_runnable")})
    elif upstream_spec(module):
        specs.append(upstream_spec(module))
    return specs


def null_key(module, ident, mutant_set_sha256):
    null = ROOT / "tests" / module / NULL_LABEL
    return {"module": module, "harness_version": HARNESS_VERSION, "env_id": ident["env_id"],
            "mutant_set_sha256": mutant_set_sha256, "null_suite_sha256": sha256(null.read_bytes())}


def stored_null(key):
    """The first stored null row with exactly this key, or None."""
    for r in _load(NULL_STORE):
        if r["key"] == key:
            return r
    return None


def tar_bytes(files, mode=0o600, uid=10001, private_dirs=()):
    """files: {arcname: host Path or bytes}. Default: owned by the sandbox user, mode 0600 (the
    writer's feedback sandbox). The scoring sandbox extracts as root with mode 0644, except files
    under `private_dirs`, which get a 0700 directory entry and mode 0600 (root only)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for d in private_dirs:
            ti = tarfile.TarInfo(d)
            ti.type, ti.mode, ti.uid, ti.gid, ti.mtime = tarfile.DIRTYPE, 0o700, uid, uid, 0
            tf.addfile(ti)
        for arc, src in files.items():
            data = src if isinstance(src, bytes) else src.read_bytes()
            ti = tarfile.TarInfo(arc)
            private = any(arc.startswith(d + "/") for d in private_dirs)
            ti.size, ti.mode, ti.uid, ti.gid, ti.mtime = len(data), 0o600 if private else mode, uid, uid, 0
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


class Sandbox:
    """A fresh container per use. scoring=True: the B3 privilege split (SCORING_RUN_FLAGS); files go
    in root-owned and world-readable, `ctl/` root-only, and exec runs as root (the runner)."""

    def __init__(self, module, scoring=False):
        self.name = f"ate-{module}-{uuid.uuid4().hex[:8]}"
        self.scoring = scoring
        self.user = ["-u", "0"] if scoring else []

    def __enter__(self):
        # No -e/--env-file: the container gets only the image's own environment.
        sh(["docker", "run", "-d", "--name", self.name, *(SCORING_RUN_FLAGS if self.scoring else DOCKER_RUN_FLAGS),
            IMAGE, "sleep", "infinity"])
        return self

    def __exit__(self, *exc):
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)

    def put(self, files):
        # docker cp is refused on read-only-rootfs containers (even into tmpfs).
        if self.scoring:
            cmd, data = ["tar", "-x", "--no-same-owner", "-C", "/work"], tar_bytes(
                files, mode=0o644, uid=0, private_dirs=("ctl",) if any(a.startswith("ctl/") for a in files) else ())
        else:
            cmd, data = ["tar", "-x", "-C", "/work"], tar_bytes(files)
        r = subprocess.run(["docker", "exec", "-i", *self.user, self.name, *cmd], input=data, capture_output=True)
        if r.returncode != 0:
            raise InfraError(f"tar into sandbox failed: {r.stderr[-300:]!r}")

    def exec(self, *args, timeout=None):
        return sh(["docker", "exec", *self.user, self.name, *args], timeout=timeout)

    def alive(self):
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", self.name],
                           capture_output=True, text=True)
        return r.stdout.strip() == "true"


# ---------------------------------------------------------------- mutant sampling
_CATEGORY_RULES = [
    (r"^core/ReplaceBinaryOperator_", "arithmetic"),
    (r"^core/ReplaceUnaryOperator_Delete_Not$", "boolean_logic"),
    (r"^core/ReplaceUnaryOperator_", "arithmetic"),
    (r"^core/ReplaceComparisonOperator_", "comparison"),
    (r"^core/(AddNot|ReplaceAndWithOr|ReplaceOrWithAnd)$", "boolean_logic"),
    (r"^core/(NumberReplacer|ReplaceTrueWithFalse|ReplaceFalseWithTrue)$", "constant"),
    (r"^core/(ZeroIterationForLoop|ReplaceBreakWithContinue|ReplaceContinueWithBreak)$", "control_flow"),
    (r"^core/ExceptionReplacer$", "exception"),
    (r"^core/RemoveDecorator$", "decorator"),
]


def operator_category(op):
    for pat, cat in _CATEGORY_RULES:
        if re.match(pat, op):
            return cat
    raise InfraError(f"operator {op!r} has no category; extend _CATEGORY_RULES")


def select_mutants(all_mutants, seed, cap):
    """Stratified by operator category: each category gets a share of the cap proportional to its
    size (largest remainder, at least 1 per category), then a seeded sample within it.
    Canonical order first, because cosmic-ray's DB order is by random job id."""
    canon = sorted(all_mutants, key=lambda m: (m["operator"], m["occurrence"]))
    keys = [(m["operator"], m["occurrence"]) for m in canon]
    if len(set(keys)) != len(keys):
        raise InfraError("duplicate (operator, occurrence) keys in mutant list")
    strata = {}
    for m in canon:
        strata.setdefault(operator_category(m["operator"]), []).append({**m, "category": operator_category(m["operator"])})
    total = len(canon)
    if total <= cap:
        alloc = {c: len(ms) for c, ms in strata.items()}
    else:
        if len(strata) > cap:
            raise InfraError(f"cap {cap} < number of categories {len(strata)}")
        quota = {c: cap * len(ms) / total for c, ms in strata.items()}
        alloc = {c: max(1, int(q)) for c, q in quota.items()}
        while sum(alloc.values()) < cap:
            c = max((c for c in strata if alloc[c] < len(strata[c])),
                    key=lambda c: (quota[c] - alloc[c], c))
            alloc[c] += 1
        while sum(alloc.values()) > cap:
            c = max((c for c in strata if alloc[c] > 1), key=lambda c: (alloc[c] - quota[c], c))
            alloc[c] -= 1
    picked = []
    for c in sorted(strata):
        ms = list(strata[c])
        random.Random(f"{seed}:{c}").shuffle(ms)
        picked += ms[:alloc[c]]
    random.Random(seed).shuffle(picked)          # run order: categories interleaved
    return picked, {c: {"available": len(strata[c]), "sampled": alloc[c]} for c in sorted(strata)}


# ---------------------------------------------------------------- static measures (ast only)
def _is_assert_call(node):
    f = node.func
    name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
    if name.startswith(("assert", "fail")) and name not in ("failureException",):
        return True
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "pytest" \
            and f.attr in ("raises", "warns", "fail", "deprecated_call"):
        return True
    return False


def _trivial(node):
    """assert <constant>, assert x == x / x is x, assertTrue(<constant>), assertEqual(x, x)."""
    if isinstance(node, ast.Assert):
        t = node.test
        if isinstance(t, ast.Constant):
            return True
        if isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], (ast.Eq, ast.Is)) \
                and ast.dump(t.left) == ast.dump(t.comparators[0]):
            return True
        return False
    name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
    args = node.args
    if name in ("assertTrue", "assertIsNotNone", "assert_") and args and isinstance(args[0], ast.Constant):
        return True
    if name in ("assertEqual", "assertEquals", "assertIs") and len(args) >= 2 \
            and ast.dump(args[0]) == ast.dump(args[1]):
        return True
    return False


def static_test_measures(paths):
    """Tests found by ast: module-level test* functions and test* methods of classes named Test*
    or deriving from *TestCase. Assertions: assert statements, assert*/fail* calls, pytest.raises/
    warns/fail; calls to same-file helpers that assert count (3 levels)."""
    tests, n_assert, per_test = [], 0, []
    for p in paths:
        tree = ast.parse(p.read_bytes().decode("utf-8-sig"))
        helpers = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                helpers.setdefault(node.name, node)

        def asserts_in(fn, depth=0, seen=None):
            seen = seen or set()
            found = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)
                     or (isinstance(n, ast.Call) and _is_assert_call(n))]
            if depth < 3:
                for n in ast.walk(fn):
                    if isinstance(n, ast.Call):
                        nm = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
                        h = helpers.get(nm)
                        if h is not None and h is not fn and nm not in seen and not nm.startswith("test"):
                            found += asserts_in(h, depth + 1, seen | {nm})
            return found

        cands = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name.startswith("test")]
        classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        bases_of = {c.name: [b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "") for b in c.bases]
                    for c in classes.values()}
        test_classes = {c for c in classes if c.startswith("Test") or any(b.endswith("TestCase") for b in bases_of[c])}
        frontier = list(test_classes)            # in-file base classes (mixins) of test classes hold tests too
        while frontier:
            for b in bases_of[frontier.pop()]:
                if b in classes and b not in test_classes:
                    test_classes.add(b)
                    frontier.append(b)
        for c in [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in test_classes]:
            cands += [n for n in c.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and n.name.startswith("test")]
        for t in cands:
            a = asserts_in(t)
            n_assert += len(a)
            per_test.append({"file": p.name, "test": t.name, "assertions": len(a),
                             "trivial_only": bool(a) and all(_trivial(x) for x in a)})
        tests += cands
    n = len(per_test)
    no_a = sum(1 for t in per_test if t["assertions"] == 0)
    triv = sum(1 for t in per_test if t["trivial_only"])
    return {"n_test_files": len(paths), "n_tests_static": n, "n_assertions_static": n_assert,
            "tests_no_assertion": no_a, "tests_trivial_assertions_only": triv,
            "no_assertion_rate": share(no_a, n), "trivial_assertion_rate": share(triv, n),
            "weak_assertion_rate": share(no_a + triv, n)}


def definition_share(src_path, executed):
    """Share of functions (incl. methods) with at least one executed body line, and of classes
    with at least one executed line inside one of their methods. Def/class header and decorator
    lines run at import and are not counted; docstrings are not counted. Functions with no
    body statement besides a docstring and classes without methods are left out (counted)."""
    tree = ast.parse(src_path.read_bytes().decode("utf-8-sig"))
    executed = set(executed)

    def body_lines(fn):
        body = fn.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]
        return {n.lineno for b in body for n in ast.walk(b) if isinstance(n, ast.stmt)}

    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    f_lines = {id(f): body_lines(f) for f in funcs}
    f_scored = [f for f in funcs if f_lines[id(f)]]
    f_hit = [f for f in f_scored if f_lines[id(f)] & executed]
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    c_scored, c_hit = [], []
    for c in classes:
        methods = [n for n in ast.walk(c) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        lines = set().union(*(f_lines[id(m)] for m in methods)) if methods else set()
        if lines:
            c_scored.append(c)
            if lines & executed:
                c_hit.append(c)
    return {"functions_total": len(f_scored), "functions_executed": len(f_hit),
            "function_share": share(len(f_hit), len(f_scored)),
            "functions_excluded_empty": len(funcs) - len(f_scored),
            "classes_total": len(c_scored), "classes_executed": len(c_hit),
            "class_share": share(len(c_hit), len(c_scored)),
            "classes_excluded_no_methods": len(classes) - len(c_scored)}


# ---------------------------------------------------------------- scoring helpers
def _parses(path):
    try:
        ast.parse(path.read_bytes().decode("utf-8-sig"))
        return True
    except (SyntaxError, ValueError, UnicodeDecodeError):
        return False


def is_killed(rec):
    return rec["status"] in ("killed", "timeout")


def ratio(num, den):
    return round(num / den, 4) if den else 0.0


def share(num, den):
    """Outcome measures: None (not applicable) when there is nothing to measure."""
    return round(num / den, 4) if den else None


def validity_runs(module, label):
    rng = random.Random(f"{SEED}:validity:{module}:{label}")
    return [{"run": i, "order_seed": rng.randrange(2 ** 32), "hash_seed": rng.randrange(1, 2 ** 32 - 1)}
            for i in range(VALIDITY_RUNS)]


def classify_tests(runs):
    """Union of test ids over runs; a test failing or missing in a run counts as failing it."""
    ids = sorted(set().union(*(r["tests"] for r in runs)))
    fails = {t: sum(1 for r in runs if r["tests"].get(t) not in ("passed", "skipped")) for t in ids}
    wrong = [t for t in ids if fails[t] == len(runs)]
    flaky = [t for t in ids if 0 < fails[t] < len(runs)]
    kept = [t for t in ids if fails[t] == 0]
    return ids, kept, wrong, flaky


def empty_row(run_id, module, sp, n_total):
    row = dict(run_id=run_id, harness_version=HARNESS_VERSION, module=module, test_file=sp["label"],
               suite=sp["suite"], upstream_path=sp["upstream_path"], runner_mode=sp["mode"],
               arm_status="ran", valid=False, valid_file_level=False, flaky_runs_failed=None,
               n_tests=0, tests_kept=0, tests_wrong=0, tests_flaky=0, kept_fraction=0.0,
               wrong_tests=[], flaky_tests=[],
               mutants_total=n_total, mutants_used=0, killed=0, survived=0,
               timeouts=0, apply_errors=0, trivially_killed=0,
               mutation_score=0.0, mutation_score_nontrivial=0.0,
               assertion_kill_rate=0.0, assertion_kill_rate_nontrivial=0.0,
               killed_by_error=0, mutation_by_category={}, coverage=None, **RUN_SCHEMA_NULLS)
    for k in KILL_KINDS:
        row[f"killed_by_{k}"] = 0
    return row


def by_category(recs):
    out = {}
    for r in recs:
        c = out.setdefault(r["category"], {"used": 0, "killed": 0, "used_nontrivial": 0, "killed_nontrivial": 0})
        c["used"] += 1
        c["killed"] += is_killed(r)
        if not r["trivially_killed"]:
            c["used_nontrivial"] += 1
            c["killed_nontrivial"] += is_killed(r)
    for c in out.values():
        c["score"] = ratio(c["killed"], c["used"])
        c["score_nontrivial"] = ratio(c["killed_nontrivial"], c["used_nontrivial"])
    return dict(sorted(out.items()))


UNAVAILABLE = "unavailable"   # B3: a field the writer run did not record (older meta.json); never inferred
WRITER_B3_FIELDS = ("first_iteration_pass", "iterations_used", "run_started_at", "response_model", "request_ids",
                    "usage_full", "peak_input_tokens_per_call", "retry_count", "api_events", "unparsable_files",
                    "unparsable_by_iteration")


def writer_fields(writer):
    """Row fields for a writer suite; the model fields are null on reference suites."""
    return {"model_id": writer["model_id"], "effort": writer["effort"], "prompt_hash": writer["prompt_hash"],
            "tokens_in": writer["tokens_in"], "tokens_out": writer["tokens_out"],
            "estimated_cost": writer["estimated_cost"], "writer_seed": writer["seed"],
            "writer_iterations": writer["iterations"], "writer_stop": writer["stop"],
            "writer_wall_seconds": writer["wall_seconds"], "writer_parse_failures": writer["parse_failures"],
            **{k: writer.get(k, UNAVAILABLE) for k in WRITER_B3_FIELDS}}


def b3_row_fields(tag):
    return {"scorer_revision": SCORER_REVISION, "design_commit": prereg_commit(), "tag": tag}


def logic_constant_fields(selected, used_recs=None):
    """B3 headline split. Constants = number-constant replacements (CONSTANT_OPERATORS); logic = every
    other operator. constants_share is over the module's sampled set; the counts and scores are over
    the mutants used (apply errors excluded) when the suite was scored."""
    const = lambda r: r["operator"] in CONSTANT_OPERATORS
    out = {"constants_share": share(sum(1 for m in selected if const(m)), len(selected))}
    recs = used_recs if used_recs is not None else selected
    lg, cs = [r for r in recs if not const(r)], [r for r in recs if const(r)]
    out.update(logic_mutants_n=len(lg), constant_mutants_n=len(cs),
               score_logic=share(sum(1 for r in lg if is_killed(r)), len(lg)) if used_recs is not None else None,
               score_constants=share(sum(1 for r in cs if is_killed(r)), len(cs)) if used_recs is not None else None)
    return out


WRITER_FAILED_STOPS = {"failed_truncated", "refusal", "api_error", "wall_cap", "extraction_failed"}


def failed_writer_row(writer):
    """B2c: the row for a writer run that failed (WRITER_FAILED_STOPS, or no suite files).
    Not scored: no sandbox run, and every score field is null rather than 0, so a failed run
    cannot be mistaken for a scored suite that killed nothing."""
    sp = {"label": "writer", "suite": "writer", "upstream_path": None, "mode": "pytest"}
    row = empty_row(writer["run_id"], writer["module"], sp, None)
    row.update({k: None for k in ("kept_fraction", "mutation_score", "mutation_score_nontrivial",
                                  "assertion_kill_rate", "assertion_kill_rate_nontrivial", "mutants_used")})
    status = "extraction_failed" if writer.get("stop") == "extraction_failed" else "writer_failed"
    row.update(b3_row_fields(writer["tag"]))
    row.update({k: None for k in ("score_logic", "score_constants")})
    row.update(arm_status=status, tag=writer["tag"], suite_files=[], **writer_fields(writer),
               writer_api_error=writer.get("api_error"), writer_stop_reasons=writer.get("stop_reasons"),
               **({"writer_stop_original": writer["writer_stop_original"]} if "writer_stop_original" in writer else {}),
               timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return row


def evaluate_module(module, ident, ctx, run_id, cap, mutmut, writer=None, tag=None):
    t_module = time.monotonic()
    meta = module_meta(module)
    src = meta["module_path"]
    if sha256(src.read_bytes()) != meta["module_sha256"]:
        raise InfraError(f"{module}: {src.name} sha256 does not match {CORPUS_FINAL.name}")
    specs = suite_specs(module, writer)
    null_src, null_statuses = None, None   # stored null row reused for this run (writer mode)
    rows, mm_rows = [], []
    trivial = None  # set of (operator, occurrence) killed by the null suite

    def budget():
        remaining = MODULE_BUDGET_S - (time.monotonic() - t_module)
        if remaining <= 0:
            raise InfraError(f"{module}: exceeded {MODULE_BUDGET_S}s budget")
        return remaining

    with Sandbox(module, scoring=True) as sb:
        files = {f"src/{module}.py": src}
        files.update({f"harness/{h}": SANDBOX / h for h in HARNESS_FILES})
        for sp in specs:
            if not sp["not_runnable"]:
                for p in sp["paths"]:
                    files[f"tests/{sp['suite']}/{sp.get('dest', {}).get(p.name, p.name)}"] = p
                if sp.get("aliases"):
                    files[f"harness/aliases_{sp['suite']}.json"] = json.dumps(sp["aliases"]).encode()
        sb.put(files)

        all_mutants = json.loads(sb.exec("python", "/work/harness/runner.py", "enumerate", module))
        selected, alloc = select_mutants(all_mutants, SEED, cap)
        mut_blob = json.dumps(selected).encode()
        sb.put({"ctl/mutants.json": mut_blob})
        sampling = {"strategy": "stratified_by_operator_category", "seed": SEED, "cap": cap,
                    "allocation": alloc, "mutant_set_sha256": sha256(mut_blob)}
        if cap == MAX_MUTANTS and sampling["mutant_set_sha256"] != meta["mutant_set_sha256"]:
            raise InfraError(f"{module}: mutant set {sampling['mutant_set_sha256'][:12]} differs from the fixed "
                             f"set {meta['mutant_set_sha256'][:12]} in {CORPUS_FINAL.name}")
        key = null_key(module, ident, sampling["mutant_set_sha256"])
        if writer:
            null_src = stored_null(key)
        if null_src:
            specs = [sp for sp in specs if sp["label"] != NULL_LABEL]
            trivial = {(op, occ) for op, occ, st in null_src["mutant_statuses"] if st in ("killed", "timeout")}

        for sp in specs:
            t0 = time.monotonic()
            row = empty_row(run_id, module, sp, len(all_mutants))
            row.update(b3_row_fields(writer["tag"] if writer else tag))
            row.update(logic_constant_fields(selected))
            if sp.get("aliases"):
                row["upstream_aliases"] = sp["aliases"]
            gaming = None
            if sp["suite"] == "writer":
                if not sp["paths"]:
                    raise InfraError(f"{module}: writer suite {writer['suite_dir']} is empty")
                row.update(writer_fields(writer))
                gaming = static_checks.gaming_flags(sp["paths"], module)    # B3: writer suites only
                row.update(gaming_flag=gaming["n_flagged"], gaming_flag_counts=gaming["counts"],
                           gaming_flags=gaming["flagged"],
                           style_profile=static_checks.style_profile(sp["paths"], src))
            row.update(static_test_measures(sp["paths"]))
            row["suite_files"] = [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha256(p.read_bytes())}
                                  for p in sp["paths"]]
            per_mutant_timeout, base, vruns = None, [], []
            if sp["not_runnable"]:
                row["arm_status"] = sp["not_runnable"]
            else:
                runs = validity_runs(module, sp["label"])
                sb.put({f"ctl/vruns_{sp['suite']}.json": json.dumps(runs).encode()})
                vruns = json.loads(sb.exec("python", "/work/harness/runner.py", "validity", module,
                                           sp["suite"], sp["mode"], f"/work/ctl/vruns_{sp['suite']}.json",
                                           timeout=budget()))
                ids, kept, wrong, flaky = classify_tests(vruns)
                gaming_ids = static_checks.flagged_nodeids(gaming, ids) if gaming else []
                if gaming is not None:
                    kept = [t for t in kept if t not in gaming_ids]   # flagged tests are invalid: dropped
                    row.update(tests_gaming=len(gaming_ids), gaming_dropped_tests=gaming_ids)
                row.update(n_tests=len(ids), tests_kept=len(kept), tests_wrong=len(wrong),
                           tests_flaky=len(flaky), kept_fraction=ratio(len(kept), len(ids)),
                           wrong_tests=wrong, flaky_tests=flaky,
                           valid_file_level=all(r["exit_code"] == 0 and not r["timed_out"]
                                                and not r["collection_errors"] for r in vruns),
                           validity_collection_errors=sorted({e for r in vruns for e in r["collection_errors"]}))
                if wrong or flaky or gaming_ids:
                    drop = wrong + flaky + [t for t in gaming_ids if t not in wrong and t not in flaky]
                    sb.put({f"harness/deselect_{sp['suite']}.json": json.dumps(drop).encode()})
                if kept:
                    base = json.loads(sb.exec("python", "/work/harness/runner.py", "baseline", module,
                                              sp["suite"], sp["mode"], str(BASELINE_RUNS), timeout=budget()))
                    failed = sum(1 for b in base if b["exit_code"] != 0)
                    row.update(valid=failed == 0, flaky_runs_failed=failed)
                    if failed:
                        row["baseline_error"] = next(b["tail"] for b in base if b["exit_code"] != 0)[-200:]
                else:
                    row["baseline_error"] = "no test passed every validity run"
            if row["valid"]:
                cov = json.loads(sb.exec("python", "/work/harness/runner.py", "coverage", module,
                                         sp["suite"], sp["mode"], timeout=budget()))
                if "error" in cov:
                    raise InfraError(f"{module}/{sp['label']}: {cov}")
                s = cov["summary"]
                row["coverage"] = {"line_coverage": share(s["covered_lines"], s["num_statements"]),
                                   "branch_coverage": share(s["covered_branches"], s["num_branches"]),
                                   "covered_lines": s["covered_lines"], "num_statements": s["num_statements"],
                                   "covered_branches": s["covered_branches"], "num_branches": s["num_branches"],
                                   **definition_share(src, cov["executed_lines"])}
                per_mutant_timeout = round(max(5.0, 10 * max(b["seconds"] for b in base)), 2)
                out = sb.exec("python", "/work/harness/runner.py", "mutants", module, sp["suite"],
                              sp["mode"], "/work/ctl/mutants.json", str(per_mutant_timeout),
                              timeout=budget())
                recs = [json.loads(line) for line in out.splitlines() if line.strip()]
                if len(recs) != len(selected):
                    raise InfraError(f"{module}/{sp['label']}: got {len(recs)} results for "
                                     f"{len(selected)} mutants (container alive={sb.alive()})")
                for r, m in zip(recs, selected):
                    r["category"] = m["category"]
                if sp["label"] == NULL_LABEL:
                    trivial = {(r["operator"], r["occurrence"]) for r in recs if is_killed(r)}
                    null_statuses = [[r["operator"], r["occurrence"], r["status"]] for r in recs]
                if trivial is None:
                    raise InfraError(f"{module}: null suite must run (and be valid) first")
                for r in recs:
                    r["trivially_killed"] = (r["operator"], r["occurrence"]) in trivial
                with DETAILS.open("a") as f:
                    for r in recs:
                        f.write(json.dumps({"run_id": run_id, "harness_version": HARNESS_VERSION,
                                            "module": module, "test_file": sp["label"], **r}) + "\n")
                used_recs = [r for r in recs if r["status"] != "apply_error"]
                used = len(used_recs)
                killed = sum(1 for r in used_recs if is_killed(r))
                kinds = {k: sum(1 for r in used_recs if r.get("kill_kind") == k) for k in KILL_KINDS}
                n_timeout = sum(1 for r in used_recs if r["status"] == "timeout")
                if killed != sum(kinds.values()) + n_timeout:
                    raise InfraError(f"{module}/{sp['label']}: kill-cause counts do not add up")
                n_triv = sum(1 for r in used_recs if r["trivially_killed"])
                killed_nt = sum(1 for r in used_recs if is_killed(r) and not r["trivially_killed"])
                row.update(mutants_used=used, killed=killed,
                           survived=sum(1 for r in used_recs if r["status"] == "survived"),
                           timeouts=n_timeout, apply_errors=len(recs) - used,
                           trivially_killed=n_triv,
                           mutation_score=ratio(killed, used),
                           mutation_score_nontrivial=ratio(killed_nt, used - n_triv),
                           assertion_kill_rate=ratio(kinds["assertion"], used),
                           assertion_kill_rate_nontrivial=ratio(kinds["assertion"], used - n_triv),
                           killed_by_error=kinds["test_exception"] + kinds["collection_error"] + kinds["crash"],
                           mutation_by_category=by_category(used_recs),
                           **logic_constant_fields(selected, used_recs),
                           **{f"killed_by_{k}": v for k, v in kinds.items()})
            elif sp["label"] == NULL_LABEL:
                raise InfraError(f"{module}: null suite invalid on original code")
            row.update(wall_seconds=round(time.monotonic() - t0, 2), tool="cosmic-ray",
                       tool_version=ctx["cosmic_ray"], sandbox_python=ctx["python"], **ident,
                       seed=SEED, mutant_sampling=sampling, per_mutant_timeout_s=per_mutant_timeout,
                       baseline_seconds=[b["seconds"] for b in base],
                       validity_runs=[{k: r[k] for k in ("run", "order_seed", "hash_seed", "exit_code",
                                                         "timed_out", "seconds")} for r in vruns],
                       timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            if sp["suite"] == "writer":
                row["null_source"] = ({"reused": True, "run_id": null_src["row"]["run_id"], "key": key} if null_src
                                      else {"reused": False, "run_id": run_id, "key": key})
            if sp["label"] == NULL_LABEL and row["valid"] and stored_null(key) is None:
                with NULL_STORE.open("a") as f:
                    f.write(json.dumps({"key": key, "row": row, "mutant_statuses": null_statuses}) + "\n")
            rows.append(row)
            with RESULTS.open("a") as f:
                f.write(json.dumps(row) + "\n")
        module_wall = time.monotonic() - t_module

        if mutmut:
            for sp, row in zip(specs, rows):
                if not row["valid"]:
                    continue
                t0 = time.monotonic()
                res = json.loads(sb.exec("python", "/work/harness/runner.py", "mutmut", module,
                                         sp["suite"], sp["mode"], timeout=MODULE_BUDGET_S))
                if "error" in res:
                    raise InfraError(f"{module}/{sp['label']} mutmut: {res}")
                c = res["counts"]
                k = c.get("killed", 0) + c.get("timeout", 0)
                den = k + c.get("survived", 0) + c.get("suspicious", 0)
                mm = {"run_id": run_id, "harness_version": HARNESS_VERSION, "module": module,
                      "test_file": sp["label"], "tool": "mutmut", "tool_version": ctx["mutmut"],
                      "counts": c, "mutants": len(res["mutants"]), "mutation_score": ratio(k, den),
                      "statuses": res["mutants"], "exit_code": res["exit_code"],
                      "wall_seconds": round(time.monotonic() - t0, 2), "env_id": ident["env_id"],
                      "deselected_tests": row["wrong_tests"] + row["flaky_tests"],
                      "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                mm_rows.append(mm)
                with MUTMUT_RESULTS.open("a") as f:
                    f.write(json.dumps(mm) + "\n")
    return rows, mm_rows, module_wall


# ---------------------------------------------------------------- repeatability
def _load(path):
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


def previous_run_id(run_id, module=None):
    """Latest earlier run with this harness_version (that scored `module`, if given); tagged (e.g.
    dry_run) runs never serve as the baseline. B3: per module, so a reference run over modules that
    were never run before is not compared with an unrelated run."""
    ids = []
    for r in _load(RESULTS):
        if (r.get("harness_version") == HARNESS_VERSION and r["run_id"] != run_id and r["run_id"] not in ids
                and not r.get("tag") and (module is None or r["module"] == module)):
            ids.append(r["run_id"])
    return ids[-1] if ids else None


def null_store_env_check(ident):
    """B3: stored null rows whose env_id is not the current one. They are never reused (the key holds
    env_id), so their modules would be re-scored; listed so the mismatch is visible."""
    return [{"module": r["key"]["module"], "run_id": r["row"]["run_id"], "env_id": r["key"]["env_id"]}
            for r in _load(NULL_STORE) if r["key"]["env_id"] != ident["env_id"]
            or r["row"].get("env_id", ident["env_id"]) != ident["env_id"]]


REPEAT_FIELDS = ("valid", "n_tests_static", "n_assertions_static", "weak_assertion_rate", "valid_file_level", "n_tests", "tests_kept", "wrong_tests", "flaky_tests",
                 "mutants_used", "killed", "survived", "timeouts", "mutation_score",
                 "mutation_score_nontrivial", "mutation_by_category", "coverage",
                 "killed_by_assertion", "killed_by_test_exception", "killed_by_collection_error",
                 "killed_by_crash", "mutant_sampling")


def compare_runs(prev, cur, modules=None, skip_labels=()):
    """Every suite present in both runs: listed fields, every per-mutant status/kill kind,
    and mutmut per-mutant statuses where both runs have them. A writer scoring run passes
    `modules` (its one module) and skips its writer suite, so only the reference suites it
    re-ran are compared."""
    rows, det, mm = _load(RESULTS), _load(DETAILS), _load(MUTMUT_RESULTS)
    lines, diffs = [], 0
    keyed = lambda rid: {(r["module"], r["test_file"]): r for r in rows if r["run_id"] == rid
                         and (modules is None or r["module"] in modules) and r["test_file"] not in skip_labels}
    a_rows, b_rows = keyed(prev), keyed(cur)
    for key in sorted(set(a_rows) | set(b_rows)):
        a, b = a_rows.get(key), b_rows.get(key)
        if a is None or b is None:
            lines.append(f"  {key[0]}/{key[1]}: only in {'current' if a is None else 'previous'} run")
            diffs += 1
            continue
        bad = [f"{k}: {a.get(k)} -> {b.get(k)}" for k in REPEAT_FIELDS if a.get(k) != b.get(k)]
        pick = lambda rid: {(d["operator"], d["occurrence"]): (d["status"], d.get("kill_kind")) for d in det
                            if d["run_id"] == rid and (d["module"], d["test_file"]) == key}
        ma, mb = pick(prev), pick(cur)
        flips = [f"{k[0]}#{k[1]}: {ma.get(k)} -> {mb.get(k)}" for k in sorted(set(ma) | set(mb))
                 if ma.get(k) != mb.get(k)]
        mma = next((r for r in mm if r["run_id"] == prev and (r["module"], r["test_file"]) == key), None)
        mmb = next((r for r in mm if r["run_id"] == cur and (r["module"], r["test_file"]) == key), None)
        mm_note = ""
        if mma and mmb:
            if mma["statuses"] != mmb["statuses"]:
                flips.append("mutmut per-mutant statuses differ")
            mm_note = ", mutmut statuses"
        diffs += len(bad) + len(flips)
        lines.append(f"  {key[0]}/{key[1]}: " + (f"exact match (fields, {len(ma)} per-mutant statuses{mm_note})"
                                                 if not (bad or flips) else "; ".join((bad + flips)[:8])))
    return diffs, lines


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-mutants", type=int, default=MAX_MUTANTS, help="cap per module (default 100)")
    ap.add_argument("--modules", default=",".join(MODULES))
    ap.add_argument("--mutmut", default="", help="comma-separated modules for the mutmut cross-check")
    ap.add_argument("--writer-meta", help="score a writer.py run (its meta.json) together with the module's "
                                          "reference suites; rows carry that run's run_id and tag")
    ap.add_argument("--tag", help=f"reference mode only: tag the rows ({sorted(REFERENCE_TAGS)}); "
                                  f"tag full needs the {PREREG_TAG} tag to exist")
    a = ap.parse_args()
    if a.tag and (a.writer_meta or a.tag not in REFERENCE_TAGS):
        raise SystemExit(f"--tag is for reference mode only, one of {sorted(REFERENCE_TAGS)}")
    if (a.tag == "full" or (a.writer_meta and json.loads(Path(a.writer_meta).read_text()).get("tag") == "full")) \
            and not prereg_commit():
        raise SystemExit(f"tag full needs the {PREREG_TAG} git tag (design_commit)")
    modules = [m for m in a.modules.split(",") if m]
    mutmut_mods = {m for m in a.mutmut.split(",") if m}
    writer = json.loads(Path(a.writer_meta).read_text()) if a.writer_meta else None
    if writer:
        modules, mutmut_mods = [writer["module"]], set()
        if any(r["run_id"] == writer["run_id"] for r in _load(RESULTS)):
            raise SystemExit(f"run_id {writer['run_id']} already in {RESULTS.name}")
        bad = [p.name for p in sorted((ROOT / writer["suite_dir"]).glob("*.py"))
               if not _parses(p)] if writer.get("suite_files") else []
        if bad and writer.get("stop") not in WRITER_FAILED_STOPS:   # B3: also checked here, for older metas
            writer = {**writer, "stop": "extraction_failed", "writer_stop_original": writer.get("stop"),
                      "unparsable_files": bad}
        if writer.get("stop") in WRITER_FAILED_STOPS or not writer.get("suite_files"):
            row = failed_writer_row(writer)   # B2c: recorded, never scored, never dropped
            with RESULTS.open("a") as f:
                f.write(json.dumps(row) + "\n")
            print(f"{writer['run_id']}: writer run failed (stop={writer['stop']}, "
                  f"{len(writer.get('suite_files') or [])} suite files): failed row recorded, not scored")
            return 1

    sh(["docker", "info", "--format", "{{.ServerVersion}}"])
    ident = build_and_verify_image()
    probe = json.loads(sh(["docker", "run", "--rm", "--network", "none", IMAGE, "python", "-c",
                           "import importlib.metadata as m, json, sys; print(json.dumps({'cosmic_ray': "
                           "m.version('cosmic-ray'), 'mutmut': m.version('mutmut'), "
                           "'python': sys.version.split()[0]}))"]))
    run_id = writer["run_id"] if writer else datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    all_rows, all_mm, module_wall, problems = [], [], {}, []
    try:
        for module in modules:
            rows, mm, wall = evaluate_module(module, ident, probe, run_id, a.max_mutants, module in mutmut_mods,
                                             writer, a.tag)
            all_rows += rows
            all_mm += mm
            module_wall[module] = wall
            if wall > MODULE_BUDGET_S:
                problems.append(f"{module} took {wall:.0f}s > {MODULE_BUDGET_S}s")
            mm_wall = sum(r["wall_seconds"] for r in mm)
            if mm_wall > MODULE_BUDGET_S:
                problems.append(f"{module} mutmut took {mm_wall:.0f}s > {MODULE_BUDGET_S}s")
    except (InfraError, subprocess.TimeoutExpired) as e:
        problems.append(f"infrastructure: {e}")

    print(f"\nrun_id={run_id} harness={HARNESS_VERSION} env_id={ident['env_id'][:16]} "
          f"cosmic-ray={probe['cosmic_ray']} mutmut={probe['mutmut']} python={probe['python']} "
          f"seed={SEED} cap={a.max_mutants}")
    print(f"  env_id_inputs={json.dumps(ident['env_id_inputs'])}")
    hdr = ["module", "suite", "valid", "file_ok", "tests", "kept", "wrong", "flaky", "used", "killed",
           "score", "score_nt", "assert_rt", "line", "branch", "weak_a", "wall_s"]
    fmt = "{:<10} {:<15} {:<5} {:<7} {:>5} {:>4} {:>5} {:>5} {:>4} {:>6} {:>6} {:>8} {:>9} {:>5} {:>6} {:>6} {:>6}"
    print(fmt.format(*hdr))
    for r in all_rows:
        if r["arm_status"] != "ran":
            print(f"{r['module']:<10} {r['test_file']:<15} -- {r['arm_status']}")
            continue
        cv = r["coverage"] or {}
        print(fmt.format(r["module"], r["test_file"], str(r["valid"]), str(r["valid_file_level"]),
                         r["n_tests"], r["tests_kept"], r["tests_wrong"], r["tests_flaky"],
                         r["mutants_used"], r["killed"], f'{r["mutation_score"]:.3f}',
                         f'{r["mutation_score_nontrivial"]:.3f}', f'{r["assertion_kill_rate"]:.3f}',
                         f'{cv.get("line_coverage", 0):.2f}', f'{cv.get("branch_coverage", 0):.2f}',
                         f'{r["weak_assertion_rate"] or 0:.2f}', f'{r["wall_seconds"]:.1f}'))
    print("\nwall time per module (excl. mutmut): " + ", ".join(f"{m}={w:.1f}s" for m, w in module_wall.items()))
    for r in all_mm:
        print(f"mutmut {r['module']:<10} {r['test_file']:<15} n={r['mutants']:>4} score={r['mutation_score']:.3f} "
              f"{r['counts']} {r['wall_seconds']:.0f}s")

    by = {(r["module"], r["test_file"]): r for r in all_rows}
    for m in ([] if writer else modules):
        s, w = by.get((m, "strong_test.py")), by.get((m, "weak_test.py"))
        if not (s and w):
            if (ROOT / "tests" / m / "strong_test.py").exists():
                problems.append(f"{m}: missing control rows")
            continue
        if not (s["valid"] and w["valid"]):
            problems.append(f"{m}: invalid control suite(s)")
        if not s["mutation_score"] > w["mutation_score"]:
            problems.append(f"{m}: strong {s['mutation_score']} not > weak {w['mutation_score']}")
        if any(r["apply_errors"] for r in all_rows if r["module"] == m):
            problems.append(f"{m}: mutant apply errors")

    stale = null_store_env_check(ident)
    if stale:
        print(f"\nstored null rows with another env_id (not reused; flagged for rescoring): {stale}")
    if writer:
        print("\nrepeatability: writer run (reference suites are not re-run; null reused or stored)")
    else:
        groups = {}
        for m in modules:
            groups.setdefault(previous_run_id(run_id, m), []).append(m)
        for prev, mods in groups.items():
            if prev is None:
                print(f"\nrepeatability: no previous {HARNESS_VERSION} run of {', '.join(mods)} to compare with")
                continue
            diffs, lines = compare_runs(prev, run_id, set(mods))
            print(f"\nrepeatability vs {prev} ({', '.join(mods)}): "
                  f"{'EXACT MATCH' if diffs == 0 else f'{diffs} difference(s)'}")
            print("\n".join(lines))
            if diffs:
                problems.append(f"repeatability vs {prev}: {diffs} difference(s)")

    print("\nGO" if not problems else "\nNO-GO:\n  " + "\n  ".join(problems))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
