#!/usr/bin/env python3
"""Stage B2c pilot driver: 10 pilot modules x 3 writer runs, Sonnet 5.5, effort low, tag pilot.

Sequential, seed-major (s1 on all 10 modules, then s2, then s3). Run ids are fixed
(B2c-pilot-sonnet55-<module>-<seed>), so the driver is resumable:
  * a run_id that already has a row in results.jsonl is skipped;
  * a run dir with meta.json but no row is scored (the writer is not called again);
  * a run dir without meta.json (writer interrupted mid-run) stops the driver: spend may have
    happened, and the run is never silently retried.
Failed writer runs are recorded by run_eval.py as a writer_failed row (B2c), never retried.

Stop rules (DECISIONS.md, Stage B2c): spend guard, key found in any written file, more than
5 of the first 10 runs failed, Docker/sandbox not responding or scoring NO-GO, a run (writer +
scoring) over 15 minutes.

The key is read from AGENT_EVAL_API_KEY, passed only to writer.py's environment, used here
only for the byte scan, and never printed or written. Usage: .venv/bin/python pilot.py
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TAG, MODEL, MODEL_SHORT, EFFORT = "pilot", "claude-sonnet-5-5", "sonnet55", "low"
SEEDS = ["s1", "s2", "s3"]
RUN_LIMIT_S = 15 * 60
KEY_ENV = "AGENT_EVAL_API_KEY"
LOG = ROOT / "runs" / TAG / "pilot_log.txt"
SCANNED = ["results.jsonl", "results_mutants.jsonl", "results_null.jsonl", f"runs/{TAG}/ledger.jsonl"]


def log(msg):
    print(msg, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(msg + "\n")


def run_id(module, seed):
    return f"B2c-pilot-{MODEL_SHORT}-{module}-{seed}"


def scored_run_ids():
    p = ROOT / "results.jsonl"
    return {json.loads(l)["run_id"] for l in p.read_text().splitlines() if l.strip()}


def key_found(key, paths):
    needles = [key.encode(), key[-12:].encode()]
    for p in paths:
        if p.is_file() and any(n in p.read_bytes() for n in needles):
            return p
    return None


def docker_ok():
    try:
        return subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True,
                              timeout=30).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def main():
    key = os.environ.pop(KEY_ENV, None)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    if not key:
        raise SystemExit(f"{KEY_ENV} is not set")
    clean_env = dict(os.environ)                    # for run_eval.py: no key
    writer_env = {**clean_env, KEY_ENV: key}        # writer.py pops it before any docker call
    modules = json.loads((ROOT / "corpus_final.json").read_text())["pilot"]
    order = [(m, s) for s in SEEDS for m in modules]
    failures_first10, done = 0, 0
    for i, (module, seed) in enumerate(order, 1):
        rid = run_id(module, seed)
        out = ROOT / "runs" / TAG / rid
        if rid in scored_run_ids():
            log(f"[{i}/30] {rid}: already recorded, skipped")
            continue
        if not docker_ok():
            log(f"STOP: Docker not responding before {rid}")
            return 3
        t0 = time.monotonic()
        if out.exists() and not (out / "meta.json").exists():
            log(f"STOP: {rid} has a run dir without meta.json (interrupted writer run); not retried")
            return 3
        if not (out / "meta.json").exists():
            log(f"[{i}/30] {rid}: writer")
            try:
                w = subprocess.run([sys.executable, "writer.py", "--module", module, "--model", MODEL,
                                    "--effort", EFFORT, "--seed", seed, "--run-id", rid, "--tag", TAG],
                                   cwd=ROOT, env=writer_env, capture_output=True, text=True, timeout=RUN_LIMIT_S)
            except subprocess.TimeoutExpired:
                log(f"STOP: {rid} writer passed {RUN_LIMIT_S}s (killed; no meta.json)")
                return 3
            for line in (w.stdout + w.stderr).strip().splitlines():
                log("    " + line)
            if w.returncode == 2:
                log(f"STOP: spend guard triggered at {rid}")
                return 2
            if not (out / "meta.json").exists():
                log(f"STOP: {rid} writer exited {w.returncode} without meta.json")
                return 3
        meta = json.loads((out / "meta.json").read_text())
        writer_s = time.monotonic() - t0
        ts = time.monotonic()
        try:
            r = subprocess.run([sys.executable, "run_eval.py", "--writer-meta", str(out / "meta.json")],
                               cwd=ROOT, env=clean_env, capture_output=True, text=True,
                               timeout=max(60, RUN_LIMIT_S - writer_s + 60))
        except subprocess.TimeoutExpired:
            log(f"STOP: {rid} scoring timed out (sandbox not responding or run over {RUN_LIMIT_S}s)")
            return 3
        score_s = time.monotonic() - ts
        (out / "scoring_log.txt").write_text(r.stdout + r.stderr)
        (out / "driver.json").write_text(json.dumps({"run_id": rid, "order": i, "scoring_wall_seconds":
                                                     round(score_s, 2), "scoring_exit": r.returncode}) + "\n")
        failed = meta["stop"] in ("failed_truncated", "refusal", "api_error", "wall_cap") or not meta["suite_files"]
        tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-4:])
        log(f"    scoring exit {r.returncode} in {score_s:.0f}s; writer stop={meta['stop']} "
            f"cost=${meta['estimated_cost']:.4f}\n    " + tail.replace("\n", "\n    "))
        if rid not in scored_run_ids():
            log(f"STOP: no results row for {rid} after scoring")
            return 3
        if not failed and r.returncode != 0:
            log(f"STOP: scoring NO-GO for {rid}")
            return 3
        hit = key_found(key, [ROOT / p for p in SCANNED] + [p for p in out.rglob("*") if p.is_file()])
        if hit:
            log(f"STOP: key bytes found in {hit.relative_to(ROOT)}")
            return 4
        done += 1
        if i <= 10 and failed:
            failures_first10 += 1
            if failures_first10 > 5:
                log("STOP: more than 5 of the first 10 runs failed")
                return 5
        total = time.monotonic() - t0
        if total > RUN_LIMIT_S:
            log(f"STOP: {rid} took {total:.0f}s > {RUN_LIMIT_S}s")
            return 6
    log(f"pilot complete: {done} run(s) this invocation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
