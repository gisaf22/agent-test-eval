#!/usr/bin/env python3
"""Stage B3 step h: nothing moved. Run after the scorer changes (f, g). No model API calls.

Scratch checks (results redirected to a scratch directory; nothing appended to the results files):
  gaming   the synthetic cheat suite in derived/b3_checks/gaming_toposort scored in writer mode
  b2b      re-score of B2b-20261119T213540Z-sonnet55-angelbot_context_acl (the B2b verification run)
  pilot    re-score of B2c-pilot-sonnet55-portable_hermes_agent_inline_markdown-s1
  mutmut   toposort with the mutmut cross-check, compared with A2.1 run 20261119T171136Z
Appended runs (reference mode, untagged, as in B2b): the Stage 0 reproduction (4 modules) and the
first reference run of the 6 primary modules whose upstream tests are now wired.
Writes derived/b3_verification.json. Usage: python3 derived/b3_checks/verify_b3.py <scratch dir>
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import run_eval  # noqa: E402

SCRATCH = Path(sys.argv[1])
REAL = {a: getattr(run_eval, a) for a in ("RESULTS", "DETAILS", "MUTMUT_RESULTS", "NULL_STORE")}
UPSTREAM_NEW = ["codebots_arena_elo", "portable_hermes_agent_inline_markdown", "synaptiq_retrieval",
                "trace2task_experience", "trace2task_experience_runtime", "wtftd_war_thunder_full_t_blk"]


def load(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]


def scratch_main(name, args, copy_results=False):
    d = SCRATCH / name
    d.mkdir(parents=True, exist_ok=True)
    for a, p in REAL.items():
        dst = d / p.name
        if a == "NULL_STORE" or copy_results:
            shutil.copy(p, dst)          # stored nulls are reused, as in a real writer run
        else:
            dst.write_text("")
        setattr(run_eval, a, dst)
    sys.argv = ["run_eval.py", *args]
    try:
        code = run_eval.main()
    finally:
        for a, p in REAL.items():
            setattr(run_eval, a, p)
    return code, d


def per_mutant(path, run_id, test_file):
    return {(d["operator"], d["occurrence"]): (d["status"], d.get("kill_kind")) for d in load(path)
            if d["run_id"] == run_id and d["test_file"] == test_file}


def compare_writer(run_id, d):
    orig = next(r for r in load(REAL["RESULTS"]) if r["run_id"] == run_id and r["test_file"] == "writer")
    new = next(r for r in load(d / "results.jsonl") if r["run_id"] == run_id and r["test_file"] == "writer")
    fields = [k for k in run_eval.REPEAT_FIELDS if orig.get(k) != new.get(k)]
    a, b = per_mutant(REAL["DETAILS"], run_id, "writer"), per_mutant(d / "results_mutants.jsonl", run_id, "writer")
    flips = sorted(str(k) for k in set(a) | set(b) if a.get(k) != b.get(k))
    return {"run_id": run_id, "field_diffs": fields, "per_mutant_compared": len(a), "per_mutant_diffs": flips,
            "exact": not fields and not flips and len(a) == len(b) > 0,
            "orig": {k: orig[k] for k in ("mutation_score", "killed", "mutants_used", "tests_kept")},
            "new": {k: new[k] for k in ("mutation_score", "killed", "mutants_used", "tests_kept", "score_logic",
                                         "score_constants", "gaming_flag", "scorer_revision")}}


def real_run(args, log):
    r = subprocess.run([sys.executable, str(ROOT / "run_eval.py"), *args], cwd=ROOT, capture_output=True, text=True)
    (SCRATCH / log).write_text(r.stdout + r.stderr)
    run_id = next((l.split()[0].split("=")[1] for l in r.stdout.splitlines() if l.startswith("run_id=")), None)
    return {"exit": r.returncode, "run_id": run_id, "go": r.stdout.strip().endswith("GO") and "NO-GO" not in r.stdout,
            "repeatability": [l for l in r.stdout.splitlines() if l.startswith("repeatability")]}


def main():
    out = {}
    code, d = scratch_main("gaming", ["--writer-meta", str(ROOT / "derived/b3_checks/gaming_toposort/meta.json")])
    g = next(r for r in load(d / "results.jsonl") if r["test_file"] == "writer")
    out["gaming"] = {k: g.get(k) for k in ("n_tests", "tests_kept", "tests_gaming", "gaming_flag", "gaming_flag_counts",
                                           "gaming_dropped_tests", "kept_fraction", "mutation_score", "killed",
                                           "mutants_used", "score_logic")}
    out["gaming"]["exit"] = code
    for key, rid, meta in [("b2b", "B2b-20261119T213540Z-sonnet55-angelbot_context_acl",
                            "runs/dry_run/B2b-20261119T213540Z-sonnet55-angelbot_context_acl/meta.json"),
                           ("pilot", "B2c-pilot-sonnet55-portable_hermes_agent_inline_markdown-s1",
                            "runs/pilot/B2c-pilot-sonnet55-portable_hermes_agent_inline_markdown-s1/meta.json")]:
        code, d = scratch_main(key, ["--writer-meta", str(ROOT / meta)])
        out[key] = {**compare_writer(rid, d), "exit": code}
    code, d = scratch_main("mutmut", ["--modules", "toposort", "--mutmut", "toposort"], copy_results=True)
    new = [r for r in load(d / "results_mutmut.jsonl") if r["run_id"] not in {x["run_id"] for x in load(REAL["MUTMUT_RESULTS"])}]
    old = {r["test_file"]: r for r in load(REAL["MUTMUT_RESULTS"]) if r["run_id"] == "20261119T171136Z" and r["module"] == "toposort"}
    out["mutmut"] = {"exit": code, "suites": {r["test_file"]: {"statuses_equal": r["statuses"] == old[r["test_file"]]["statuses"],
                                                               "score": r["mutation_score"],
                                                               "score_A2.1": old[r["test_file"]]["mutation_score"]}
                                              for r in new}}
    out["stage0_reproduction"] = real_run(["--modules", "toposort,heapdict,mergedeep,addict"], "stage0.log")
    out["upstream_new"] = real_run(["--modules", ",".join(UPSTREAM_NEW)], "upstream_new.log")
    (ROOT / "derived" / "b3_verification.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
