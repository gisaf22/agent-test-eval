"""Tests for run_full.py without API calls or Docker: the plan, resume, and every hard stop with a
fake trigger. The writer and scorer are replaced by fakes that write meta.json, a ledger line and
a results row into a temporary directory. Usage: .venv/bin/python -m pytest -q test_run_full.py"""
import json
import subprocess
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import run_full

KEY = "sk-test-FAKEKEY-0123456789abcdef"
REAL_ROOT = Path(run_full.__file__).resolve().parent
RUN5 = REAL_ROOT / "runs" / "full" / "B4-full-sonnet55-skijack_ast-s3" / "scoring_log.txt"


def full_row(rid, test_file, **over):
    """A complete scored full row (the fields the B4b rule looks at, plus a few others)."""
    row = {"run_id": rid, "tag": "full", "test_file": test_file, "arm_status": "ran",
           "design_commit": run_full.FROZEN_COMMIT, "scorer_revision": "B3", "harness_version": "A2.1",
           **{k: 0.5 for k in run_full.REQUIRED_SCORES}, "constant_mutants_n": 3, "score_constants": 0.5,
           "coverage": {"line_coverage": 1.0, "branch_coverage": 0.9, "num_branches": 10, "covered_branches": 9}}
    row.update(over)
    return row


def crash_output(root, func="main", exc=None):
    """run 5's saved scoring output, with its paths moved to `root`."""
    text = RUN5.read_text().replace(str(REAL_ROOT), str(root))
    if func != "main":
        text = text.replace(", in main\n", f", in {func}\n")
    if exc:
        text = text.replace("TypeError: unsupported format string passed to NoneType.__format__", exc)
    return text


class Fakes:
    """Configurable fake writer and scorer. by_order[i] overrides the defaults for plan position i."""

    def __init__(self, tmp, by_order=None, cost=0.05, model="claude-sonnet-5-5"):
        self.tmp, self.by_order, self.cost, self.model = tmp, by_order or {}, cost, model
        self.writer_calls, self.scorer_calls = [], []

    def cfg(self, rid):
        order = next(r["order"] for r in self.plan["runs"] if r["run_id"] == rid)
        return {"fail": False, "model": self.model, "cost": self.cost, "leak": False, "touch": None,
                "sleep": 0, "exit": None, "no_meta": False, "crash": None, "rows": None, **self.by_order.get(order, {})}

    def writer(self, entry, env, timeout):
        rid = entry["run_id"]
        self.writer_calls.append(rid)
        assert env.get(run_full.KEY_ENV) == KEY
        c = self.cfg(rid)
        time.sleep(c["sleep"])
        if c["exit"] == 2:
            return SimpleNamespace(returncode=2, stdout="STOP: spend guard", stderr="")
        out = run_full.FULL_DIR / rid
        out.mkdir(parents=True)
        if c["no_meta"]:
            return SimpleNamespace(returncode=1, stdout="crash", stderr="")
        (out / "transcript.jsonl").write_text(KEY if c["leak"] else "{}\n")
        if c["touch"]:
            Path(c["touch"]).write_text("changed")
        meta = {"run_id": rid, "module": entry["module"], "tag": "full",
                "stop": "failed_truncated" if c["fail"] else "writer_done", "estimated_cost": c["cost"],
                "wall_seconds": 1.0, "response_model": c["model"], "suite_files": [] if c["fail"] else ["t.py"]}
        (out / "meta.json").write_text(json.dumps(meta))
        with run_full.LEDGER.open("a") as f:
            f.write(json.dumps({"run_id": rid, "estimated_cost": c["cost"]}) + "\n")
        return SimpleNamespace(returncode=1 if c["fail"] else 0, stdout="ok", stderr="")

    def scorer(self, meta_path, env, timeout):
        assert run_full.KEY_ENV not in env
        meta = json.loads(Path(meta_path).read_text())
        rid = meta["run_id"]
        self.scorer_calls.append(rid)
        c = self.cfg(rid)
        if meta["stop"] == "failed_truncated":
            rows = [{"run_id": rid, "tag": "full", "test_file": "writer", "arm_status": "writer_failed"}]
        elif c["rows"] is not None:
            rows = c["rows"](rid)
        else:
            cov = ({"coverage": {"line_coverage": 1.0, "branch_coverage": None, "num_branches": 0,
                                 "covered_branches": 0}} if c["crash"] else {})
            rows = [full_row(rid, "null_test.py", **cov), full_row(rid, "writer", **cov)]
        with run_full.NULL_STORE.open("a") as f:      # this run scored and stored its null
            f.write(json.dumps({"key": {}, "row": {"run_id": rid}}) + "\n")
        with run_full.RESULTS.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        if c["crash"]:
            return SimpleNamespace(returncode=1, stdout=c["crash"](run_full.ROOT), stderr="")
        status = rows[-1]["arm_status"]
        return SimpleNamespace(returncode=1 if status != "ran" else 0, stdout="GO", stderr="")


class DriverCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        full = tmp / "runs" / "full"
        self.watched = tmp / "watched.py"
        self.watched.write_text("frozen")
        self.patches = [mock.patch.object(run_full, k, v) for k, v in {
            "ROOT": tmp, "PLAN": tmp / "full_plan.json", "RESULTS": tmp / "results.jsonl", "FULL_DIR": full,
            "LEDGER": full / "ledger.jsonl", "PROGRESS": full / "progress.txt", "STOPPED": full / "STOPPED.txt",
            "LOG": full / "log.txt", "OTHER_OUTPUTS": [],
            "COVARIATES": tmp / "covariates.json", "TOLERATED": tmp / "derived" / "b4_tolerated_runs.jsonl",
            "NULL_STORE": tmp / "results_null.jsonl", "PILOT_DIR": tmp / "runs" / "pilot",
            "watched_files": lambda: [self.watched, run_full.PLAN],
            "docker_ok": lambda: True}.items()]
        self.patches.append(mock.patch.object(run_full.run_eval, "null_store_env_check", lambda ident: []))
        for p in self.patches:
            p.start()
        full.mkdir(parents=True)
        run_full.NULL_STORE.write_text("")
        self.plan = run_full.load_or_create_plan()
        self.set_branches({})

    def set_branches(self, by_order):
        """Every plan module has 5 branches, except the modules at the given plan positions."""
        b = {r["module"]: 5 for r in self.plan["runs"]}
        b.update({self.plan["runs"][o - 1]["module"]: n for o, n in by_order.items()})
        run_full.COVARIATES.write_text(json.dumps({"modules": [{"module": m, "branches": n} for m, n in b.items()]}))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self._tmp.cleanup()

    def go(self, fakes, through=None, **kw):
        fakes.plan = self.plan
        with mock.patch.object(run_full, "call_writer", fakes.writer), \
                mock.patch.object(run_full, "call_scorer", fakes.scorer), mock.patch("builtins.print"):
            return run_full.run(self.plan, KEY, through, **kw)

    def stop(self, fakes, through=None, **kw):
        with self.assertRaises(run_full.Stop) as cm:
            self.go(fakes, through, **kw)
        with mock.patch("builtins.print"):
            run_full.stop_file(cm.exception)
        self.assertIn(cm.exception.reason, run_full.STOPPED.read_text())
        return cm.exception


class Plan(DriverCase):
    def test_dry_plan(self):
        p = run_full.build_plan()
        self.assertEqual(p["n_runs"], 117)
        self.assertEqual(Counter(r["set"] for r in p["runs"]), {"primary": 93, "baseline": 24})
        per_module = Counter(r["module"] for r in p["runs"])
        self.assertEqual((len(per_module), set(per_module.values())), (39, {3}))
        self.assertEqual(len({r["run_id"] for r in p["runs"]}), 117)
        self.assertEqual([r["order"] for r in p["runs"]], list(range(1, 118)))
        self.assertEqual(p, run_full.build_plan())                       # seeded, deterministic
        unshuffled = [(m, s) for m, _ in run_full.corpus_modules() for s in run_full.SEEDS]
        self.assertNotEqual([(r["module"], r["seed"]) for r in p["runs"]], unshuffled)
        self.assertTrue(all(r["run_id"] == f"B4-full-sonnet55-{r['module']}-{r['seed']}" for r in p["runs"]))

    def test_saved_plan_is_reloaded_not_rebuilt(self):
        created = json.loads(run_full.PLAN.read_text())["created_at"]
        self.assertEqual(run_full.load_or_create_plan()["created_at"], created)

    def test_tampered_plan_stops(self):
        p = json.loads(run_full.PLAN.read_text())
        p["runs"][0], p["runs"][1] = p["runs"][1], p["runs"][0]
        run_full.PLAN.write_text(json.dumps(p))
        with self.assertRaises(run_full.Stop):
            run_full.load_or_create_plan()


class Resume(DriverCase):
    def test_resume_skips_done_and_keeps_order(self):
        f = Fakes(self)
        self.assertEqual(self.go(f, through=3), 0)
        first = [r["run_id"] for r in self.plan["runs"][:3]]
        self.assertEqual(f.writer_calls, first)
        f2 = Fakes(self)
        self.go(f2, through=5)
        self.assertEqual(f2.writer_calls, [r["run_id"] for r in self.plan["runs"][3:5]])
        prog = run_full.PROGRESS.read_text()
        self.assertIn("runs done 5 of 117", prog)
        self.assertIn(f"last run_id {self.plan['runs'][4]['run_id']}", prog)
        self.assertIn("cumulative spend $0.2500", prog)
        self.assertIn("failed 0", prog)

    def test_meta_without_row_is_scored_without_writer(self):
        f = Fakes(self)
        f.plan = self.plan
        f.writer(self.plan["runs"][0], {run_full.KEY_ENV: KEY}, 1)   # writer ran, scoring never did
        f2 = Fakes(self)
        self.go(f2, through=1)
        self.assertEqual((f2.writer_calls, f2.scorer_calls), ([], [self.plan["runs"][0]["run_id"]]))

    def test_failed_run_is_recorded_and_not_retried(self):
        f = Fakes(self, by_order={1: {"fail": True}})
        self.go(f, through=2)
        f2 = Fakes(self)
        self.go(f2, through=2)
        self.assertEqual(f2.writer_calls, [])
        self.assertIn("failed 1", run_full.PROGRESS.read_text())

    def test_interrupted_writer_dir_stops(self):
        (run_full.FULL_DIR / self.plan["runs"][0]["run_id"]).mkdir()
        self.assertEqual(self.stop(Fakes(self), through=1).code, 3)


class HardStops(DriverCase):
    def test_spend_would_pass_cap(self):
        run_full.LEDGER.write_text(json.dumps({"estimated_cost": 7.95}) + "\n")
        f = Fakes(self)
        self.assertEqual(self.stop(f).code, 2)
        self.assertEqual(f.writer_calls, [])

    def test_writer_spend_guard(self):
        self.assertEqual(self.stop(Fakes(self, by_order={2: {"exit": 2}})).code, 2)

    def test_key_in_output_file(self):
        e = self.stop(Fakes(self, by_order={2: {"leak": True}}))
        self.assertEqual(e.code, 4)
        self.assertNotIn(KEY, e.reason)
        self.assertNotIn(KEY[-12:], run_full.STOPPED.read_text() + run_full.LOG.read_text())

    def test_response_model_change(self):
        e = self.stop(Fakes(self, by_order={3: {"model": "claude-sonnet-5-5-other"}}))
        self.assertEqual(e.code, 7)
        self.assertIn(self.plan["runs"][2]["run_id"], e.reason)

    def test_more_than_5_of_first_10_failed(self):
        f = Fakes(self, by_order={i: {"fail": True} for i in range(1, 11)})
        self.assertEqual(self.stop(f).code, 5)
        self.assertEqual(len(f.writer_calls), 6)

    def test_more_than_10_percent_after_20(self):
        f = Fakes(self, by_order={i: {"fail": True} for i in (11, 12, 13)})
        e = self.stop(f)
        self.assertEqual((e.code, len(f.writer_calls)), (5, 20))   # 3 of 13 earlier was not checked

    def test_10_percent_exactly_does_not_stop(self):
        f = Fakes(self, by_order={i: {"fail": True} for i in (11, 12)})
        self.assertEqual(self.go(f, through=25), 0)

    def test_run_over_time_limit(self):
        with mock.patch.object(run_full, "RUN_LIMIT_S", 0.05):
            self.assertEqual(self.stop(Fakes(self, by_order={1: {"sleep": 0.1}})).code, 6)

    def test_writer_timeout(self):
        def hang(*a, **k):
            raise subprocess.TimeoutExpired("writer", 1)
        with mock.patch.object(run_full, "call_writer", hang), mock.patch("builtins.print"), \
                self.assertRaises(run_full.Stop) as cm:
            run_full.run(self.plan, KEY)
        self.assertEqual(cm.exception.code, 6)

    def test_file_changed_mid_run(self):
        e = self.stop(Fakes(self, by_order={2: {"touch": str(self.watched)}}))
        self.assertEqual(e.code, 8)

    def test_writer_without_meta(self):
        self.assertEqual(self.stop(Fakes(self, by_order={1: {"no_meta": True}})).code, 3)

    def test_docker_down(self):
        with mock.patch.object(run_full, "docker_ok", lambda: False):
            self.assertEqual(self.stop(Fakes(self)).code, 3)

    def test_preflight_refuses_after_a_stop(self):
        run_full.STOPPED.write_text("earlier stop")
        with self.assertRaises(run_full.Stop):
            run_full.preflight(KEY)


class BranchlessSummaryCrash(DriverCase):
    """B4b: scoring exit 1 is tolerated only for the exact run-5 summary crash on a branchless module
    whose rows are complete. Every variant stops."""

    def crash(self, **kw):
        return {"crash": lambda root: crash_output(root, **kw)}

    def test_tolerated(self):
        self.set_branches({2: 0})
        f = Fakes(self, by_order={2: self.crash()})
        self.assertEqual(self.go(f, through=3), 0)
        self.assertEqual(len(f.writer_calls), 3)
        rid = self.plan["runs"][1]["run_id"]
        rec = [json.loads(l) for l in run_full.TOLERATED.read_text().splitlines()]
        self.assertEqual([(r["run_id"], r["rows"]) for r in rec], [(rid, ["null_test.py", "writer"])])
        self.assertIn(f"tolerated scoring exits (B4b, b4_tolerated_runs.jsonl): 1 ({rid})", run_full.PROGRESS.read_text())
        self.go(Fakes(self), through=3)                          # resume: recorded once, not re-checked
        self.assertEqual(len(run_full.TOLERATED.read_text().splitlines()), 1)

    def test_module_with_branches_stops(self):
        e = self.stop(Fakes(self, by_order={2: self.crash()}))
        self.assertEqual(e.code, 3)
        self.assertIn("has 5 branches", e.reason)
        self.assertFalse(run_full.TOLERATED.exists())

    def test_other_function_stops(self):
        self.set_branches({2: 0})
        e = self.stop(Fakes(self, by_order={2: self.crash(func="evaluate_module")}))
        self.assertIn("traceback is not the summary-print crash", e.reason)

    def test_other_exception_stops(self):
        self.set_branches({2: 0})
        e = self.stop(Fakes(self, by_order={2: self.crash(exc="ValueError: unsupported format string passed to NoneType.__format__")}))
        self.assertIn("traceback is not the summary-print crash", e.reason)

    def test_extra_output_after_traceback_stops(self):
        self.set_branches({2: 0})
        f = Fakes(self, by_order={2: {"crash": lambda root: crash_output(root) + "NO-GO\n"}})
        self.assertIn("traceback is not", self.stop(f).reason)

    def test_missing_row_stops(self):
        self.set_branches({2: 0})
        cov = {"coverage": {"branch_coverage": None, "num_branches": 0}}
        f = Fakes(self, by_order={2: {**self.crash(), "rows": lambda rid: [full_row(rid, "writer", **cov)]}})
        self.assertIn("!= expected ['null_test.py', 'writer']", self.stop(f).reason)

    def test_null_score_field_stops(self):
        self.set_branches({2: 0})
        cov = {"coverage": {"branch_coverage": None, "num_branches": 0}}
        f = Fakes(self, by_order={2: {**self.crash(), "rows": lambda rid: [
            full_row(rid, "null_test.py", **cov), full_row(rid, "writer", mutation_score=None, **cov)]}})
        self.assertIn("writer: null score fields ['mutation_score']", self.stop(f).reason)

    def test_branch_coverage_zero_not_null_stops(self):
        self.set_branches({2: 0})
        cov = {"coverage": {"branch_coverage": 0, "num_branches": 0}}
        f = Fakes(self, by_order={2: {**self.crash(), "rows": lambda rid: [
            full_row(rid, "null_test.py", **cov), full_row(rid, "writer", **cov)]}})
        self.assertIn("branch coverage not recorded as null", self.stop(f).reason)

    def test_missing_field_stops(self):
        self.set_branches({2: 0})
        def rows(rid):
            w = full_row(rid, "writer", coverage={"branch_coverage": None, "num_branches": 0})
            del w["killed"]
            return [full_row(rid, "null_test.py", coverage=w["coverage"]), w]
        e = self.stop(Fakes(self, by_order={2: {**self.crash(), "rows": rows}}))
        self.assertIn("writer: field set differs", e.reason)

    def test_unrecorded_nonzero_exit_is_checked_on_resume(self):
        self.set_branches({1: 5})
        f = Fakes(self, by_order={1: self.crash()})
        with self.assertRaises(run_full.Stop):
            self.go(f, through=1)
        with self.assertRaises(run_full.Stop) as cm:             # restart: the stored exit 1 stops again
            self.go(Fakes(self), through=2)
        self.assertIn("has 5 branches", cm.exception.reason)


WAVE1 = {"primary": ["trace2task_experience", "role_aware_financial_age_sanitize", "wtftd_war_thunder_full_t_minimap",
                     "skijack_ast", "intent_relations", "blackmamba_open_source_r_vision", "trace2task_experience_runtime"],
         "baseline": ["toposort", "databroker_pivot", "moirai_abstract_process_handler", "heapdict", "addict",
                      "depthcharge_log", "mergedeep"]}


class Waves(DriverCase):
    """B4c: wave filter, resume across waves, the spend cap and the refuse-to-start check."""

    def wave1_ids(self):
        return [r["run_id"] for r in self.plan["runs"] if r["module"] in WAVE1["primary"] + WAVE1["baseline"]]

    def test_wave1_draw_is_the_recorded_one(self):
        self.assertEqual(run_full.wave1_modules(), WAVE1)
        runs = run_full.wave_runs(self.plan, "1")
        self.assertEqual((len(runs), Counter(r["set"] for r in runs)), (42, {"primary": 21, "baseline": 21}))
        self.assertEqual(run_full.wave_runs(self.plan, "all"), self.plan["runs"])

    def test_wave1_runs_only_wave1_in_plan_order(self):
        f = Fakes(self, cost=0.01)
        self.assertEqual(self.go(f, wave="1"), 0)
        self.assertEqual(f.writer_calls, self.wave1_ids())

    def test_resume_wave1_then_all(self):
        ids = self.wave1_ids()
        f = Fakes(self, cost=0.01)
        self.go(f, through=self.plan["runs"][[r["run_id"] for r in self.plan["runs"]].index(ids[4])]["order"], wave="1")
        self.assertEqual(f.writer_calls, ids[:5])
        f2 = Fakes(self, cost=0.01)
        self.go(f2, wave="1")                                    # resume: only the wave-1 runs not done
        self.assertEqual(f2.writer_calls, ids[5:])
        f3 = Fakes(self, cost=0.01)
        self.go(f3, wave="all")                                  # wave 2 = every remaining planned run
        self.assertEqual(f3.writer_calls, [r["run_id"] for r in self.plan["runs"] if r["run_id"] not in ids])
        f4 = Fakes(self)
        self.go(f4)
        self.assertEqual(f4.writer_calls, [])

    def test_spend_cap_counts_earlier_spend_and_stops_before_writer(self):
        run_full.LEDGER.write_text(json.dumps({"estimated_cost": 3.10}) + "\n")   # e.g. the checkpoint
        f = Fakes(self)
        e = self.stop(f, wave="1", cap=3.15)
        self.assertEqual((e.code, f.writer_calls), (2, []))
        self.assertIn("would pass $3.15", e.reason)

    def test_spend_cap_stops_mid_wave(self):
        f = Fakes(self, cost=0.5)
        e = self.stop(f, wave="1", cap=1.2)                      # 0 + 0.122 ok, 0.5 + 0.5 ok, 1.0 + 0.5 > 1.2
        self.assertEqual((e.code, f.writer_calls), (2, self.wave1_ids()[:2]))

    def test_spend_cap_passed_after_a_run_stops(self):
        f = Fakes(self, cost=1.5)
        e = self.stop(f, cap=1.2)
        self.assertEqual((e.code, len(f.writer_calls)), (2, 1))
        self.assertIn("passed $1.20", e.reason)

    def test_outer_guard_stays(self):
        run_full.LEDGER.write_text(json.dumps({"estimated_cost": 7.95}) + "\n")
        f = Fakes(self)
        self.assertEqual(self.stop(f, cap=20.0).code, 2)
        self.assertEqual(f.writer_calls, [])

    def pilot_meta(self, module, cost):
        d = run_full.PILOT_DIR / f"B2c-pilot-sonnet55-{module}-s{len(list(run_full.PILOT_DIR.glob(f'*-{module}-s*'))) + 1}"
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"module": module, "estimated_cost": cost}))

    def test_estimate_uses_module_cost_else_mean(self):
        self.pilot_meta("toposort", 0.10)
        self.pilot_meta("toposort", 0.20)
        self.pilot_meta("not_in_wave1", 0.03)
        runs = run_full.wave_runs(self.plan, "1")
        est, todo, fallback = run_full.estimate_remaining(runs, {})
        self.assertAlmostEqual(fallback, 0.11)                   # mean over all 3 known runs
        self.assertAlmostEqual(est, 3 * 0.15 + 39 * 0.11)        # toposort's own mean, others the mean
        self.assertEqual(len(todo), 42)
        done = {runs[0]["run_id"]: {"arm_status": "ran"}}
        self.assertEqual(len(run_full.estimate_remaining(runs, done)[1]), 41)

    def test_refuses_to_start_over_cap(self):
        self.pilot_meta("toposort", 0.05)
        run_full.LEDGER.write_text(json.dumps({"estimated_cost": 1.0}) + "\n")
        lines = run_full.start_check(self.plan, "1", 3.15)       # 1.0 + 42 * 0.05 = 3.10
        self.assertIn("wave 1: 42 runs, 0 completed, 42 remaining", "\n".join(lines))
        self.assertIn(", ".join(WAVE1["primary"]), lines[0])
        with self.assertRaises(run_full.Refuse):
            run_full.start_check(self.plan, "1", 3.05)
        with self.assertRaises(run_full.Refuse):
            run_full.start_check(self.plan, "all", 3.15)         # 1.0 + 117 * 0.05

    def test_main_refusal_writes_no_stop_file_and_calls_no_writer(self):
        self.pilot_meta("toposort", 0.05)
        f = Fakes(self)
        with mock.patch.object(run_full, "preflight", lambda key: []), \
                mock.patch.object(run_full, "call_writer", f.writer), mock.patch("builtins.print"), \
                mock.patch("sys.argv", ["run_full.py", "--wave", "all", "--spend-cap", "3.15"]):
            self.assertEqual(run_full.main(), 2)
        self.assertEqual(f.writer_calls, [])
        self.assertFalse(run_full.STOPPED.exists())
        self.assertIn("REFUSED", run_full.LOG.read_text())


class Run5(unittest.TestCase):
    def test_saved_run5_output_is_the_reference_traceback(self):
        self.assertEqual(run_full.parse_traceback(RUN5.read_text()), run_full.SUMMARY_CRASH)


class Preflight(unittest.TestCase):
    def test_frozen_files_match_tag(self):
        self.assertEqual(run_full.frozen_mismatches(), [])

    def test_container_filter_is_project_only(self):
        out = "\n".join(["ate-toposort-1234abcd\tagent-test-eval-sandbox:a2",
                         "ate-toposort-1234abcd-x\tagent-test-eval-sandbox:a2",
                         "ate-toposort-5678abcd\tsome-other:image",
                         "ate-notamodule-1234abcd\tagent-test-eval-sandbox:a2",
                         "other_project\tpostgres"])
        with mock.patch.object(run_full.subprocess, "run", return_value=SimpleNamespace(stdout=out)):
            self.assertEqual(run_full.project_containers(["toposort", "addict"]), ["ate-toposort-1234abcd"])


if __name__ == "__main__":
    unittest.main()
