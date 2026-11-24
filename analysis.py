#!/usr/bin/env python3
"""Analysis input rule (pre-registered, Stage B3; DESIGN.md section 8).

The analysis reads only rows that pass an explicit allowlist: tag `full`, `design_commit` equal to
the commit of the `prereg-v1` git tag, and scorer_revision B3. Dry-run, pilot, untagged reference,
superseded and every other row is excluded. `load_analysis_rows` is the only entry point for the
analysis; it re-checks every row it returns and stops if a non-allowed row got through.

The analysis itself (per-module means and ranges, bootstrap intervals over modules) is written
after the full run, on top of this loader. Stdlib only.
"""
import json
from pathlib import Path

import run_eval

ALLOWED_TAGS = frozenset({"full"})
ALLOWED_SCORER_REVISIONS = frozenset({"B3"})


class NotAllowedRow(RuntimeError):
    pass


def allowed(row, commit):
    return (bool(commit) and row.get("tag") in ALLOWED_TAGS and row.get("design_commit") == commit
            and row.get("scorer_revision") in ALLOWED_SCORER_REVISIONS)


def select_rows(rows, commit):
    """The allowlisted rows, in file order. Rows sharing (run_id, module, test_file) stop the load:
    a run_id is never reused, so a duplicate means something was re-recorded."""
    out = [r for r in rows if allowed(r, commit)]
    keys = [(r["run_id"], r["module"], r["test_file"]) for r in out]
    if len(set(keys)) != len(keys):
        raise NotAllowedRow("duplicate (run_id, module, test_file) among allowlisted rows")
    return out


def check_rows(rows, commit):
    bad = [r for r in rows if not allowed(r, commit)]
    if bad:
        raise NotAllowedRow(f"{len(bad)} row(s) outside the allowlist reached the analysis, e.g. "
                            f"run_id={bad[0].get('run_id')} tag={bad[0].get('tag')}")
    return rows


def load_analysis_rows(path=None, commit=None):
    commit = commit or run_eval.prereg_commit()
    if not commit:
        raise SystemExit(f"no {run_eval.PREREG_TAG} tag: there is no pre-registered design to analyse against")
    path = Path(path or run_eval.RESULTS)
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return check_rows(select_rows(rows, commit), commit)


# ================================================================ B5: the analysis (DESIGN.md 8.3)
# Built on the loader above, which is unchanged from prereg-v1. Reads results.jsonl,
# results_mutants.jsonl, and corpus_final.json (set membership and flags.ai_trace only).
# Prints tables to the terminal and writes no files.
# Run: .venv/bin/python analysis.py
import hashlib
import random
import statistics
from collections import Counter, defaultdict

MUTANTS = run_eval.ROOT / "results_mutants.jsonl"
CORPUS_FINAL = run_eval.CORPUS_FINAL
PLAN = run_eval.ROOT / "full_plan.json"   # B4 run plan (117 runs, seed 20261120): planned runs per module
SETS = ("primary", "baseline")
CONSTANT_OPERATORS = frozenset({"core/NumberReplacer"})   # DESIGN 6.1: excluded from the logic score
BOOT_SEED = 20261117      # DESIGN 8.3: random.Random(20261117)
BOOT_N = 10_000
LOGIC_MIN = 15            # DESIGN 6.1 headline eligibility
SPREAD = 0.0368           # DESIGN 8.3 interpretation rule (pilot mean within-module logic range)
CONSTANTS_HEAVY = 0.5     # DESIGN 8.3 sensitivity 2


# ---------------------------------------------------------------- inputs
def writer_rows(rows):
    """The analysis unit is the writer suite. Null (and any reference) rows are left out."""
    return [r for r in rows if r.get("test_file") == "writer"]


def scored(rows):
    return [r for r in rows if r.get("arm_status") == "ran"]


def planned_runs(path=PLAN):
    """{module: set of planned run_ids}, read from full_plan.json."""
    out = defaultdict(set)
    for r in json.loads(Path(path).read_text())["runs"]:
        out[r["module"]].add(r["run_id"])
    return dict(out)


def split_complete(wrows, planned):
    """(complete_rows, partial_rows). A module is complete when every one of its planned run_ids has an
    allowlisted writer row (scored or failed). B5b: only complete modules enter across-module statistics,
    the within-module range and the sensitivity analyses; partial modules are reported descriptively."""
    have = defaultdict(set)
    for r in wrows:
        have[r["module"]].add(r["run_id"])
    complete = {m for m in have if planned.get(m) and planned[m] <= have[m]}
    return [r for r in wrows if r["module"] in complete], [r for r in wrows if r["module"] not in complete]


def partial_table(prows, planned, sets):
    """Lines of the partial-module table: per-run values, run counts and the exclusion reason."""
    lines = [f"  {'module':<44} {'set':<8} {'run':<4} {'status':<8} {'writer_stop':<15} {'logic':>7} "
             f"{'all-mut':>7} {'const':>7}"]
    for m in sorted({r["module"] for r in prows}, key=lambda m: (SETS.index(sets[m]["set"]), m)):
        runs = sorted((r for r in prows if r["module"] == m), key=lambda r: r["run_id"])
        for r in runs:
            lines.append(f"  {m:<44} {sets[m]['set']:<8} {r['run_id'].rsplit('-', 1)[-1]:<4} {r['arm_status']:<8} "
                         f"{str(r.get('writer_stop')):<15} {fmt(r.get('score_logic')):>7} "
                         f"{fmt(r.get('mutation_score')):>7} {fmt(r.get('score_constants')):>7}")
        missing = sorted(rid.rsplit("-", 1)[-1] for rid in planned.get(m, set()) - {r["run_id"] for r in runs})
        lines.append(f"  {'':<44} -> {len(runs)} of {len(planned.get(m, ()))} planned runs present; "
                     f"excluded: incomplete (missing {', '.join(missing) or 'n/a: not in full_plan.json'})")
    return lines


def corpus_sets(path=CORPUS_FINAL):
    final = json.loads(Path(path).read_text())
    return {m["name"]: {"set": s, "ai_trace": bool(m["flags"]["ai_trace"])} for s in SETS for m in final[s]}


def load_mutants(keys, path=MUTANTS):
    """{(run_id, module, test_file): [per-mutant rows]}, for the given keys only."""
    want, out = set(keys), defaultdict(list)
    with open(path) as f:
        for line in f:
            if line.strip():
                m = json.loads(line)
                k = (m["run_id"], m["module"], m["test_file"])
                if k in want:
                    out[k].append(m)
    return out


def logic_from_mutants(recs):
    """(score_logic, logic_mutants_n) recomputed from per-mutant results: every mutant used
    (apply errors excluded) except number-constant replacements; timeouts count as killed."""
    used = [m for m in recs if m["status"] != "apply_error" and m["operator"] not in CONSTANT_OPERATORS]
    killed = sum(1 for m in used if m["status"] in ("killed", "timeout"))
    return (round(killed / len(used), 4) if used else None), len(used)


def assertion_kill_nontrivial_corrected(recs):
    """B6a, post-hoc, corrected: assertion kills among non-trivial mutants / non-trivial mutants used.
    The stored assertion_kill_rate_nontrivial (run_eval, frozen) drops null-killed mutants from the
    denominator only; this drops them from the numerator too. Apply errors are excluded; rounding is
    run_eval.ratio's (4 places, 0.0 when nothing is left). The stored value is not changed."""
    nt = [m for m in recs if m["status"] != "apply_error" and not m["trivially_killed"]]
    return run_eval.ratio(sum(1 for m in nt if m.get("kill_kind") == "assertion"), len(nt))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# Wrap-up: the commit of the prereg-v1 tag as recorded in DECISIONS.md (Stage B3, `prereg-v1` commit).
# A published copy without git history has no tag; the analysis then uses this hash.
RECORDED_PREREG_COMMIT = "c530e5168b2d14d1f473ae316039ac9b27d52929"


def prereg_commit():
    """The prereg-v1 commit: from the git tag when it exists (it must equal the recorded hash), else the
    recorded hash, with a notice on stderr. stdout is unchanged either way, so tables stay byte-identical."""
    import sys
    tag = run_eval.prereg_commit()
    if tag:
        if tag != RECORDED_PREREG_COMMIT:
            raise SystemExit(f"{run_eval.PREREG_TAG} tag is {tag}, not the recorded {RECORDED_PREREG_COMMIT}")
        return tag
    print(f"note: no {run_eval.PREREG_TAG} git tag here; using the recorded commit {RECORDED_PREREG_COMMIT} "
          f"(DECISIONS.md, Stage B3) as a fallback", file=sys.stderr)
    return RECORDED_PREREG_COMMIT


# ---------------------------------------------------------------- statistics
def quantile(sorted_vals, q):
    """Linear interpolation between closest ranks."""
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def bootstrap(values, seed=BOOT_SEED, n=BOOT_N):
    """95% percentile intervals for the mean and the median of `values` (one per module),
    resampling modules with replacement. Each call starts a fresh random.Random(seed), so an
    interval doesn't depend on which statistics were computed before it. The values are sorted
    first, so the interval doesn't depend on their order either (set order varies with the hash seed)."""
    values = sorted(values)
    rng, k = random.Random(seed), len(values)
    means, meds = [], []
    for _ in range(n):
        s = rng.choices(values, k=k)
        means.append(statistics.fmean(s))
        meds.append(statistics.median(s))
    means.sort()
    meds.sort()
    return (quantile(means, .025), quantile(means, .975)), (quantile(meds, .025), quantile(meds, .975))


def summarize(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0}
    mean_ci, median_ci = bootstrap(vals)
    return {"n": len(vals), "mean": statistics.fmean(vals), "median": statistics.median(vals),
            "mean_ci": mean_ci, "median_ci": median_ci}


def per_module(rows, get):
    """{module: {mean, min, max, range, n}} over the runs where get(row) is not None."""
    by = defaultdict(list)
    for r in rows:
        v = get(r)
        if v is not None:
            by[r["module"]].append(float(v))
    return {m: {"mean": statistics.fmean(v), "min": min(v), "max": max(v), "range": max(v) - min(v), "n": len(v)}
            for m, v in by.items()}


def field(path):
    """Getter for a dotted path into a row; None when any step is missing or None."""
    def get(r):
        for k in path.split("."):
            r = r.get(k) if isinstance(r, dict) else None
        return r
    return get


# ---------------------------------------------------------------- printing
def fmt(v, spec=".4f"):
    return "null" if v is None else format(v, spec)


def stat_line(label, setname, s, spec=".4f"):
    if not s["n"]:
        return f"  {label:<44} {setname:<8} n= 0   (no non-null module values)"
    lo, hi = s["mean_ci"]
    mlo, mhi = s["median_ci"]
    return (f"  {label:<44} {setname:<8} n={s['n']:>2}  mean {fmt(s['mean'], spec)} [{fmt(lo, spec)}, {fmt(hi, spec)}]"
            f"  median {fmt(s['median'], spec)} [{fmt(mlo, spec)}, {fmt(mhi, spec)}]")


def header(title):
    print(f"\n{'=' * 100}\n{title}\n{'=' * 100}")


def across(rows, sets, get, label, spec=".4f", modules=None):
    """One line per set: across-module mean and median (bootstrap CI) of the per-module means."""
    pm = per_module(rows, get)
    for s in SETS:
        mods = [m for m in pm if sets[m]["set"] == s and (modules is None or m in modules)]
        print(stat_line(label, s, summarize([pm[m]["mean"] for m in mods]), spec))


def module_order(mods, sets):
    return sorted(mods, key=lambda m: (SETS.index(sets[m]["set"]), m))


# ---------------------------------------------------------------- sections
def headline(rows, sets, label="headline", logic_mods=None):
    pm = per_module(rows, field("score_logic"))
    mods = set(pm) if logic_mods is None else set(pm) & logic_mods
    for s in SETS:
        vals = [pm[m]["mean"] for m in mods if sets[m]["set"] == s]
        print(stat_line(f"logic score ({label})", s, summarize(vals)))


def range_line(rows, sets):
    pm = per_module(rows, field("score_logic"))
    for s in SETS:
        ranges = [pm[m]["range"] for m in pm if sets[m]["set"] == s]
        mean_r = statistics.fmean(ranges) if ranges else None
        flag = "" if mean_r is None else ("  (above threshold)" if mean_r > SPREAD else "  (below threshold)")
        print(f"  mean within-module range of logic score   {s:<8} n={len(ranges):>2} modules: "
              f"{fmt(mean_r)}   pre-registered threshold {SPREAD}{flag}")


def main():
    commit = prereg_commit()
    all_rows = [json.loads(l) for l in run_eval.RESULTS.read_text().splitlines() if l.strip()]
    allow = load_analysis_rows(commit=commit)
    wrows = writer_rows(allow)
    sets = corpus_sets()
    unknown = sorted({r["module"] for r in wrows} - set(sets))
    if unknown:
        raise SystemExit(f"allowlisted modules not in corpus_final.json: {unknown}")

    header("INPUTS")
    print(f"  prereg-v1 commit  {commit}")
    for p in (run_eval.RESULTS, MUTANTS, CORPUS_FINAL, PLAN):
        print(f"  sha256 {p.name:<24} {sha256(p)}")
    print(f"  bootstrap: {BOOT_N} resamples of modules, percentile 95% intervals, "
          f"random.Random({BOOT_SEED}) restarted for every interval")
    header("ROW COUNTS (results.jsonl)")
    print(f"  rows in file                                   {len(all_rows)}")
    print(f"  excluded by allowlist (tag/commit/scorer)      {len(all_rows) - len(allow)}  "
          f"by tag: {dict(sorted(Counter(str(r.get('tag')) for r in all_rows if r not in allow).items()))}")
    print(f"  allowlisted (tag full, prereg-v1, B3)          {len(allow)}  "
          f"by test_file: {dict(Counter(r['test_file'] for r in allow))}")
    print(f"  excluded: non-writer allowlisted rows          {len(allow) - len(wrows)}")
    print(f"  IN: writer rows                                {len(wrows)}  "
          f"({len({r['module'] for r in wrows})} modules: "
          + ", ".join(f"{s} {len({r['module'] for r in wrows if sets[r['module']]['set'] == s})}" for s in SETS) + ")")

    # integrity: stored logic score == recomputed from per-mutant results
    keys = [(r["run_id"], r["module"], r["test_file"]) for r in wrows]
    pilot = [r for r in all_rows if r.get("tag") == "pilot" and r.get("test_file") == "writer"]   # drift only
    muts = load_mutants(keys + [(r["run_id"], r["module"], r["test_file"]) for r in pilot])
    ok = sum(1 for r, k in zip(wrows, keys)
             if logic_from_mutants(muts[k]) == (r["score_logic"], r["logic_mutants_n"]))
    print(f"  check: score_logic recomputed from results_mutants.jsonl == stored for {ok}/{len(wrows)} rows")

    failed = [r for r in wrows if r.get("arm_status") != "ran"]
    srows = scored(wrows)
    header("FAILED RUNS (excluded from score means)")
    print(f"  total failed {len(failed)} of {len(wrows)}  by status: {dict(Counter(r['arm_status'] for r in failed))}")
    for (m, st), n in sorted(Counter((r["module"], r["arm_status"]) for r in failed).items()):
        print(f"    {m:<44} {st:<20} {n}")
    noscore = sorted({r["module"] for r in wrows} - {r["module"] for r in srows})
    print(f"  modules with no scored run (left out of across-module stats): {noscore or 'none'}")

    # ---- B5b: only modules with all planned runs (full_plan.json) enter across-module statistics
    planned = planned_runs()
    all_wrows, all_srows = wrows, srows
    wrows, prows = split_complete(all_wrows, planned)
    srows, failed = scored(wrows), [r for r in wrows if r.get("arm_status") != "ran"]
    header("COMPLETENESS RULE (all planned runs from full_plan.json present)")
    cmods, pmods = {r["module"] for r in wrows}, {r["module"] for r in prows}
    by_set = lambda mods: ", ".join(f"{s} {sum(1 for m in mods if sets[m]['set'] == s)}" for s in SETS)
    print(f"  allowlisted writer modules {len(cmods) + len(pmods)} ({len(all_wrows)} rows)")
    print(f"  complete -> across-module statistics: {len(cmods)} modules ({by_set(cmods)}), {len(wrows)} rows")
    print(f"  excluded for incompleteness: {len(pmods)} modules ({by_set(pmods)}), {len(prows)} rows "
          f"(listed in the partial-module table)")

    # ---- headline
    logic_n = {m: min(r["logic_mutants_n"] for r in srows if r["module"] == m) for m in {r["module"] for r in srows}}
    ineligible = sorted(m for m, n in logic_n.items() if n < LOGIC_MIN)
    eligible = set(logic_n) - set(ineligible)
    header(f"HEADLINE: LOGIC SCORE (eligible: >= {LOGIC_MIN} logic mutants)")
    print(f"  excluded from headline (< {LOGIC_MIN} logic mutants): {ineligible or 'none'}")
    pl, pa, pc, pn = (per_module(srows, field(f)) for f in
                      ("score_logic", "mutation_score", "score_constants", "mutation_score_nontrivial"))
    share = {m: next(r["constants_share"] for r in srows if r["module"] == m) for m in logic_n}
    const_n = {m: min(r["constant_mutants_n"] for r in srows if r["module"] == m) for m in logic_n}
    rng = lambda d, m: (f"{d[m]['mean']:.4f} [{d[m]['min']:.4f}-{d[m]['max']:.4f}]" if m in d else "null".ljust(22))
    print(f"\n  {'module':<44} {'set':<8} {'ai':<3} {'runs':>4}  {'logic mean [min-max]':<22} {'logic_n':>7}  "
          f"{'all-mutant mean [min-max]':<25} {'constants mean [min-max]':<24} {'const_n':>7} {'c_share':>7}")
    for m in module_order(logic_n, sets):
        print(f"  {m:<44} {sets[m]['set']:<8} {'Y' if sets[m]['ai_trace'] else '-':<3} {pl[m]['n']:>4}  "
              f"{rng(pl, m):<22} {logic_n[m]:>7}  {rng(pa, m):<25} {rng(pc, m):<24} {const_n[m]:>7} {share[m]:>7.2f}")
    print()
    headline(srows, sets, "headline", eligible)
    across(srows, sets, field("mutation_score"), "all-mutant score")
    across(srows, sets, field("score_constants"), "constants-only score (n = modules non-null)")
    print()
    range_line(srows, sets)
    print(f"  ({len(pmods)} incomplete modules are not in these statistics: see the partial-module table)")

    # ---- secondary
    header("SECONDARY MEASURES (per-module mean over runs, then across modules)")
    secondary = [
        ("first-iteration pass rate", field("first_iteration_pass"), ".4f", wrows),
        ("iterations used", field("iterations_used"), ".4f", wrows),
        ("assertion-kill rate (raw)", field("assertion_kill_rate"), ".4f", srows),
        ("assertion-kill rate (non-trivial)", field("assertion_kill_rate_nontrivial"), ".4f", srows),
        ("weak-assertion rate", field("weak_assertion_rate"), ".4f", srows),
        ("line coverage", field("coverage.line_coverage"), ".4f", srows),
        ("branch coverage (n excludes branchless)", field("coverage.branch_coverage"), ".4f", srows),
        ("kept_fraction (validity, condition)", field("kept_fraction"), ".4f", srows),
        ("estimated cost per run ($)", field("estimated_cost"), ".4f", wrows),
        ("tokens in per run", field("tokens_in"), ".0f", wrows),
        ("tokens out per run", field("tokens_out"), ".0f", wrows),
        ("writer wall time per run (s)", field("writer_wall_seconds"), ".1f", wrows),
        ("scoring wall time per run (s)", field("wall_seconds"), ".1f", srows),
    ]
    for label, get, spec, rs in secondary:
        across(rs, sets, get, label, spec)
    print("\n  assertion-kill rate = mutants killed because a test raised AssertionError or pytest's Failed in its "
          "call phase,\n  divided by mutants used (non-trivial: denominator excludes null-killed mutants; "
          "numerator is not restricted).")
    fip = [r for r in wrows if r.get("first_iteration_pass") is not None]
    print(f"\n  runs: first-iteration pass {sum(bool(r['first_iteration_pass']) for r in fip)}/{len(fip)}; "
          f"iterations used {dict(sorted(Counter(r['iterations_used'] for r in wrows).items()))}; "
          f"writer stop {dict(Counter(r['writer_stop'] for r in wrows))}")
    print(f"  total estimated writer cost, allowlisted runs: ${sum(r['estimated_cost'] for r in wrows):.4f} "
          f"over {len(wrows)} runs")
    branchless = sorted({r["module"] for r in srows if field("coverage.branch_coverage")(r) is None})
    print(f"  branch coverage null (branchless) modules, excluded from branch mean: {branchless}")

    header("SCORE BY OPERATOR CATEGORY (n = modules where the category was sampled)")
    cats = sorted({c for r in srows for c in (r.get("mutation_by_category") or {})})
    for c in cats:
        across(srows, sets, field(f"mutation_by_category.{c}.score"), f"{c} (raw)")
        across(srows, sets, field(f"mutation_by_category.{c}.score_nontrivial"), f"{c} (non-trivial)")

    header("STYLE PROFILE (descriptive only, never scored)")
    style = ["n_tests", "tests_per_public_unit", "parametrize_share", "fixture_use_share", "monkeypatch_share",
             "mock_share", "raises_share", "median_assertions_per_test", "median_test_lines"]
    mix = ["equality", "truthiness", "membership", "comparison", "other"]
    for k in style:
        across(srows, sets, field(f"style_profile.{k}"), k, ".3f")
    for k in mix:
        across(srows, sets, field(f"style_profile.assertion_mix.{k}"), f"assertion mix: {k}", ".3f")
    print(f"\n  per module (mean over runs):")
    cols = ["n_tests", "tests_per_public_unit", "parametrize_share", "fixture_use_share", "raises_share",
            "median_assertions_per_test", "median_test_lines"]
    short = ["tests", "per_unit", "param", "fixture", "raises", "med_asrt", "med_lines"]
    pms = {k: per_module(srows, field(f"style_profile.{k}")) for k in cols}
    pmx = {k: per_module(srows, field(f"style_profile.assertion_mix.{k}")) for k in mix}
    print(f"  {'module':<44} " + " ".join(f"{s:>9}" for s in short) + "  " + " ".join(f"{s[:5]:>6}" for s in mix))
    for m in module_order(logic_n, sets):
        print(f"  {m:<44} " + " ".join(f"{fmt(pms[k].get(m, {}).get('mean'), '.2f'):>9}" for k in cols) + "  "
              + " ".join(f"{fmt(pmx[k].get(m, {}).get('mean'), '.2f'):>6}" for k in mix))

    # ---- pre-registered sensitivities
    header("PRE-REGISTERED SENSITIVITY ANALYSES (logic score)")
    no_ai = {m for m in eligible if not sets[m]["ai_trace"]}
    ai = sorted(eligible - no_ai)
    print(f"  1. excluding AI-trace modules: {len(ai)} excluded ({', '.join(ai)})")
    headline(srows, sets, "no AI trace", no_ai)
    heavy = sorted(m for m in eligible if share[m] > CONSTANTS_HEAVY)
    print(f"  2. excluding constants_share > {CONSTANTS_HEAVY}: {len(heavy)} excluded "
          f"({', '.join(f'{m} {share[m]:.2f}' for m in heavy) or 'none'})")
    headline(srows, sets, "constants_share <= 0.5", eligible - set(heavy))
    allm = [r for r in allow if str(r.get("run_id", "")).endswith("-allmutants")]
    print(f"  3. sampled vs all mutants: NOT AVAILABLE ({len(allm)} '-allmutants' rows; "
          f"the all-mutants scoring mode is not implemented, DESIGN 12)")
    zero = [dict(r, score_logic=0.0) if r.get("arm_status") != "ran" else r for r in wrows]
    print(f"  4. failed runs counted as 0: {len(failed)} failed run(s)"
          + ("; identical to the headline" if not failed else ""))
    headline(zero, sets, "failed = 0", eligible | {r["module"] for r in failed})

    # ---- exploratory
    header("EXPLORATORY SENSITIVITIES — NOT PRE-REGISTERED, post-hoc")
    maxit = [r for r in srows if r.get("writer_stop") == "max_iterations"]
    print(f"  (a) drop runs with writer_stop=max_iterations: {len(maxit)} dropped "
          f"({', '.join(r['run_id'] for r in maxit)})")
    headline([r for r in srows if r not in maxit], sets, "no max_iterations runs", eligible)
    print("  (b) drop skijack_ast (ceiling: logic 1.0 on every run)")
    headline(srows, sets, "without skijack_ast", eligible - {"skijack_ast"})
    print("  (c) mutation_score_nontrivial (all mutants, null-killed mutants dropped):")
    across(srows, sets, field("mutation_score_nontrivial"), "mutation_score_nontrivial")
    print(f"\n  {'module':<44} {'set':<8} {'nontrivial mean [min-max]':<25} {'all-mutant mean':>15} "
          f"{'trivially killed (mean)':>24}")
    pt = per_module(srows, field("trivially_killed"))
    for m in module_order(logic_n, sets):
        print(f"  {m:<44} {sets[m]['set']:<8} {rng(pn, m):<25} {pa[m]['mean']:>15.4f} {pt[m]['mean']:>24.1f}")

    # B6a: the stored non-trivial assertion-kill rate counts assertion kills of null-killed mutants in the
    # numerator while dropping those mutants from the denominator. Recomputed here; the stored value is kept.
    print("\n  (d) assertion-kill rate (non-trivial), post-hoc, corrected: numerator also excludes null-killed mutants")
    corr = {r["run_id"]: assertion_kill_nontrivial_corrected(muts[(r["run_id"], r["module"], r["test_file"])])
            for r in srows}
    get_corr = lambda r: corr[r["run_id"]]
    across(srows, sets, field("assertion_kill_rate_nontrivial"), "assert-kill non-trivial, stored")
    across(srows, sets, get_corr, "assert-kill non-trivial, post-hoc corrected")
    differ = [r["run_id"] for r in srows if corr[r["run_id"]] != r["assertion_kill_rate_nontrivial"]]
    print(f"  runs where corrected != stored: {len(differ)} of {len(srows)}" + (f" ({', '.join(differ)})" if differ else ""))
    ps, pc_ = per_module(srows, field("assertion_kill_rate_nontrivial")), per_module(srows, get_corr)
    print(f"\n  {'module':<44} {'set':<8} {'stored mean':>11} {'corrected mean':>14} {'diff':>8}")
    for m in module_order(logic_n, sets):
        print(f"  {m:<44} {sets[m]['set']:<8} {ps[m]['mean']:>11.4f} {pc_[m]['mean']:>14.4f} "
              f"{pc_[m]['mean'] - ps[m]['mean']:>+8.4f}")

    # ---- descriptive extras from DESIGN 8.3
    header("DRIFT CHECK (descriptive; pilot rows are read only here and are not part of the analysis)")
    fl, fa = per_module(all_srows, field("score_logic")), per_module(all_srows, field("mutation_score"))
    both = sorted({r["module"] for r in pilot} & set(fl), key=lambda m: (SETS.index(sets[m]["set"]), m))
    print(f"  pilot writer rows read: {len(pilot)}; modules in both pilot and full: {len(both)} "
          f"(per module, all allowlisted full runs; * = partial module)")
    plog = defaultdict(list)
    for r in pilot:
        plog[r["module"]].append(logic_from_mutants(muts[(r["run_id"], r["module"], r["test_file"])])[0])
    pall = per_module(pilot, field("mutation_score"))
    print(f"  {'module':<44} {'full logic':>10} {'pilot logic':>11} {'diff':>7} {'full all':>9} {'pilot all':>9}"
          f" {'runs f/p':>8}")
    for m in both:
        pm_ = statistics.fmean(plog[m])
        tag = m + ("*" if m in pmods else "")
        print(f"  {tag:<44} {fl[m]['mean']:>10.4f} {pm_:>11.4f} {fl[m]['mean'] - pm_:>+7.4f} {fa[m]['mean']:>9.4f}"
              f" {pall[m]['mean']:>9.4f} {fl[m]['n']:>4}/{len(plog[m])}")
    print("  (pilot logic score recomputed from results_mutants.jsonl; pilot rows predate the score_logic field)")

    header("PARTIAL MODULES (descriptive, not in across-module statistics)")
    print(f"  {len(pmods)} modules, {len(prows)} runs; reason: fewer allowlisted runs than planned in full_plan.json")
    for line in partial_table(prows, planned, sets):
        print(line)

    up = [r for r in allow if r.get("test_file") == "upstream"]
    header("UPSTREAM COMPARISON")
    print(f"  NOT AVAILABLE: {len(up)} allowlisted upstream rows (the tag-full reference-mode run of "
          f"DESIGN 10.5 has not been done)")


if __name__ == "__main__":
    main()

