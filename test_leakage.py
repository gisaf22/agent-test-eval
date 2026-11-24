"""Leakage audit (Stage B3). Needs Docker; skipped without it. No model API calls.

Writer-loop sandbox (writer.run_in_sandbox, the path every writer iteration uses):
  * canary files are planted where mutants, reference tests, upstream tests, other runs' outputs
    and results live on the host (and in the image build context), a canary key is put in the
    host environment under the key's variable names, and a scoring container holding a canary
    mutant list runs at the same time;
  * a probe test walks the sandbox filesystem and environment and must find no canary, no key,
    no file except the module and its own test file, and nothing left by an earlier iteration;
    it must run non-root and have no network.
Scoring sandbox (run_eval.Sandbox(scoring=True) + runner.py, the path every scored suite uses):
  * the test process is not root, cannot write, chmod, rename or shadow the module, the harness or
    the suites, cannot read the mutant list or cosmic-ray's session, and sees no state from an
    earlier run.
Stored nulls: every results_null.jsonl row carries the current env_id (otherwise it is flagged).

Run: .venv/bin/python -m unittest test_leakage -v
"""
import json
import os
import shutil
import subprocess
import unittest
import uuid
from pathlib import Path

import run_eval
import writer

ROOT = Path(__file__).resolve().parent
MODULE = "toposort"


def docker_ok():
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


WRITER_PROBE = r'''
import json, os, socket

TOKEN = "{token}"
MODULE = "{module}"
SKIP = ("/proc", "/sys", "/dev")


def test_probe():
    findings = []
    me = os.path.abspath(__file__)
    scanned, scanned_bytes = 0, 0
    for root, dirs, files in os.walk("/", onerror=lambda e: None):
        if root.startswith(SKIP) and not root.startswith("/dev/shm"):
            dirs[:] = []
            continue
        for f in files:
            p = os.path.join(root, f)
            if p == me or os.path.islink(p):
                continue
            if TOKEN in f:
                findings.append("canary file name: " + p)
            try:
                if os.path.getsize(p) <= 5_000_000:
                    with open(p, "rb") as fh:
                        data = fh.read()
                    scanned, scanned_bytes = scanned + 1, scanned_bytes + len(data)
                    if TOKEN.encode() in data or b"sk-ant-" in data:
                        findings.append("canary or key bytes in " + p)
            except OSError:
                pass
    env_blobs = [json.dumps(dict(os.environ))]
    for p in ("/proc/self/environ", "/proc/1/environ"):
        try:
            env_blobs.append(open(p, "rb").read().decode("utf-8", "replace"))
        except OSError:
            pass
    for blob in env_blobs:
        if TOKEN in blob or "sk-ant-" in blob or "API_KEY" in blob:
            findings.append("key or canary in the environment")
    if scanned < 1000 or scanned_bytes < 10_000_000:   # the walk must really cover the image
        findings.append("scan too small: %d files, %d bytes" % (scanned, scanned_bytes))
    work = sorted(os.path.relpath(os.path.join(r, f), "/work") for r, _, fs in os.walk("/work") for f in fs)
    if work != sorted(["src/%s.py" % MODULE, "tests/test_probe.py"]):
        findings.append("unexpected files in /work: %r" % work)
    left = [e for d in ("/tmp", "/dev/shm") for e in os.listdir(d)]
    if left:
        findings.append("files left in /tmp or /dev/shm at test start: %r" % left)
    if os.getuid() == 0:
        findings.append("tests run as root")
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2).close()
        findings.append("network reachable")
    except OSError:
        pass
    for p in ("/tmp/ate_marker_" + TOKEN, "/work/ate_marker_" + TOKEN, "/dev/shm/ate_marker_" + TOKEN):
        try:
            open(p, "w").write("x")       # the next iteration must not see these
        except OSError:
            pass
    print("FINDINGS " + json.dumps(findings))
    assert findings == [], findings
'''

SCORING_PROBE = r'''
import json, os

MODULE = "{module}"


def test_privileges():
    f = []
    m = "/work/src/%s.py" % MODULE
    if os.getuid() == 0 or os.geteuid() == 0:
        f.append("tests run as root")
    if os.access(m, os.W_OK):
        f.append("module writable (access)")
    attempts = [("append to module", lambda: open(m, "a")), ("chmod module", lambda: os.chmod(m, 0o666)),
                ("create file in src", lambda: open("/work/src/shadow.py", "w")),
                ("rename module", lambda: os.rename(m, m + ".x")),
                ("write harness", lambda: open("/work/harness/runner.py", "a")),
                ("write own suite", lambda: open(__file__, "a")),
                ("read mutant list", lambda: open("/work/ctl/mutants.json", "rb").read()),
                ("read cosmic-ray session", lambda: open("/work/ctl/cr_session.sqlite", "rb").read()),
                ("list /work/ctl", lambda: os.listdir("/work/ctl"))]
    for name, fn in attempts:
        try:
            fn()
            f.append(name + " allowed")
        except OSError:
            pass
    for d in ("/tmp", "/dev/shm", "/work/xchg"):
        if os.path.exists(os.path.join(d, "ate_marker")):
            f.append("state from an earlier run in " + d)
        try:
            open(os.path.join(d, "ate_marker"), "w").write("x")
        except OSError:
            pass
    stray = [e for e in os.listdir("/tmp") if e.startswith("cr")]
    if stray:
        f.append("cosmic-ray files in /tmp: %r" % stray)
    print("FINDINGS " + json.dumps(f))
    assert f == [], f
'''


@unittest.skipUnless(docker_ok(), "Docker not available")
class LeakageAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ident = run_eval.build_and_verify_image()

    def test_writer_loop_sandbox_sees_no_canary_key_or_earlier_state(self):
        token = "canary" + uuid.uuid4().hex
        planted = [ROOT / "tests" / MODULE / f"zz_{token}_reference_test.py",
                   ROOT / "corpus" / MODULE / f"zz_{token}_upstream_test.txt",
                   ROOT / f"zz_{token}_results.jsonl", ROOT / f"zz_{token}_mutants.json",
                   ROOT / "sandbox" / f"zz_{token}.txt"]
        run_dir = ROOT / "runs" / f"zz_{token}"
        planted_run = [run_dir / "r1" / "suite" / "test_other_run.py", run_dir / "r1" / "meta.json",
                       run_dir / "r1" / "transcript.jsonl"]
        saved_env = {k: os.environ.get(k) for k in ("AGENT_EVAL_API_KEY", "ANTHROPIC_API_KEY")}
        try:
            for p in planted + planted_run:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(f"{token}\n")
            for k in saved_env:
                os.environ[k] = f"sk-ant-{token}"
            probe = {"tests/test_probe.py": WRITER_PROBE.replace("{token}", token).replace("{module}", MODULE)}
            src = run_eval.module_meta(MODULE)["module_path"]
            with run_eval.Sandbox(MODULE, scoring=True) as other:     # a scoring container running alongside
                other.put({"ctl/mutants.json": f'[{{"canary": "{token}"}}]'.encode()})
                results = [writer.run_in_sandbox(MODULE, src, probe) for _ in range(2)]
        finally:
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            for p in planted + planted_run:
                p.unlink(missing_ok=True)
            if run_dir.exists():
                shutil.rmtree(run_dir)       # only the directory this test created
        for i, r in enumerate(results, 1):
            with self.subTest(iteration=i):
                self.assertEqual(r["exit_code"], 0, r["output"][-3000:])
                self.assertIn("1 passed", r["output"])
        # positive control: the same probe must fail when a canary does reach the sandbox
        leak = {**probe, "tests/zz_leak.txt": f"{token}\n"}
        r = writer.run_in_sandbox(MODULE, src, leak)
        self.assertNotEqual(r["exit_code"], 0)
        self.assertIn("canary", r["output"])

    def test_scoring_sandbox_protects_module_and_mutants(self):
        src = run_eval.module_meta(MODULE)["module_path"]
        with run_eval.Sandbox(MODULE, scoring=True) as sb:
            files = {f"src/{MODULE}.py": src,
                     **{f"harness/{h}": run_eval.SANDBOX / h for h in run_eval.HARNESS_FILES},
                     "tests/probe/test_probe.py": SCORING_PROBE.replace("{module}", MODULE).encode()}
            sb.put(files)
            json.loads(sb.exec("python", "/work/harness/runner.py", "enumerate", MODULE))
            sb.put({"ctl/mutants.json": b"[]"})
            base = json.loads(sb.exec("python", "/work/harness/runner.py", "baseline", MODULE, "probe", "pytest", "3"))
            owner = sb.exec("stat", "-c", "%U %a", f"/work/src/{MODULE}.py").strip()
        self.assertEqual(owner, "root 644")
        for i, b in enumerate(base, 1):
            with self.subTest(run=i):
                self.assertEqual(b["exit_code"], 0, b["tail"])

    def test_stored_nulls_carry_the_current_env_id(self):
        self.assertEqual(run_eval.null_store_env_check(self.ident), [])


if __name__ == "__main__":
    unittest.main()
