#!/usr/bin/env python3
"""Stage B4 full-run driver: 39 modules (31 primary, 8 baseline) x 3 writer runs, Sonnet 5.5,
effort low, tag full (DESIGN.md section 10). One command, resumable.

Every start runs the preflight (prereg-v1 ancestor of HEAD; writer, scorer, sandbox, prompt and
corpus files byte-identical to the tag; frozen prompt hash; key present; Docker up; stored-null
env_ids; no leftover project containers or stale run dirs). The plan is built once with seed
20261120 and saved as full_plan.json; a later start loads it, checks it is the same plan, and
skips run_ids that already have a full row in results.jsonl. It is never reshuffled.

Per run: writer.py (unchanged prompt and caps) -> run_eval.py --writer-meta (full scorer; rows
carry tag full, design_commit, scorer_revision B3, harness_version and the B3 logging fields).
A failed writer run gets run_eval's failed row; it is never retried or dropped. A run dir with
meta.json but no row is scored without calling the writer again. A run dir without meta.json
stops the driver (spend may have happened).

Hard stops write runs/full/STOPPED.txt and exit non-zero: spend would pass $8.00; key bytes in
any output file; response_model differs from the first run's; more than 5 of the first 10 runs
failed; more than 10% failed once 20 are done; a run over 15 minutes; a watched code or corpus
file changed; Docker down or scoring NO-GO; writer killed without meta.json.

The driver reads rows only for run_id, tag, test_file and arm_status. It never reads scores.
It never commits. The key comes from AGENT_EVAL_API_KEY only, goes only to writer.py's
environment and the byte scan, and is never printed or written.

B4c (DECISIONS.md, Stage B4c): staged execution for API budget. Wave 1 is all 3 planned runs of 7
primary and 7 baseline modules (random.Random(20261123).sample on each sorted list); wave 2 is the
rest. --wave 1 runs only wave-1 run_ids not yet completed; --wave all (default) runs every one.
--spend-cap X is a hard stop on cumulative full-tag spend (runs/full/ledger.jsonl, checkpoint
included); the $8.00 guard stays the outer limit. At start the driver prints the wave-1 modules,
completed vs remaining runs and the estimated remaining cost, and refuses to start if spend so far
plus that estimate exceeds the cap. The plan (full_plan.json) is unchanged.

Usage: .venv/bin/python run_full.py [--wave {1,all}] [--spend-cap X] [--through N] [--preflight-only] [--dry-plan]
"""
import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import run_eval
import writer

ROOT = Path(__file__).resolve().parent
TAG, MODEL, MODEL_SHORT, EFFORT = "full", "claude-sonnet-5-5", "sonnet55", "low"
SEEDS = ["s1", "s2", "s3"]
PLAN_SEED = 20261120
KEY_ENV = writer.KEY_ENV
FROZEN_COMMIT = "c530e5168b2d14d1f473ae316039ac9b27d52929"   # DECISIONS.md, Stage B3: prereg-v1 commit
FROZEN_PROMPT_HASH = "9c407f6b6e8870edaa6b91607144c1efcd29a0947dc37d79e064fb043c03acc7"
FROZEN_ENV_PREFIX = "70d777ed"
FROZEN_PATHS = ["writer.py", "run_eval.py", "static_checks.py", "sandbox", "DESIGN.md",
                "corpus_final.json", "candidates_frozen.json", "corpus", "tests",
                "derived/b3_module_covariates.json"]   # B4b: source of the per-module branch count
SPEND_CAP = writer.SPEND_CAPS[TAG]   # 8.00
PILOT_MAX_RUN_COST = 0.122           # B2c: largest pilot run; used until a full run costs more
RUN_LIMIT_S = 15 * 60
FAILED_STATUSES = {"writer_failed", "extraction_failed"}

PLAN = ROOT / "full_plan.json"
RESULTS = ROOT / "results.jsonl"
FULL_DIR = ROOT / "runs" / TAG
LEDGER = FULL_DIR / "ledger.jsonl"
PROGRESS = FULL_DIR / "progress.txt"
STOPPED = FULL_DIR / "STOPPED.txt"
LOG = FULL_DIR / "full_log.txt"
OTHER_OUTPUTS = ["results_mutants.jsonl", "results_null.jsonl", "results_mutmut.jsonl"]
COVARIATES = ROOT / "derived" / "b3_module_covariates.json"
TOLERATED = ROOT / "derived" / "b4_tolerated_runs.jsonl"
NULL_STORE = run_eval.NULL_STORE

# B4b (DECISIONS.md, Stage B4b): run_eval.py's console summary formats branch_coverage with :.2f, and
# branch_coverage is null (0/0) on a module with no branches, so main() raises after every row was
# appended. This is the exact traceback of run 5 (B4-full-sonnet55-skijack_ast-s3, scoring_log.txt);
# test_run_full checks that the saved log parses to it. run_eval.py is byte-identical to prereg-v1,
# so its line numbers are fixed.
SUMMARY_CRASH = {
    "frames": [("run_eval.py", 1000, "<module>", "sys.exit(main())"),
               ("run_eval.py", 954, "main",
                """f'{cv.get("line_coverage", 0):.2f}', f'{cv.get("branch_coverage", 0):.2f}',""")],
    "exception": "TypeError: unsupported format string passed to NoneType.__format__",
}
# Score fields that must be non-null on a tolerated run's rows. score_constants is null exactly when the
# module has no constant mutants (0/0), and must be non-null otherwise.
REQUIRED_SCORES = ["kept_fraction", "mutants_used", "killed", "mutation_score", "mutation_score_nontrivial",
                   "assertion_kill_rate", "assertion_kill_rate_nontrivial", "score_logic"]
FRAME = re.compile(r'^  File "(.+)", line (\d+), in (\S+)$')

# B4c: staged execution (DECISIONS.md, Stage B4c).
WAVE1_SEED, WAVE1_PER_SET = 20261123, 7
PILOT_DIR = ROOT / "runs" / "pilot"


class Stop(Exception):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code, self.reason = code, reason


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg):
    print(msg, flush=True)
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(msg + "\n")


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


# ---------------------------------------------------------------- frozen files
def blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def frozen_mismatches():
    """Tracked files under FROZEN_PATHS whose working copy differs from prereg-v1, plus files
    there that are untracked (not ignored) or missing."""
    ls = git("ls-tree", "-r", run_eval.PREREG_TAG, "--", *FROZEN_PATHS)
    if ls.returncode != 0 or not ls.stdout.strip():
        return [f"git ls-tree {run_eval.PREREG_TAG} failed"]
    bad = []
    for line in ls.stdout.splitlines():
        info, path = line.split("\t", 1)
        sha = info.split()[2]
        p = ROOT / path
        if not p.is_file():
            bad.append(f"missing: {path}")
        elif blob_sha(p.read_bytes()) != sha:
            bad.append(f"differs from tag: {path}")
    extra = git("ls-files", "--others", "--exclude-standard", "--", *FROZEN_PATHS).stdout.split()
    bad += [f"untracked: {p}" for p in extra]
    return bad


def watched_files():
    files = [ROOT / l.split("\t", 1)[1] for l in
             git("ls-tree", "-r", run_eval.PREREG_TAG, "--", *FROZEN_PATHS).stdout.splitlines()]
    return files + [Path(__file__).resolve(), PLAN]


def watched_hashes():
    return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None) for p in watched_files()}


# ---------------------------------------------------------------- plan
def corpus_modules():
    final = json.loads(run_eval.CORPUS_FINAL.read_text())
    return [(m["name"], "primary") for m in final["primary"]] + [(m["name"], "baseline") for m in final["baseline"]]


def run_id(module, seed):
    return f"B4-full-{MODEL_SHORT}-{module}-{seed}"


def build_plan():
    pairs = [(m, s, seed) for m, s in corpus_modules() for seed in SEEDS]
    random.Random(PLAN_SEED).shuffle(pairs)
    runs = [{"order": i, "run_id": run_id(m, seed), "module": m, "set": s, "seed": seed}
            for i, (m, s, seed) in enumerate(pairs, 1)]
    return {"tag": TAG, "model": MODEL, "effort": EFFORT, "plan_seed": PLAN_SEED, "seeds": SEEDS,
            "design_commit": FROZEN_COMMIT,
            "corpus_final_sha256": hashlib.sha256(run_eval.CORPUS_FINAL.read_bytes()).hexdigest(),
            "n_runs": len(runs), "runs": runs}


def wave1_modules():
    """7 primary + 7 baseline modules: a fresh random.Random(WAVE1_SEED).sample on each sorted list."""
    mods = corpus_modules()
    return {s: random.Random(WAVE1_SEED).sample(sorted(m for m, t in mods if t == s), WAVE1_PER_SET)
            for s in ("primary", "baseline")}


def wave_runs(plan, wave):
    """Plan entries of the wave, in plan order. wave is "1" or "all"."""
    if wave == "all":
        return list(plan["runs"])
    w1 = {m for ms in wave1_modules().values() for m in ms}
    return [r for r in plan["runs"] if r["module"] in w1]


def known_run_costs():
    """{module: [per-run cost, ...]} from the pilot and full runs' meta.json (writer-reported cost)."""
    out = {}
    for d in (PILOT_DIR, FULL_DIR):
        if d.exists():
            for m in sorted(d.glob("*/meta.json")):
                meta = json.loads(m.read_text())
                if meta.get("estimated_cost") is not None:
                    out.setdefault(meta["module"], []).append(meta["estimated_cost"])
    return out


def estimate_remaining(runs, rows):
    """Estimated writer cost of the runs still to do: each module's mean known per-run cost, else the
    mean over all known runs. A run with meta.json but no row needs scoring only and costs 0."""
    known = known_run_costs()
    flat = [c for cs in known.values() for c in cs]
    fallback = sum(flat) / len(flat) if flat else PILOT_MAX_RUN_COST
    todo = [r for r in runs if r["run_id"] not in rows and not run_meta(r["run_id"])]
    per = {r["run_id"]: (sum(known[r["module"]]) / len(known[r["module"]]) if r["module"] in known else fallback)
           for r in todo}
    return sum(per.values()), todo, fallback


def start_check(plan, wave, cap):
    """Lines describing the wave and budget state; Refuse (no STOPPED.txt) if spend + estimate exceeds cap."""
    rows = full_rows()
    w1 = wave1_modules()
    runs = wave_runs(plan, wave)
    est, todo, fallback = estimate_remaining(runs, rows)
    done = [r for r in runs if r["run_id"] in rows]
    lines = [f"wave 1 primary ({len(w1['primary'])}): {', '.join(w1['primary'])}",
             f"wave 1 baseline ({len(w1['baseline'])}): {', '.join(w1['baseline'])}",
             f"wave {wave}: {len(runs)} runs, {len(done)} completed, {len(runs) - len(done)} remaining "
             f"({len(todo)} need the writer)",
             f"estimated remaining cost ${est:.4f} (per-module pilot/full mean, else ${fallback:.4f}); "
             f"spent ${spend():.4f}; projected ${spend() + est:.4f}; cap ${cap:.2f}"]
    if spend() + est > cap:
        raise Refuse(f"refusing to start: spent ${spend():.4f} + estimated ${est:.4f} = "
                     f"${spend() + est:.4f} exceeds the cap ${cap:.2f}")
    return lines


class Refuse(Exception):
    """Start refused before any run; nothing was spent, so no STOPPED.txt is written."""


def load_or_create_plan():
    fresh = build_plan()
    if PLAN.exists():
        saved = json.loads(PLAN.read_text())
        if {k: v for k, v in saved.items() if k != "created_at"} != fresh:
            raise Stop(9, f"{PLAN.name} differs from the plan the seed and corpus give; not reshuffled, not overwritten")
        return saved
    plan = {**fresh, "created_at": now()}
    PLAN.write_text(json.dumps(plan, indent=1) + "\n")
    return plan


# ---------------------------------------------------------------- state (run ids and status only; never scores)
def full_rows():
    out = {}
    if RESULTS.exists():
        for line in RESULTS.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("tag") == TAG and r.get("test_file") == "writer":
                    out[r["run_id"]] = {"arm_status": r["arm_status"]}
    return out


def spend():
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(l)["estimated_cost"] for l in LEDGER.read_text().splitlines() if l.strip())


def run_meta(rid):
    p = FULL_DIR / rid / "meta.json"
    return json.loads(p.read_text()) if p.exists() else None


def key_found(key, extra=()):
    needles = [key.encode(), key[-12:].encode()]
    paths = [RESULTS, PLAN, TOLERATED, *(ROOT / p for p in OTHER_OUTPUTS), *extra]
    if FULL_DIR.exists():
        paths += [p for p in FULL_DIR.rglob("*") if p.is_file()]
    for p in paths:
        if p.is_file() and any(n in p.read_bytes() for n in needles):
            return p
    return None


def summary(plan, rows):
    done = [r for r in plan["runs"] if r["run_id"] in rows]
    failed = [r for r in done if rows[r["run_id"]]["arm_status"] in FAILED_STATUSES]
    return done, failed


# ---------------------------------------------------------------- B4b: tolerated summary-print crash
def parse_traceback(output):
    """The single traceback ending the output, as {frames, exception}, or None. More than one
    traceback, or anything after the exception line, gives None."""
    lines = output.rstrip("\n").splitlines()
    starts = [i for i, l in enumerate(lines) if l == "Traceback (most recent call last):"]
    if len(starts) != 1:
        return None
    body, frames, i = lines[starts[0] + 1:], [], 0
    while i < len(body):
        m = FRAME.match(body[i])
        if not m:
            break
        if i + 1 >= len(body) or not body[i + 1].startswith("    "):
            return None
        if Path(m.group(1)) != ROOT / "run_eval.py" and Path(m.group(1)).name == "run_eval.py":
            return None   # a run_eval.py that is not this repo's
        frames.append((Path(m.group(1)).name, int(m.group(2)), m.group(3), body[i + 1].strip()))
        i += 2
    if i != len(body) - 1:
        return None
    return {"frames": frames, "exception": body[i]}


def branches(module):
    mods = json.loads(COVARIATES.read_text())["modules"]
    return next(m["branches"] for m in mods if m["module"] == module)


def rows_for(rid):
    if not RESULTS.exists():
        return []
    return [r for r in map(json.loads, filter(str.strip, RESULTS.read_text().splitlines()))
            if r.get("run_id") == rid and r.get("tag") == TAG]


def reference_fields(test_file, exclude):
    """The one field set of every other scored full row of this test_file (None if none or several)."""
    sets = {frozenset(r) for r in map(json.loads, filter(str.strip, RESULTS.read_text().splitlines()))
            if r.get("tag") == TAG and r.get("test_file") == test_file and r.get("arm_status") == "ran"
            and r["run_id"] not in exclude}
    return next(iter(sets)) if len(sets) == 1 else None


def tolerance_problems(entry, exit_code, output):
    """Empty list = the scoring exit 1 is the branchless-module summary crash and the run's rows are
    complete. Checks validity fields only (presence and null-ness); score values are never read."""
    rid, module = entry["run_id"], entry["module"]
    p = []
    if exit_code != 1:
        p.append(f"scoring exit {exit_code}, not 1")
    if branches(module) != 0:
        p.append(f"{module} has {branches(module)} branches in {COVARIATES.name}")
    if parse_traceback(output) != SUMMARY_CRASH:
        p.append("traceback is not the summary-print crash")
    rows = rows_for(rid)
    stored_null_here = any(r["row"]["run_id"] == rid for r in
                           map(json.loads, filter(str.strip, NULL_STORE.read_text().splitlines())))
    expected = sorted(["writer"] + (["null_test.py"] if stored_null_here else []))
    if sorted(r["test_file"] for r in rows) != expected:
        p.append(f"rows {sorted(r['test_file'] for r in rows)} != expected {expected}")
    for r in rows:
        tf = r["test_file"]
        ref = reference_fields(tf, {rid})
        if ref is None or frozenset(r) != ref:
            p.append(f"{tf}: field set differs from the other full {tf} rows")
        if r.get("arm_status") != "ran" or r.get("design_commit") != FROZEN_COMMIT \
                or r.get("scorer_revision") != run_eval.SCORER_REVISION or r.get("harness_version") != run_eval.HARNESS_VERSION:
            p.append(f"{tf}: arm_status/design_commit/scorer_revision/harness_version not as expected")
        nulls = [k for k in REQUIRED_SCORES if r.get(k) is None]
        if (r.get("constant_mutants_n") or 0) > 0 and r.get("score_constants") is None:
            nulls.append("score_constants")
        if nulls:
            p.append(f"{tf}: null score fields {nulls}")
        cv = r.get("coverage") or {}
        if not ("branch_coverage" in cv and cv["branch_coverage"] is None and cv.get("num_branches") == 0):
            p.append(f"{tf}: branch coverage not recorded as null with 0 branches")
    if run_eval.null_store_env_check(run_eval.environment_identity()[0]):   # a check main() skipped
        p.append("stored null rows with another env_id")
    return p


def tolerated_ids():
    if not TOLERATED.exists():
        return set()
    return {json.loads(l)["run_id"] for l in TOLERATED.read_text().splitlines() if l.strip()}


def tolerate_or_stop(entry, exit_code, output):
    if entry["run_id"] in tolerated_ids():
        return
    problems = tolerance_problems(entry, exit_code, output)
    if problems:
        raise Stop(3, f"scoring NO-GO for {entry['run_id']}: " + "; ".join(problems))
    TOLERATED.parent.mkdir(parents=True, exist_ok=True)
    with TOLERATED.open("a") as f:
        f.write(json.dumps({"run_id": entry["run_id"], "module": entry["module"], "scoring_exit": exit_code,
                            "branches": 0, "traceback": SUMMARY_CRASH["exception"],
                            "rows": sorted(r["test_file"] for r in rows_for(entry["run_id"])),
                            "scoring_log_sha256": hashlib.sha256(output.encode()).hexdigest(),
                            "rule": "DECISIONS.md, Stage B4b", "recorded_at": now()}) + "\n")
    log(f"    {entry['run_id']}: scoring exit 1 tolerated (branchless summary-print crash; rows complete)")


def check_recorded_nonzero_exits(plan, rows):
    """On every start: a scored run whose driver.json shows a non-zero scoring exit must be a
    tolerated one (checked here from its saved scoring_log.txt if not recorded yet)."""
    for e in plan["runs"]:
        d = FULL_DIR / e["run_id"] / "driver.json"
        if e["run_id"] not in rows or rows[e["run_id"]]["arm_status"] in FAILED_STATUSES or not d.exists():
            continue
        code = json.loads(d.read_text())["scoring_exit"]
        if code != 0:
            tolerate_or_stop(e, code, (FULL_DIR / e["run_id"] / "scoring_log.txt").read_text())


def write_progress(plan, rows, last, t_start, cap=None):
    done, failed = summary(plan, rows)
    wall = 0.0
    for r in done:
        d = FULL_DIR / r["run_id"] / "driver.json"
        if d.exists():
            wall += json.loads(d.read_text()).get("total_seconds") or 0
    tol = sorted(tolerated_ids())
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(
        f"updated {now()}\nruns done {len(done)} of {plan['n_runs']}\nlast run_id {last}\n"
        f"cumulative spend ${spend():.4f} (cap ${cap or SPEND_CAP:.2f})\nfailed {len(failed)}\n"
        f"elapsed this invocation {time.monotonic() - t_start:.0f}s; summed run wall {wall:.0f}s\n"
        f"tolerated scoring exits (B4b, {TOLERATED.name}): {len(tol)}" + (f" ({', '.join(tol)})" if tol else "") + "\n")


def check_stops(plan, rows, key, first_model, cap=None):
    """Stops that depend on the recorded state. Returns the first run's response_model."""
    done, failed = summary(plan, rows)
    hit = key_found(key)
    if hit:
        raise Stop(4, f"key bytes found in {hit.relative_to(ROOT) if hit.is_relative_to(ROOT) else hit}")
    for r in done:
        m = (run_meta(r["run_id"]) or {}).get("response_model")
        if m is None:
            continue
        if not isinstance(m, str):
            raise Stop(7, f"{r['run_id']}: response_model changed within the run: {m}")
        first_model = first_model or m
        if m != first_model:
            raise Stop(7, f"{r['run_id']}: response_model {m} != first run's {first_model}")
    first10 = [r for r in done if r["order"] <= 10]
    if sum(r in failed for r in first10) > 5:
        raise Stop(5, "more than 5 of the first 10 runs failed")
    if len(done) >= 20 and len(failed) / len(done) > 0.10:
        raise Stop(5, f"{len(failed)} of {len(done)} runs failed (> 10%)")
    cap = SPEND_CAP if cap is None else cap
    if spend() > cap:
        raise Stop(2, f"spend ${spend():.4f} passed ${cap:.2f}")
    return first_model


# ---------------------------------------------------------------- docker
def docker_ok():
    try:
        return subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True,
                              timeout=30).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def project_containers(modules):
    """This project's sandbox containers for corpus modules: name ate-<module>-<8 hex> and the
    project image. Nothing else is ever listed for removal."""
    pat = re.compile(r"^ate-(%s)-[0-9a-f]{8}$" % "|".join(map(re.escape, modules)))
    out = subprocess.run(["docker", "ps", "-a", "--filter", "name=ate-", "--format", "{{.Names}}\t{{.Image}}"],
                         capture_output=True, text=True, timeout=60).stdout
    return [n for n, img in (l.split("\t", 1) for l in out.splitlines() if "\t" in l)
            if pat.match(n) and img == run_eval.IMAGE]


# ---------------------------------------------------------------- preflight
def preflight(key):
    out = []
    if STOPPED.exists():
        raise Stop(9, f"{STOPPED.relative_to(ROOT)} exists from an earlier stop; review it and move it aside first")
    if git("merge-base", "--is-ancestor", run_eval.PREREG_TAG, "HEAD").returncode != 0:
        raise Stop(9, f"{run_eval.PREREG_TAG} is not an ancestor of HEAD")
    if run_eval.prereg_commit() != FROZEN_COMMIT:
        raise Stop(9, f"{run_eval.PREREG_TAG} points at {run_eval.prereg_commit()}, not {FROZEN_COMMIT}")
    out.append(f"ok  {run_eval.PREREG_TAG} = {FROZEN_COMMIT[:12]}, ancestor of HEAD")
    bad = frozen_mismatches()
    if bad:
        raise Stop(9, "frozen files changed: " + "; ".join(bad[:10]))
    n = len(watched_files()) - 2
    out.append(f"ok  {n} writer/scorer/sandbox/prompt/corpus files byte-identical to the tag")
    if writer.prompt_hash() != FROZEN_PROMPT_HASH:
        raise Stop(9, f"prompt hash {writer.prompt_hash()[:12]} != frozen {FROZEN_PROMPT_HASH[:12]}")
    out.append(f"ok  prompt_hash {FROZEN_PROMPT_HASH[:12]}")
    if not key:
        raise Stop(9, f"{KEY_ENV} is not set")
    out.append(f"ok  {KEY_ENV} present (not printed)")
    if not docker_ok():
        raise Stop(3, "Docker is not responding")
    ident = run_eval.build_and_verify_image()
    if not ident["env_id"].startswith(FROZEN_ENV_PREFIX):
        raise Stop(9, f"env_id {ident['env_id'][:12]} is not the frozen {FROZEN_ENV_PREFIX}")
    out.append(f"ok  Docker up; image built, pip freeze = lock; env_id {ident['env_id'][:12]}")
    modules = [m for m, _ in corpus_modules()]
    nulls = [json.loads(l) for l in run_eval.NULL_STORE.read_text().splitlines() if l.strip()]
    with_null, mism = set(), []
    for r in nulls:
        m = r["key"]["module"]
        if m in modules and r["key"]["harness_version"] == run_eval.HARNESS_VERSION:
            with_null.add(m)
            if r["key"]["env_id"] != ident["env_id"] or r["row"].get("env_id") != ident["env_id"]:
                mism.append(m)
    if mism:
        raise Stop(9, f"stored null env_id differs for: {sorted(set(mism))}")
    no_null = [m for m in modules if m not in with_null]
    out.append(f"ok  stored null env_id = current for {len(with_null)} modules; "
               f"{len(no_null)} have none yet (scored and stored on their first run, B2b)")
    left = project_containers(modules)
    for name in left:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
    if project_containers(modules):
        raise Stop(3, "leftover project containers could not be removed")
    out.append(f"ok  leftover project containers: {len(left)} found, {len(left)} removed by name"
               + (f" ({', '.join(left)})" if left else "") + "; the project creates no volumes")
    plan_ids = {r["run_id"] for r in build_plan()["runs"]}
    rows = full_rows()
    stale = []
    if FULL_DIR.exists():
        for d in sorted(p for p in FULL_DIR.iterdir() if p.is_dir()):
            if d.name not in plan_ids:
                stale.append(f"{d.name} (not in plan)")
            elif not (d / "meta.json").exists():
                stale.append(f"{d.name} (no meta.json: interrupted writer)")
    if stale:
        raise Stop(3, "stale run dirs: " + "; ".join(stale))
    pending = [rid for rid in plan_ids if rid not in rows and run_meta(rid)]
    out.append("ok  no stale run dirs" + (f"; {len(pending)} with meta.json to be scored" if pending else ""))
    return out


# ---------------------------------------------------------------- one run
def call_writer(entry, env, timeout):
    return subprocess.run([sys.executable, "writer.py", "--module", entry["module"], "--model", MODEL,
                           "--effort", EFFORT, "--seed", entry["seed"], "--run-id", entry["run_id"], "--tag", TAG],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)


def call_scorer(meta_path, env, timeout):
    return subprocess.run([sys.executable, "run_eval.py", "--writer-meta", str(meta_path)],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)


def max_run_cost(plan):
    costs = [(run_meta(r["run_id"]) or {}).get("estimated_cost") or 0 for r in plan["runs"]]
    return max([PILOT_MAX_RUN_COST, *costs])


def one_run(entry, plan, writer_env, clean_env, cap=None):
    rid = entry["run_id"]
    out = FULL_DIR / rid
    n = plan["n_runs"]
    cap = SPEND_CAP if cap is None else cap
    if spend() + max_run_cost(plan) > cap:
        raise Stop(2, f"before {rid}: spend ${spend():.4f} + largest run ${max_run_cost(plan):.4f} "
                      f"would pass ${cap:.2f}")
    if not docker_ok():
        raise Stop(3, f"Docker not responding before {rid}")
    if out.exists() and not (out / "meta.json").exists():
        raise Stop(3, f"{rid}: run dir without meta.json (interrupted writer); not retried")
    t0 = time.monotonic()
    writer_called = False
    if not (out / "meta.json").exists():
        log(f"[{entry['order']}/{n}] {rid}: writer")
        writer_called = True
        try:
            w = call_writer(entry, writer_env, RUN_LIMIT_S)
        except subprocess.TimeoutExpired:
            raise Stop(6, f"{rid}: writer passed {RUN_LIMIT_S}s (killed; no meta.json)")
        for line in (w.stdout + w.stderr).strip().splitlines():
            log("    " + line)
        if w.returncode == 2:
            raise Stop(2, f"writer spend guard triggered at {rid}")
        if not (out / "meta.json").exists():
            raise Stop(3, f"{rid}: writer exited {w.returncode} without meta.json")
    else:
        log(f"[{entry['order']}/{n}] {rid}: meta.json present, scoring only")
    meta = run_meta(rid)
    writer_s = time.monotonic() - t0
    ts = time.monotonic()
    try:
        r = call_scorer(out / "meta.json", clean_env, max(60, RUN_LIMIT_S - writer_s + 60))
    except subprocess.TimeoutExpired:
        raise Stop(6, f"{rid}: scoring timed out (sandbox not responding or run over {RUN_LIMIT_S}s)")
    score_s = time.monotonic() - ts
    (out / "scoring_log.txt").write_text(r.stdout + r.stderr)
    total = time.monotonic() - t0
    (out / "driver.json").write_text(json.dumps({
        "run_id": rid, "order": entry["order"], "writer_called": writer_called,
        "writer_subprocess_seconds": round(writer_s, 2), "writer_wall_seconds": meta.get("wall_seconds"),
        "scoring_wall_seconds": round(score_s, 2), "total_seconds": round(total, 2),
        "scoring_exit": r.returncode, "finished_at": now()}) + "\n")
    tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-3:])
    log(f"    scoring exit {r.returncode} in {score_s:.0f}s; writer stop={meta['stop']} "
        f"cost=${meta['estimated_cost']:.4f}\n    " + tail.replace("\n", "\n    "))
    rows = full_rows()
    if rid not in rows:
        raise Stop(3, f"no results row for {rid} after scoring")
    if rows[rid]["arm_status"] not in FAILED_STATUSES and r.returncode != 0:
        tolerate_or_stop(entry, r.returncode, r.stdout + r.stderr)   # B4b; anything else is a NO-GO stop
    if total > RUN_LIMIT_S:
        raise Stop(6, f"{rid} took {total:.0f}s > {RUN_LIMIT_S}s")


# ---------------------------------------------------------------- main loop
def run(plan, key, through=None, t_start=None, wave="all", cap=None):
    t_start = t_start or time.monotonic()
    cap = SPEND_CAP if cap is None else min(cap, SPEND_CAP)   # B4c: $8.00 stays the outer limit
    selected = {r["run_id"] for r in wave_runs(plan, wave)}
    clean_env = {k: v for k, v in os.environ.items() if k not in (KEY_ENV, "ANTHROPIC_API_KEY")}
    writer_env = {**clean_env, KEY_ENV: key}
    hashes = watched_hashes()
    check_recorded_nonzero_exits(plan, full_rows())
    first_model = check_stops(plan, full_rows(), key, None, cap)
    for entry in plan["runs"]:
        if through is not None and entry["order"] > through:
            break
        if entry["run_id"] not in selected or entry["run_id"] in full_rows():
            continue
        if watched_hashes() != hashes:
            raise Stop(8, f"a watched code or corpus file changed before {entry['run_id']}")
        try:
            one_run(entry, plan, writer_env, clean_env, cap)
        finally:
            write_progress(plan, full_rows(), entry["run_id"], t_start, cap)
        if watched_hashes() != hashes:
            raise Stop(8, f"a watched code or corpus file changed during {entry['run_id']}")
        first_model = check_stops(plan, full_rows(), key, first_model, cap)
    done, failed = summary(plan, full_rows())
    w_done = len(selected & set(full_rows()))
    log(f"stopped at plan position {through or plan['n_runs']}: {len(done)} of {plan['n_runs']} done "
        f"(wave {wave}: {w_done} of {len(selected)}), {len(failed)} failed, spend ${spend():.4f} (cap ${cap:.2f})")
    return 0


def stop_file(e):
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    STOPPED.write_text(f"{now()}\nexit {e.code}\n{e.reason}\n")
    log(f"STOP (exit {e.code}): {e.reason}")
    return e.code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--through", type=int, help="process plan positions 1..N only (checkpoint)")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--dry-plan", action="store_true", help="print the plan; no preflight, no API, no files")
    ap.add_argument("--wave", choices=["1", "all"], default="all",
                    help="1: only wave-1 run_ids not yet completed; all: every run not completed (B4c)")
    ap.add_argument("--spend-cap", type=float, default=SPEND_CAP,
                    help=f"hard stop on cumulative full-tag spend incl. the checkpoint; at most ${SPEND_CAP:.2f}")
    a = ap.parse_args()
    if not 0 < a.spend_cap <= SPEND_CAP:
        ap.error(f"--spend-cap must be > 0 and <= {SPEND_CAP:.2f} (the outer guard)")
    if a.dry_plan:
        p = build_plan()
        for r in p["runs"]:
            print(f"{r['order']:>3} {r['run_id']} {r['set']}")
        print(f"{p['n_runs']} runs; saved plan {'matches' if PLAN.exists() and json.loads(PLAN.read_text()).get('runs') == p['runs'] else 'absent or differs'}")
        return 0
    key = os.environ.pop(KEY_ENV, None)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    t_start = time.monotonic()
    try:
        for line in preflight(key):
            log("preflight " + line)
        plan = load_or_create_plan()
        log(f"preflight ok; plan {PLAN.name}: {plan['n_runs']} runs, {len(full_rows())} with a full row")
        for line in start_check(plan, a.wave, a.spend_cap):
            log("start " + line)
        if a.preflight_only:
            return 0
        return run(plan, key, a.through, t_start, a.wave, a.spend_cap)
    except Refuse as e:
        log(f"REFUSED (exit 2): {e}")
        return 2
    except Stop as e:
        return stop_file(e)


if __name__ == "__main__":
    sys.exit(main())
