#!/usr/bin/env python3
"""Stage B3 derived data. Reads the results files, the saved pilot transcripts and suites, and the
corpus; writes derived files only. It never writes or edits a results file. Stdlib only; test and
module code is read with ast, never run. Deterministic: same inputs, same outputs.

Outputs (derived/):
  b3_module_covariates.json  per usable module: physical lines, functions, classes, branch count
                             (coverage.py num_branches from the B2a null row), mutants available and
                             used, number-constant vs logic mutants in the fixed sample
  b3_pilot_runs.jsonl        per pilot writer run: the B3 per-run fields backfilled (first_iteration_pass,
                             iterations_used, logic/constant split, logging fields, style profile,
                             gaming-detector counts); fields the run did not record are "unavailable"
  b3_reference_gaming.json   gaming-detector counts on reference, constructed and upstream suites
                             (counted only; their rows and scores are not changed)
  b3_report.md               the tables quoted in DESIGN.md and DECISIONS.md, Stage B3
Every output records the sha256 of the inputs it was computed from.

Usage: python3 derive_b3.py
"""
import ast
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path

import run_eval
import static_checks

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "derived"
LOGIC_MIN = 15            # pre-registered minimum of logic mutants for the logic headline (B3)
CONST_HEAVY = 0.5         # sensitivity threshold on constants_share (B3)
UNAV = run_eval.UNAVAILABLE
INPUTS = ["results.jsonl", "results_mutants.jsonl", "results_null.jsonl", "smoke_null.jsonl",
          "smoke_null_mutants.jsonl", "corpus_final.json"]


def load(p):
    return [json.loads(l) for l in (ROOT / p).read_text().splitlines() if l.strip()]


def sha(p):
    return hashlib.sha256((ROOT / p).read_bytes()).hexdigest()


def is_const(op):
    return op in run_eval.CONSTANT_OPERATORS


# ---------------------------------------------------------------- module covariates
def module_sets(final):
    """{module: [(operator, occurrence)]} of the fixed sample, from the latest B2a null run per
    module (smoke_null_mutants.jsonl), checked against corpus_final.json and the stored nulls."""
    latest = {}
    for r in load("smoke_null.jsonl"):
        latest[r["module"]] = r["run_id"]
    sets = defaultdict(list)
    for d in load("smoke_null_mutants.jsonl"):
        if latest.get(d["module"]) == d["run_id"]:
            sets[d["module"]].append((d["operator"], d["occurrence"], d["category"]))
    stored = {r["key"]["module"]: {(o, c) for o, c, _ in r["mutant_statuses"]} for r in load("results_null.jsonl")
              if r["key"]["mutant_set_sha256"] == next((m["mutant_set_sha256"] for m in final["primary"] + final["baseline"]
                                                         if m["name"] == r["key"]["module"]), None)}
    for m in final["primary"] + final["baseline"]:
        s = sets[m["name"]]
        if len(s) != m["mutants_used"]:
            raise SystemExit(f"{m['name']}: {len(s)} sampled mutants in smoke_null_mutants, corpus_final says {m['mutants_used']}")
        cats = defaultdict(int)
        for _, _, c in s:
            cats[c] += 1
        if dict(cats) != m["mutants_by_category"]:
            raise SystemExit(f"{m['name']}: category counts differ from corpus_final")
        if m["name"] in stored and stored[m["name"]] != {(o, c) for o, c, _ in s}:
            raise SystemExit(f"{m['name']}: stored null mutant set differs from the B2a set")
    return sets, sorted(stored)


def covariates(final, sets):
    smoke = {}
    for r in load("smoke_null.jsonl"):
        smoke[r["module"]] = r
    out = []
    for setname in ("primary", "baseline"):
        for m in final[setname]:
            p = ROOT / m["module_file"]
            text = p.read_bytes().decode("utf-8-sig")
            tree = ast.parse(text)
            s = sets[m["name"]]
            n_const = sum(1 for op, _, _ in s if is_const(op))
            out.append({"module": m["name"], "set": setname, "pilot": m["name"] in final["pilot"],
                        "physical_lines": len(text.splitlines()), "lines_corpus_final": m["lines"],
                        "functions": sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))),
                        "classes": sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef)),
                        "branches": smoke[m["name"]]["coverage"]["num_branches"],
                        "statements": smoke[m["name"]]["coverage"]["num_statements"],
                        "mutants_available": m["mutants_total"], "mutants_used": m["mutants_used"],
                        "constant_mutants_n": n_const, "logic_mutants_n": len(s) - n_const,
                        "constants_share": round(n_const / len(s), 4),
                        "logic_headline_eligible": len(s) - n_const >= LOGIC_MIN,
                        "constants_heavy": n_const / len(s) > CONST_HEAVY,
                        "ai_trace": m["flags"]["ai_trace"], "upstream_reference": bool(
                            run_eval.upstream_spec(m["name"]) or (run_eval.module_meta(m["name"])["upstream_tests"] or {})
                            .get("runner") and not (run_eval.module_meta(m["name"])["upstream_tests"] or {}).get("not_runnable"))})
    return out


# ---------------------------------------------------------------- pilot runs
def transcript_fields(run_dir):
    ev = [json.loads(l) for l in (run_dir / "transcript.jsonl").read_text().splitlines()]
    resp = [e for e in ev if e["event"] == "response"]
    sandbox = {e["iteration"]: e["exit_code"] for e in ev if e["event"] == "sandbox"}
    reqs = [e for e in ev if e["event"] == "request"]
    usage = [e["reply"].get("usage", UNAV) for e in resp]
    models = [e["reply"].get("model", UNAV) for e in resp]
    rids = [e.get("request_id") for e in resp]
    return {"first_iteration_pass": sandbox.get(1) == 0, "iteration_1_exit_code": sandbox.get(1),
            "iterations_used": len(reqs), "suite_iterations": len(sandbox),
            "response_models": models, "response_model": models[0] if len(set(models)) == 1 else models,
            "usage_full": usage,
            "peak_input_tokens_per_call": max(u["input_tokens"] + u.get("cache_creation_input_tokens", 0)
                                              + u.get("cache_read_input_tokens", 0) for u in usage),
            "request_ids": rids if any(rids) else UNAV,
            "run_started_at": UNAV, "first_request_at": reqs[0]["time"] if reqs else None,
            "retry_count": UNAV,
            "api_events": [{"iteration": e["iteration"], "type": e.get("type"), "status": e.get("status")}
                           for e in ev if e["event"] == "api_error"] or UNAV}


def pilot_runs(final, rows, details):
    out = []
    per_mut = defaultdict(list)
    for d in details:
        if d["test_file"] == "writer" and d["run_id"].startswith("B2c-pilot"):
            per_mut[d["run_id"]].append(d)
    for r in rows:
        if r.get("tag") != "pilot" or r["test_file"] != "writer":
            continue
        run_dir = ROOT / "runs" / "pilot" / r["run_id"]
        meta = json.loads((run_dir / "meta.json").read_text())
        recs = [d for d in per_mut[r["run_id"]] if d["status"] != "apply_error"]
        if len(recs) != r["mutants_used"] or sum(run_eval.is_killed(d) for d in recs) != r["killed"]:
            raise SystemExit(f"{r['run_id']}: per-mutant rows do not add up to the row")
        selected = [{"operator": d["operator"]} for d in per_mut[r["run_id"]]]
        tf = transcript_fields(run_dir)
        if tf["iterations_used"] != meta["iterations"]:
            raise SystemExit(f"{r['run_id']}: transcript calls differ from meta.iterations")
        suite = sorted((run_dir / "suite").glob("*.py"))
        src = ROOT / run_eval.module_meta(r["module"])["module_path"]
        g = static_checks.gaming_flags(suite, r["module"])
        out.append({"run_id": r["run_id"], "module": r["module"], "seed": r["writer_seed"],
                    "derived_from": {"results_row": "results.jsonl", "per_mutant": "results_mutants.jsonl",
                                     "transcript": f"runs/pilot/{r['run_id']}/transcript.jsonl"},
                    "mutation_score": r["mutation_score"], "mutants_used": r["mutants_used"], "killed": r["killed"],
                    **run_eval.logic_constant_fields(selected, recs),
                    **tf, "design_commit": UNAV,
                    "gaming_flag": g["n_flagged"], "gaming_flag_counts": g["counts"],
                    "style_profile": static_checks.style_profile(suite, src),
                    "line_coverage": (r["coverage"] or {}).get("line_coverage"),
                    "kept_fraction": r["kept_fraction"], "estimated_cost": r["estimated_cost"]})
    return out


def reference_gaming(final):
    out = []
    for m in final["primary"] + final["baseline"]:
        n = m["name"]
        files = sorted((ROOT / "tests" / n).glob("*.py"))
        up = ROOT / "corpus" / n / "upstream_test.txt"
        for p in files + ([up] if up.exists() else []):
            g = static_checks.gaming_flags([p], n)
            out.append({"module": n, "file": p.relative_to(ROOT).as_posix(), "n_tests": g["n_tests"],
                        "n_flagged": g["n_flagged"], "counts": g["counts"]})
    return out


# ---------------------------------------------------------------- report
def fmt(x, nd=3):
    return "—" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def report(cov, runs, ref_g, inputs, stored_null_modules, null_env):
    L = ["# Stage B3 derived tables", "",
         "Generated by `derive_b3.py` from: " + ", ".join(f"`{k}` ({v[:12]}…)" for k, v in inputs.items()) + ".",
         "Descriptive only. Pilot runs are a rehearsal, excluded from the final analysis.", ""]
    for setname in ("primary", "baseline"):
        ms = [c for c in cov if c["set"] == setname]
        L.append(f"- {setname}: {sum(c['logic_headline_eligible'] for c in ms)} of {len(ms)} modules have at least "
                 f"{LOGIC_MIN} logic mutants; {sum(c['constants_heavy'] for c in ms)} have constants_share > {CONST_HEAVY}.")
    L += ["", "## Module covariates", "",
          "| module | set | lines | functions | classes | branches | mutants avail/used | constant | logic | constants_share | logic ≥15 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in cov:
        L.append(f"| {c['module']} | {c['set']} | {c['physical_lines']} | {c['functions']} | {c['classes']} | {c['branches']} | "
                 f"{c['mutants_available']}/{c['mutants_used']} | {c['constant_mutants_n']} | {c['logic_mutants_n']} | "
                 f"{c['constants_share']:.2f} | {'yes' if c['logic_headline_eligible'] else 'no'} |")
    by = defaultdict(list)
    for r in runs:
        by[r["module"]].append(r)
    covd = {c["module"]: c for c in cov}
    L += ["", "## Pilot: per-module scores over 3 runs (descriptive)", "",
          "| module | lines | logic mutants | logic score mean (range) | all-mutant mean (range) | constants mean | first-iter pass | iterations used |",
          "|---|---|---|---|---|---|---|---|"]
    rng_logic, rng_all, rng_logic_elig = [], [], []
    for mod in sorted(by):
        rs = sorted(by[mod], key=lambda r: r["seed"])
        lg = [r["score_logic"] for r in rs]
        al = [r["mutation_score"] for r in rs]
        cs = [r["score_constants"] for r in rs if r["score_constants"] is not None]
        rng_logic.append(max(lg) - min(lg))
        rng_all.append(max(al) - min(al))
        if covd[mod]["logic_headline_eligible"]:
            rng_logic_elig.append(max(lg) - min(lg))
        L.append(f"| {mod} | {covd[mod]['physical_lines']} | {rs[0]['logic_mutants_n']} | {statistics.mean(lg):.3f} "
                 f"({min(lg):.3f}–{max(lg):.3f}) | {statistics.mean(al):.3f} ({min(al):.3f}–{max(al):.3f}) | "
                 f"{fmt(statistics.mean(cs) if cs else None)} | {sum(r['first_iteration_pass'] for r in rs)}/3 | "
                 f"{', '.join(str(r['iterations_used']) for r in rs)} |")
    L += ["", f"- Mean within-module range (max − min over 3 runs), logic score: {statistics.mean(rng_logic):.4f} "
              f"over {len(rng_logic)} modules; over the {len(rng_logic_elig)} modules with ≥{LOGIC_MIN} logic mutants: "
              f"{statistics.mean(rng_logic_elig):.4f}.",
          f"- Mean within-module range, all-mutant score: {statistics.mean(rng_all):.4f} over {len(rng_all)} modules.",
          f"- First-iteration pass: {sum(r['first_iteration_pass'] for r in runs)} of {len(runs)} runs. "
          f"Iterations used: " + ", ".join(f"{k} calls: {sum(1 for r in runs if r['iterations_used'] == k)} runs"
                                            for k in sorted({r['iterations_used'] for r in runs})) + ".",
          f"- Gaming detector on the {len(runs)} pilot suites: {sum(r['gaming_flag'] for r in runs)} tests flagged "
          f"(counted only; pilot rows unchanged).",
          f"- Gaming detector on {len(ref_g)} reference, constructed and upstream files: "
          f"{sum(g['n_flagged'] for g in ref_g)} of {sum(g['n_tests'] for g in ref_g)} tests flagged (counted only).",
          f"- Logging fields absent from the pilot transcripts, marked unavailable: request_ids "
          f"({sum(1 for r in runs if r['request_ids'] == UNAV)} of {len(runs)} runs), run_started_at, retry_count, "
          f"rate-limit events. Available: response_model, the full usage object, peak input tokens per call.",
          f"- Stored null rows: {len(stored_null_modules)} modules; rows with another env_id: {len(null_env)}.",
          "", "## Pilot: style profile per module (mean over 3 runs; descriptive, not scored)", "",
          "| module | tests | tests per public unit | parametrize | fixtures | monkeypatch | mock | raises | equality / truthiness / membership / comparison / other | median asserts per test | median test lines |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    mean = lambda xs: statistics.mean([x for x in xs if x is not None]) if any(x is not None for x in xs) else None
    for mod in sorted(by):
        sp = [r["style_profile"] for r in by[mod]]
        mix = " / ".join(f"{mean([s['assertion_mix'][k] for s in sp]):.2f}" for k in static_checks.ASSERT_KINDS)
        L.append(f"| {mod} | {mean([s['n_tests'] for s in sp]):.1f} | {fmt(mean([s['tests_per_public_unit'] for s in sp]), 2)} | "
                 f"{mean([s['parametrize_share'] for s in sp]):.2f} | {mean([s['fixture_use_share'] for s in sp]):.2f} | "
                 f"{mean([s['monkeypatch_share'] for s in sp]):.2f} | {mean([s['mock_share'] for s in sp]):.2f} | "
                 f"{mean([s['raises_share'] for s in sp]):.2f} | {mix} | {mean([s['median_assertions_per_test'] for s in sp]):.1f} | "
                 f"{mean([s['median_test_lines'] for s in sp]):.1f} |")
    return "\n".join(L) + "\n", {"mean_range_logic": round(statistics.mean(rng_logic), 4),
                                 "mean_range_logic_eligible": round(statistics.mean(rng_logic_elig), 4),
                                 "mean_range_all": round(statistics.mean(rng_all), 4)}


def main():
    final = json.loads((ROOT / "corpus_final.json").read_text())
    inputs = {p: sha(p) for p in INPUTS}
    sets, stored_null_modules = module_sets(final)
    cov = covariates(final, sets)
    rows, details = load("results.jsonl"), load("results_mutants.jsonl")
    runs = pilot_runs(final, rows, details)
    ref_g = reference_gaming(final)
    ident, _ = run_eval.environment_identity()
    null_env = run_eval.null_store_env_check(ident)
    OUT.mkdir(exist_ok=True)
    head = {"generated_by": "derive_b3.py", "inputs_sha256": inputs}
    (OUT / "b3_module_covariates.json").write_text(json.dumps({**head, "logic_min": LOGIC_MIN,
                                                               "constants_heavy_threshold": CONST_HEAVY,
                                                               "modules": cov}, indent=1) + "\n")
    with (OUT / "b3_pilot_runs.jsonl").open("w") as f:
        for r in runs:
            f.write(json.dumps({**r, "inputs_sha256": inputs}, sort_keys=True) + "\n")
    (OUT / "b3_reference_gaming.json").write_text(json.dumps({**head, "suites": ref_g}, indent=1) + "\n")
    text, summary = report(cov, runs, ref_g, inputs, stored_null_modules, null_env)
    (OUT / "b3_report.md").write_text(text)
    print(json.dumps(summary))
    print(f"{len(cov)} modules, {len(runs)} pilot runs, {len(ref_g)} reference files")


if __name__ == "__main__":
    main()
