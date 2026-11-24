#!/usr/bin/env python3
"""Stage B2a: build the corpus from candidates_frozen.json and smoke-check it.

  fetch   download each primary/baseline candidate's module (and direct upstream test and
          licence file) at its pinned SHA, check sha256s, parse with ast on the host (never
          import or execute), store under corpus/<name>/ with meta.json.
  smoke [names]  per module (named modules are rerun; the latest record wins), offline sandbox only: import check (flat, as the scorer imports
          it); the direct upstream test, laid out at its repo path; then the null suite
          through run_eval.evaluate_module (validity, baselines, coverage, seeded stratified
          cosmic-ray sample, cap 100) to get the mutant set and the scoring wall time.
          Rows go to smoke_null.jsonl / smoke_null_mutants.jsonl, not results.jsonl.
  final   write corpus_final.json (primary, baseline, exclusions) and the pilot draw.

Downloaded code is untrusted: on the host it is only read as bytes/text and parsed with
ast. Upstream tests are stored as upstream_test.txt so host-side pytest never collects them.
Usage: python3 corpus_build.py fetch|smoke|final
"""
import ast
import hashlib
import json
import random
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import run_eval

ROOT = Path(__file__).resolve().parent
FROZEN = ROOT / "candidates_frozen.json"
CORPUS = ROOT / "corpus"
SMOKE = ROOT / "smoke_results.jsonl"
NULL_ROWS = ROOT / "smoke_null.jsonl"
NULL_DETAILS = ROOT / "smoke_null_mutants.jsonl"
FINAL = ROOT / "corpus_final.json"
PILOT_SEED = 20261118
PILOT_N = 10
MIN_MUTANTS = 20
IMPORT_TIMEOUT_S = 60
UPSTREAM_TIMEOUT_S = 300
UA = "agent-test-eval-corpus-fetch"


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def candidates():
    d = json.loads(FROZEN.read_text())
    return [c for c in d["candidates"] if c["primary_set"] or c["baseline_set"]]


def corpus_name(c, taken):
    """Stage 0 modules keep their names. Others: <repo>_<stem>, a valid identifier that
    cannot shadow the stdlib or a sandbox package (e.g. SKIjack's ast.py)."""
    if c.get("stage0_name"):
        return c["stage0_name"]
    repo = c["repo_url"].rstrip("/").split("/")[-1]
    stem = Path(c["path"]).stem
    slug = lambda s: re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", s.lower())).strip("_")
    name = f"{slug(repo)[:24].strip('_')}_{slug(stem)}"
    if name[0].isdigit():
        name = "m_" + name
    base, i = name, 2
    while name in taken or name in sys.stdlib_module_names:
        name, i = f"{base}_{i}", i + 1
    return name


def raw_url(c, path):
    owner_repo = c["repo_url"].split("github.com/", 1)[1].rstrip("/")
    return f"https://raw.githubusercontent.com/{owner_repo}/{c['pinned_sha']}/{path}"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def safe_rel(p):
    if p.startswith("/") or ".." in Path(p).parts:
        raise ValueError(f"unsafe path {p!r}")
    return p


# ---------------------------------------------------------------- fetch
def cmd_fetch():
    taken = {p.name for p in CORPUS.iterdir() if p.is_dir()}
    out = []
    for c in candidates():
        name = corpus_name(c, taken - ({c["stage0_name"]} if c.get("stage0_name") else set()))
        taken.add(name)
        d = CORPUS / name
        rec = {"name": name, "id": c["id"], "set": "primary" if c["primary_set"] else "baseline",
               "repo_url": c["repo_url"], "pinned_sha": c["pinned_sha"], "path": c["path"],
               "licence": c["licence"], "licence_file": c["licence_file"], "lines": c["lines"],
               "first_commit_date": c["first_commit_date"], "last_change_date": c["last_change_date"],
               "upstream_test_kind": c["upstream_test_kind"], "upstream_test": c["upstream_test"],
               "flags": {k: c[k] for k in ("ai_trace", "possible_copy", "baseline_human_certain")},
               "windows": c["windows"], "module_sha256": c["module_sha256"],
               "stage0": bool(c.get("stage0_name")), "fetch_error": None,
               "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        try:
            if c.get("stage0_name"):
                data = (d / f"{name}.py").read_bytes()   # stored at Stage 0; matches the pin (A1c)
                rec["source_url"] = "corpus (Stage 0); module_matches_corpus_at_pin=" + str(c["module_matches_corpus_at_pin"])
            else:
                rec["source_url"] = raw_url(c, safe_rel(c["path"]))
                data = get(rec["source_url"])
            if sha256(data) != c["module_sha256"]:
                raise ValueError(f"module sha256 {sha256(data)[:12]} != frozen {c['module_sha256'][:12]}")
            ast.parse(data.decode("utf-8"), filename=c["path"])   # host-side read only
            if not c.get("stage0_name"):
                d.mkdir(exist_ok=True)
                (d / f"{name}.py").write_bytes(data)
                try:
                    (d / "LICENSE").write_bytes(get(raw_url(c, safe_rel(c["licence_file"]))))
                except Exception as e:   # licence text is for attribution; its family was checked at A1b
                    rec["licence_fetch_error"] = str(e)[:200]
                if c["upstream_test_kind"] == "direct":
                    t = get(raw_url(c, safe_rel(c["upstream_test"])))
                    rec["upstream_test_sha256"] = sha256(t)
                    if c.get("upstream_test_sha256") and sha256(t) != c["upstream_test_sha256"]:
                        rec["upstream_test_sha_mismatch"] = True
                    (d / "upstream_test.txt").write_bytes(t)
            rec["module_file"] = f"corpus/{name}/{name}.py"
        except Exception as e:
            rec["fetch_error"] = f"{type(e).__name__}: {str(e)[:300]}"
        if d.exists() and not c.get("stage0_name"):
            (d / "meta.json").write_text(json.dumps(rec, indent=2) + "\n")
        out.append(rec)
        print(f"{name:<44} {'FETCH ERROR ' + rec['fetch_error'] if rec['fetch_error'] else 'ok'}")
    (ROOT / "corpus_fetch.json").write_text(json.dumps(out, indent=2) + "\n")


# ---------------------------------------------------------------- smoke (sandbox only)
ENV = ["env", "-i", "PATH=/usr/local/bin:/usr/bin:/bin", "HOME=/tmp", "PYTHONDONTWRITEBYTECODE=1",
       "PYTHONHASHSEED=0", "LANG=C.UTF-8"]


def dexec(sb, args, timeout, cwd="/work"):
    try:
        r = subprocess.run(["docker", "exec", "-w", cwd, sb.name, *args], capture_output=True, text=True,
                           timeout=timeout + 30)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "host_timeout", ""


def reason_of(output):
    for pat in (r"(ModuleNotFoundError: No module named '[^']+')", r"(ImportError: [^\n]+)",
                r"(SyntaxError: [^\n]+)", r"(fixture '[^']+' not found)", r"^E\s+(\w+(?:Error|Exception)[^\n]*)",
                r"^(\w+(?:Error|Exception): [^\n]+)"):
        m = re.search(pat, output, re.M)
        if m:
            return m.group(1)[:200]
    return None


def summary_line(output):
    lines = [l for l in output.strip().splitlines() if re.search(r"\b(passed|failed|error|errors|no tests ran)\b", l)]
    return lines[-1].strip("= ")[:200] if lines else None


def smoke_one(rec):
    name, m = rec["name"], CORPUS / rec["name"] / f"{rec['name']}.py"
    res = {"name": name, "import_ok": False, "import_error": None, "upstream": None}
    with run_eval.Sandbox(name) as sb:
        files = {f"src/{name}.py": m}
        test = CORPUS / name / "upstream_test.txt"
        if test.exists():
            files[f"repo/{safe_rel(rec['path'])}"] = m
            files[f"repo/{safe_rel(rec['upstream_test'])}"] = test
        sb.put(files)
        code, out = dexec(sb, [*ENV, "PYTHONPATH=/work/src", "timeout", "-s", "KILL", str(IMPORT_TIMEOUT_S),
                               "python", "-c", f"import {name}"], IMPORT_TIMEOUT_S)
        res["import_ok"] = code == 0
        if code != 0:
            res["import_error"] = (reason_of(out) or f"exit {code}: {out.strip()[-200:]}")
        if test.exists():
            parts = Path(rec["path"]).parent.parts
            # The module's own directory is left off when its file name is a stdlib name
            # (SKIjack's ast.py would shadow the stdlib ast that pytest itself imports).
            top = len(parts) if Path(rec["path"]).stem in sys.stdlib_module_names else len(parts) + 1
            roots = ["/work/repo"] + ["/work/repo/" + "/".join(parts[:i]) for i in range(1, top)]
            tparts = Path(rec["upstream_test"]).parent.parts
            roots += ["/work/repo/" + "/".join(tparts[:i]) for i in range(1, len(tparts) + 1)]
            pp = ":".join(dict.fromkeys(roots))
            code, out = dexec(sb, [*ENV, f"PYTHONPATH={pp}", "timeout", "-s", "KILL", str(UPSTREAM_TIMEOUT_S),
                                   "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE",
                                   rec["upstream_test"]], UPSTREAM_TIMEOUT_S, cwd="/work/repo")
            res["upstream"] = {"exit_code": code, "passed": code == 0, "summary": summary_line(out),
                               "reason": None if code == 0 else (reason_of(out) or f"exit {code}"),
                               "note": "module + test file only, at their repo paths; other repo files absent"}
    return res


def stage0_upstream(name):
    """Stage 0 upstream status from the latest untagged A2.1 run (their runners differ: script mode)."""
    rows = [json.loads(l) for l in run_eval.RESULTS.read_text().splitlines()]
    rows = [r for r in rows if r.get("harness_version") == "A2.1" and not r.get("tag")
            and r["module"] == name and r["test_file"] == "upstream"]
    if not rows:
        return None
    r = rows[-1]
    return {"exit_code": None, "passed": bool(r["valid"]), "summary": f"A2.1 run {r['run_id']}: arm_status={r['arm_status']}",
            "reason": None if r["valid"] else r["arm_status"], "note": "from results.jsonl (Stage 0 harness)"}


def null_timing(name, ident, probe):
    null = ROOT / "tests" / name / "null_test.py"
    if not null.exists():
        null.parent.mkdir(parents=True, exist_ok=True)
        null.write_text(f"import {name}  # noqa: F401\n\n\ndef test_import_only():\n    pass\n")
    spec = [{"label": run_eval.NULL_LABEL, "suite": "null", "paths": [null], "mode": "pytest",
             "upstream_path": None, "not_runnable": None}]
    orig = (run_eval.suite_specs, run_eval.RESULTS, run_eval.DETAILS)
    run_eval.suite_specs, run_eval.RESULTS, run_eval.DETAILS = (lambda m, w=None: spec), NULL_ROWS, NULL_DETAILS
    try:
        run_id = "B2a-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        t0 = time.monotonic()
        rows, _, wall = run_eval.evaluate_module(name, ident, probe, run_id, run_eval.MAX_MUTANTS, False)
        return rows[0], round(time.monotonic() - t0, 2)
    finally:
        run_eval.suite_specs, run_eval.RESULTS, run_eval.DETAILS = orig


def cmd_smoke(only=None):
    fetched = json.loads((ROOT / "corpus_fetch.json").read_text())
    done = {json.loads(l)["name"] for l in SMOKE.read_text().splitlines()} if SMOKE.exists() else set()
    ident = run_eval.build_and_verify_image()
    probe = json.loads(run_eval.sh(["docker", "run", "--rm", "--network", "none", run_eval.IMAGE, "python", "-c",
                                    "import importlib.metadata as m, json, sys; print(json.dumps({'cosmic_ray': "
                                    "m.version('cosmic-ray'), 'mutmut': m.version('mutmut'), "
                                    "'python': sys.version.split()[0]}))"]))
    for rec in fetched:
        if rec["fetch_error"] or (only and rec["name"] not in only) or (not only and rec["name"] in done):
            continue
        t0 = time.monotonic()
        res = smoke_one(rec)
        if rec["stage0"]:
            res["upstream"] = stage0_upstream(rec["name"])
        if res["import_ok"]:
            try:
                row, wall = null_timing(rec["name"], ident, probe)
                res.update(null_valid=row["valid"], null_wall_seconds=wall, mutants_total=row["mutants_total"],
                           mutants_used=row["mutants_used"], mutant_sampling=row["mutant_sampling"],
                           null_trivially_killed=row["killed"], per_mutant_timeout_s=row["per_mutant_timeout_s"])
            except (run_eval.InfraError, subprocess.TimeoutExpired) as e:
                res["null_error"] = str(e)[:300]
        res["smoke_wall_seconds"] = round(time.monotonic() - t0, 2)
        res["python"] = probe["python"]
        with SMOKE.open("a") as f:
            f.write(json.dumps(res) + "\n")
        up = res["upstream"]
        print(f"{rec['name']:<44} import={'ok' if res['import_ok'] else 'FAIL'} "
              f"upstream={'-' if not up else ('pass' if up['passed'] else 'fail')} "
              f"mutants={res.get('mutants_used', '-')}/{res.get('mutants_total', '-')} "
              f"null={res.get('null_wall_seconds', '-')}s total={res['smoke_wall_seconds']:.0f}s"
              + (f" ERR {res.get('import_error') or res.get('null_error')}" if not res['import_ok'] or res.get('null_error') else ""),
              flush=True)
        if res["smoke_wall_seconds"] > 20 * 60:
            print(f"STOP: {rec['name']} took over 20 minutes")
            return 1
    return 0


# ---------------------------------------------------------------- final
def cmd_final():
    fetched = {r["name"]: r for r in json.loads((ROOT / "corpus_fetch.json").read_text())}
    smoke = {json.loads(l)["name"]: json.loads(l) for l in SMOKE.read_text().splitlines()}
    lists, exclusions, by_rule = {"primary": [], "baseline": []}, [], []
    for name, rec in fetched.items():
        s = smoke.get(name)
        reason = (rec["fetch_error"] and f"fetch: {rec['fetch_error']}") or (not s and "not smoke-checked") \
            or (not s["import_ok"] and f"does not import: {s['import_error']}") \
            or (s.get("null_error") and f"null suite: {s['null_error']}") or None
        if reason:
            exclusions.append({"name": name, "id": rec["id"], "set": rec["set"], "reason": reason})
            continue
        cats = {c: v["sampled"] for c, v in s["mutant_sampling"]["allocation"].items()}
        lists[rec["set"]].append({
            "name": name, "id": rec["id"], "repo_url": rec["repo_url"], "pinned_sha": rec["pinned_sha"],
            "path": rec["path"], "module_file": rec["module_file"], "module_sha256": rec["module_sha256"],
            "licence": rec["licence"], "lines": rec["lines"], "first_commit_date": rec["first_commit_date"],
            "last_change_date": rec["last_change_date"], "flags": rec["flags"], "stage0": rec["stage0"],
            "upstream_test_kind": rec["upstream_test_kind"], "upstream_test": rec["upstream_test"],
            "upstream_smoke": s["upstream"], "mutants_total": s["mutants_total"], "mutants_used": s["mutants_used"],
            "mutants_by_category": cats, "mutant_set_sha256": s["mutant_sampling"]["mutant_set_sha256"],
            "few_mutants": s["mutants_used"] < MIN_MUTANTS, "null_wall_seconds": s["null_wall_seconds"]})
    # B2a draw, reproduced: over every primary module that passed the smoke check.
    b2a_draw = sorted(random.Random(PILOT_SEED).sample(sorted(m["name"] for m in lists["primary"]), PILOT_N))
    # B2b corpus rule (written before any pilot result): at least MIN_MUTANTS mutants.
    for k in lists:
        for m in [m for m in lists[k] if m["few_mutants"]]:
            by_rule.append({"name": m["name"], "id": m["id"], "set": k, "mutants_used": m["mutants_used"],
                            "mutants_total": m["mutants_total"], "rule": f"fewer than {MIN_MUTANTS} mutants"})
        lists[k] = [m for m in lists[k] if not m["few_mutants"]]
    usable = sorted(m["name"] for m in lists["primary"])
    kept = [n for n in b2a_draw if n in usable]
    remaining = sorted(n for n in usable if n not in kept)
    replacements = random.Random(PILOT_SEED).sample(remaining, len(remaining))[:PILOT_N - len(kept)]
    pilot = sorted(kept + replacements)
    out = {"meta": {"stage": "B2a", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "source": "candidates_frozen.json", "source_sha256": sha256(FROZEN.read_bytes()),
                    "mutant_seed": run_eval.SEED, "mutant_cap": run_eval.MAX_MUTANTS, "min_mutants_flag": MIN_MUTANTS,
                    "pilot_rule": (f"B2a draw random.Random({PILOT_SEED}).sample(sorted names of smoke-passing primary "
                                   f"modules, {PILOT_N}); B2b keeps those that pass the corpus rule and fills each gap, "
                                   f"in order, from random.Random({PILOT_SEED}).sample(R, len(R)) where R = sorted "
                                   f"usable primary modules not already kept"),
                    "usable_rule": (f"fetched with matching sha256, imports in the sandbox, null suite valid, "
                                    f"at least {MIN_MUTANTS} mutants (corpus rule, B2b)")},
           "counts": {"candidates": len(fetched), "fetched": sum(1 for r in fetched.values() if not r["fetch_error"]),
                      "imports_ok": sum(1 for s in smoke.values() if s["import_ok"]),
                      "usable": len(lists["primary"]) + len(lists["baseline"]),
                      "usable_primary": len(lists["primary"]), "usable_baseline": len(lists["baseline"]),
                      "excluded_by_rule": len(by_rule)},
           "primary": lists["primary"], "baseline": lists["baseline"], "exclusions": exclusions,
           "excluded_by_rule": by_rule, "pilot_b2a_draw": b2a_draw, "pilot_replacements": replacements, "pilot": pilot}
    FINAL.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out["counts"]), "pilot:", pilot)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit({"fetch": cmd_fetch, "smoke": lambda: cmd_smoke(set(sys.argv[2:]) or None), "final": cmd_final}
             .get(cmd, lambda: sys.exit(__doc__))())
