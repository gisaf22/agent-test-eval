"""In-container runner. Stdlib only (plus pytest / coverage / cosmic-ray / mutmut as tools);
invoked by run_eval.py via `docker exec`.

Layout inside the container (all on tmpfs):
  /work/src/<module>.py          pristine module under test
  /work/tests/<suite>/...        one directory per suite (one or more test files)
  /work/harness/*.py             this file, killtype_plugin, suite_plugin, script_wrapper, alias_plugin
  /work/harness/deselect_<suite>.json   test ids dropped by the validity check (optional)
  /work/harness/aliases_<suite>.json    repo import paths of the module (upstream suites, optional)
  /work/ctl/                     mutant list and validity seeds: root only (B3)
  /work/xchg/                    files the test process writes for the runner (kill cause, outcomes, coverage data)

B3 privilege split: run_eval execs this runner as root (container caps: SETUID, SETGID, KILL
only). /work is root-owned, so the test processes, which run as uid 10001 with no capabilities,
cannot write, chmod or replace the module, the harness or the suites, and cannot read /work/ctl.
When the runner is not root (older layout), tests run as the runner's own user.

Test modes:
  pytest  python -m pytest [-x] -q -p no:cacheprovider -p killtype_plugin -p suite_plugin <suite dir>
  script  python script_wrapper.py <suite dir>/<file> [-f]   (unittest.main()-style, one file)

Subcommands (JSON on stdout):
  enumerate <module>                                         -> [{operator, occurrence, ...}]
  validity  <module> <suite> <mode> <runs.json>              -> [{order_seed, hash_seed, tests, ...}]
  baseline  <module> <suite> <mode> <n>                      -> [{exit_code, seconds, ...}]
  coverage  <module> <suite> <mode>                          -> coverage.py JSON report for the module
  mutants   <module> <suite> <mode> <mutants.json> <timeout> -> JSON lines, one per mutant
  mutmut    <module> <suite> <mode>                          -> {status counts, per-mutant list}
Scoring runs (baseline, coverage, mutants) use pytest's own order and PYTHONHASHSEED=0.
"""
import glob
import hashlib
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time

WORK = "/work"
SRC = os.path.join(WORK, "src")
HARNESS = os.path.join(WORK, "harness")
XCHG = os.path.join(WORK, "xchg")
CTL = os.path.join(WORK, "ctl")
KILLTYPE_OUT = os.path.join(XCHG, "killtype.json")
OUTCOMES_OUT = os.path.join(XCHG, "outcomes.json")
TEST_UID = TEST_GID = 10001
AS_ROOT = os.geteuid() == 0
ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp",
       "PYTHONPATH": SRC + ":" + HARNESS, "PYTHONDONTWRITEBYTECODE": "1",
       "PYTHONHASHSEED": "0", "LANG": "C.UTF-8", "KILLTYPE_OUT": KILLTYPE_OUT}


def module_path(module):
    return os.path.join(SRC, module + ".py")


def suite_target(suite, mode):
    d = os.path.join(WORK, "tests", suite)
    if mode == "script":
        files = sorted(glob.glob(os.path.join(d, "*.py")))
        if len(files) != 1:
            raise SystemExit(f"script mode needs exactly one file in {d}, found {files}")
        return files[0]
    return d


def test_cmd(suite, mode, failfast=True):
    target = suite_target(suite, mode)
    if mode == "pytest":
        alias = ["-p", "alias_plugin"] if os.path.exists(os.path.join(HARNESS, f"aliases_{suite}.json")) else []
        return ([sys.executable, "-m", "pytest"] + (["-x"] if failfast else []) +
                ["-q", "-p", "no:cacheprovider", "-p", "killtype_plugin", "-p", "suite_plugin"] + alias + [target])
    if mode == "script":
        return [sys.executable, os.path.join(HARNESS, "script_wrapper.py"), target] + (["-f"] if failfast else [])
    raise ValueError(mode)


def suite_env(suite, extra=None):
    env = dict(ENV)
    des = os.path.join(HARNESS, f"deselect_{suite}.json")
    if os.path.exists(des):
        env["SUITE_DESELECT"] = des
    ali = os.path.join(HARNESS, f"aliases_{suite}.json")
    if os.path.exists(ali):
        env["SUITE_ALIASES"] = ali
    env.update(extra or {})
    return env


def _xchg():
    if not os.path.isdir(XCHG):
        os.makedirs(XCHG)
        os.chmod(XCHG, 0o777)   # the test user writes here; root (no CAP_FOWNER) can still remove


WIPE_DIRS = ("/tmp", "/dev/shm", XCHG)
_WIPE = ("import os, shutil\n"
         "for d in %r:\n"
         "    for e in (os.listdir(d) if os.path.isdir(d) else []):\n"
         "        p = os.path.join(d, e)\n"
         "        try:\n"
         "            shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.unlink(p)\n"
         "        except OSError:\n"
         "            pass\n" % (WIPE_DIRS,))


def wipe_test_state():
    """B3: before every test run, delete everything the test user can delete in the places it can
    write (/tmp, /dev/shm, /work/xchg), as that user, so no run sees files left by an earlier run
    (pytest's kept basetemp dirs, coverage data, files a test wrote). Root-owned runner files live
    in /work/ctl and are untouched. No-op in the older single-user layout."""
    if AS_ROOT:
        subprocess.run([sys.executable, "-c", _WIPE], env=ENV, cwd="/", capture_output=True, timeout=60, **_drop())


def _drop():
    """Popen kwargs that run a test process as the unprivileged test user (when the runner is root)."""
    return {"user": TEST_UID, "group": TEST_GID, "extra_groups": []} if AS_ROOT else {}


def classify(mode, code, output):
    """Kill cause for a non-zero, non-timeout run (assertion | test_exception |
    collection_error | crash); see killtype_plugin and script_wrapper."""
    try:
        with open(KILLTYPE_OUT) as f:
            info = json.load(f)
        return info["kind"], info["exc_type"]
    except (OSError, ValueError, KeyError):
        pass
    if mode == "script":
        m = re.search(r"FAILED \((failures|errors)=\d+\)", output)
        if m:
            return ("assertion" if m.group(1) == "failures" else "test_exception"), m.group(1)
    return "crash", f"exit={code}"


def run_cmd(cmd, env, timeout):
    _xchg()
    wipe_test_state()
    for p in (KILLTYPE_OUT, OUTCOMES_OUT):
        if os.path.exists(p):
            os.remove(p)
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=WORK, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True, **_drop())
    try:
        out, _ = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        timed_out = True
    return proc.returncode, timed_out, time.monotonic() - t0, out.decode("utf-8", "replace")


def run_tests(suite, mode, timeout):
    code, timed_out, secs, output = run_cmd(test_cmd(suite, mode), suite_env(suite), timeout)
    if timed_out:
        return {"status": "timeout", "exit_code": None, "seconds": secs}
    if code == 0:
        return {"status": "survived", "exit_code": 0, "seconds": secs}
    kind, exc_type = classify(mode, code, output)
    return {"status": "killed", "kill_kind": kind, "exc_type": exc_type,
            "exit_code": code, "seconds": secs, "tail": output[-300:]}


def cmd_enumerate(module):
    os.makedirs(CTL, mode=0o700, exist_ok=True)   # B3: the session DB lists every mutant; root only
    cfg = os.path.join(CTL, "cr.toml")
    db = os.path.join(CTL, "cr_session.sqlite")
    for p in (cfg, db):
        if os.path.exists(p):
            os.remove(p)
    with open(cfg, "w") as f:
        f.write(f'[cosmic-ray]\nmodule-path = "{module_path(module)}"\ntimeout = 10.0\n'
                f'excluded-modules = []\ntest-command = "false"\n'
                f'[cosmic-ray.distributor]\nname = "local"\n')
    subprocess.run(["cosmic-ray", "init", cfg, db], check=True, env=ENV,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = subprocess.run(["cosmic-ray", "dump", db], check=True, env=ENV,
                         capture_output=True, text=True).stdout
    mutants = []
    for line in out.splitlines():
        job, _result = json.loads(line)
        assert len(job["mutations"]) == 1, job
        m = job["mutations"][0]
        mutants.append({"operator": m["operator_name"], "occurrence": m["occurrence"],
                        "start_pos": m["start_pos"], "end_pos": m["end_pos"]})
    print(json.dumps(mutants))


def cmd_validity(module, suite, mode, runs_json):
    """Original code, no failfast, every test's outcome; each run has its own order and hash seed."""
    with open(runs_json) as f:
        runs = json.load(f)
    res = []
    for r in runs:
        env = suite_env(suite, {"SUITE_ORDER_SEED": str(r["order_seed"]),
                                "PYTHONHASHSEED": str(r["hash_seed"]), "SUITE_OUTCOMES": OUTCOMES_OUT})
        env.pop("SUITE_DESELECT", None)            # validity always sees the whole suite
        code, timed_out, secs, output = run_cmd(test_cmd(suite, mode, failfast=False), env, 300)
        try:
            with open(OUTCOMES_OUT) as f:
                rec = json.load(f)
        except (OSError, ValueError):
            rec = {"tests": {}, "collection_errors": ["<no outcome record>"]}
        res.append({**r, "exit_code": code, "timed_out": timed_out, "seconds": round(secs, 4),
                    "tests": rec["tests"], "collection_errors": rec["collection_errors"],
                    "tail": output[-300:] if code else ""})
    print(json.dumps(res))


def cmd_baseline(module, suite, mode, n):
    res = []
    for _ in range(int(n)):
        r = run_tests(suite, mode, timeout=120)
        res.append({"exit_code": r["exit_code"], "timed_out": r["status"] == "timeout",
                    "seconds": round(r["seconds"], 4), "tail": r.get("tail", "")})
    print(json.dumps(res))


def cmd_coverage(module, suite, mode):
    _xchg()
    os.makedirs(CTL, mode=0o700, exist_ok=True)
    data, rep = os.path.join(XCHG, "cov.data"), os.path.join(CTL, "cov.json")
    for p in (data, rep):
        if os.path.exists(p):
            os.remove(p)
    cmd = test_cmd(suite, mode)
    cov = [sys.executable, "-m", "coverage", "run", "--branch", f"--data-file={data}",
           f"--include={module_path(module)}"]
    cov += cmd[1:] if mode == "script" else ["-m"] + cmd[2:]
    code, timed_out, _, output = run_cmd(cov, suite_env(suite), 300)
    if code != 0 or timed_out:
        print(json.dumps({"error": f"coverage run exit={code} timeout={timed_out}", "tail": output[-300:]}))
        return
    subprocess.run([sys.executable, "-m", "coverage", "json", f"--data-file={data}", "-o", rep,
                    f"--include={module_path(module)}"], check=True, env=ENV, cwd=WORK,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(rep) as f:
        r = json.load(f)
    files = r["files"]
    assert len(files) == 1, list(files)
    fr = next(iter(files.values()))
    print(json.dumps({"summary": fr["summary"], "executed_lines": fr["executed_lines"],
                      "missing_lines": fr["missing_lines"]}))


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def cmd_mutants(module, suite, mode, mutants_json, timeout):
    """Each mutant is applied to the pristine file, tested, and reverted; the revert is checked."""
    path = module_path(module)
    with open(path, "rb") as f:
        pristine = f.read()
    pristine_sha = hashlib.sha256(pristine).hexdigest()
    with open(mutants_json) as f:
        mutants = json.load(f)
    for idx, m in enumerate(mutants):
        if _sha(path) != pristine_sha:
            raise SystemExit(f"module not pristine before mutant {idx}")
        rec = {"idx": idx, "operator": m["operator"], "occurrence": m["occurrence"]}
        ap = subprocess.run(["cosmic-ray", "apply", path, m["operator"], str(m["occurrence"])],
                            env=ENV, capture_output=True, text=True)
        with open(path, "rb") as f:
            mutated = f.read()
        if ap.returncode != 0 or mutated == pristine:
            rec.update(status="apply_error", detail=(ap.stderr or "")[-300:])
        else:
            rec["mutant_sha256"] = hashlib.sha256(mutated).hexdigest()
            r = run_tests(suite, mode, timeout=float(timeout))
            r.pop("tail", None)
            r["seconds"] = round(r["seconds"], 4)
            rec.update(r)
        with open(path, "wb") as f:
            f.write(pristine)
        print(json.dumps(rec), flush=True)
    if _sha(path) != pristine_sha:
        raise SystemExit("module not pristine after mutants")


MUTMUT_STATUS = {"ok_killed": "killed", "bad_timeout": "timeout", "ok_suspicious": "suspicious",
                 "bad_survived": "survived", "skipped": "skipped", "untested": "untested"}


def cmd_mutmut(module, suite, mode):
    """mutmut 2 cross-check over all of its mutants, same suite command (failfast, kept tests)."""
    path = module_path(module)
    pristine_sha = _sha(path)
    for p in glob.glob(os.path.join(WORK, ".mutmut-cache*")):
        os.remove(p)
    runner = " ".join(([sys.executable, os.path.join(HARNESS, "as_user.py")] if AS_ROOT else []) + test_cmd(suite, mode))
    env = suite_env(suite)
    t0 = time.monotonic()
    p = subprocess.run(["mutmut", "run", "--paths-to-mutate", path, "--tests-dir",
                        os.path.join(WORK, "tests", suite), "--runner", runner, "--no-progress",
                        "--simple-output"],
                       cwd=WORK, env=env, capture_output=True, text=True, timeout=1200)
    secs = time.monotonic() - t0
    if _sha(path) != pristine_sha:
        raise SystemExit("mutmut left the module modified")
    db = os.path.join(WORK, ".mutmut-cache")
    if not os.path.exists(db):
        print(json.dumps({"error": "no .mutmut-cache", "exit_code": p.returncode,
                          "tail": (p.stdout + p.stderr)[-600:]}))
        return
    con = sqlite3.connect(db)
    rows = con.execute("select m.id, l.line_number, m.\"index\", m.status from Mutant m "
                       "join Line l on m.line = l.id order by m.id").fetchall()
    con.close()
    statuses = [MUTMUT_STATUS.get(s, s) for (_, _, _, s) in rows]
    counts = {k: statuses.count(k) for k in sorted(set(MUTMUT_STATUS.values()) | set(statuses))}
    print(json.dumps({"exit_code": p.returncode, "seconds": round(secs, 2), "counts": counts,
                      "mutants": [{"line": ln, "index": ix, "status": MUTMUT_STATUS.get(s, s)}
                                  for (_, ln, ix, s) in rows],
                      "tail": (p.stdout + p.stderr)[-300:]}))


if __name__ == "__main__":
    {"enumerate": cmd_enumerate, "validity": cmd_validity, "baseline": cmd_baseline,
     "coverage": cmd_coverage, "mutants": cmd_mutants, "mutmut": cmd_mutmut}[sys.argv[1]](*sys.argv[2:])
