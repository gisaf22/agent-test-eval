"""The analysis input rule (B3): only tag full + design_commit == prereg-v1 commit reaches the analysis.

Run: .venv/bin/python -m unittest test_analysis -v
"""
import json
import tempfile
import unittest
from pathlib import Path

import analysis
import run_eval

COMMIT = "a" * 40


def row(**kw):
    base = {"run_id": "r1", "module": "toposort", "test_file": "writer", "tag": "full",
            "design_commit": COMMIT, "scorer_revision": "B3"}
    return {**base, **kw}


NOT_ALLOWED = {
    "pilot": row(tag="pilot"), "dry_run": row(tag="dry_run"), "untagged reference": row(tag=None),
    "no tag field": {k: v for k, v in row().items() if k != "tag"},
    "other commit": row(design_commit="b" * 40), "no design_commit": row(design_commit=None),
    "older scorer": row(scorer_revision=None), "haiku arm": row(tag="haiku_arm"),
}


class AnalysisInput(unittest.TestCase):
    def test_only_allowlisted_rows_are_selected(self):
        rows = [row()] + [dict(r, run_id=f"x{i}") for i, r in enumerate(NOT_ALLOWED.values())]
        self.assertEqual(analysis.select_rows(rows, COMMIT), [row()])

    def test_a_non_allowed_row_that_reaches_the_analysis_fails(self):
        for name, r in NOT_ALLOWED.items():
            with self.subTest(row=name), self.assertRaises(analysis.NotAllowedRow):
                analysis.check_rows([row(), r], COMMIT)

    def test_no_prereg_commit_selects_nothing(self):
        self.assertEqual(analysis.select_rows([row()], None), [])

    def test_duplicates_stop_the_load(self):
        with self.assertRaises(analysis.NotAllowedRow):
            analysis.select_rows([row(), row()], COMMIT)

    def test_loader_on_a_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "results.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in [row(), *NOT_ALLOWED.values()]) + "\n")
            self.assertEqual(analysis.load_analysis_rows(p, COMMIT), [row()])

    def test_no_existing_row_is_allowlisted(self):
        """Every row recorded before the freeze (dry run, pilot, Stage 0, B3 checks) is excluded."""
        rows = [json.loads(l) for l in run_eval.RESULTS.read_text().splitlines() if l.strip()]
        commit = run_eval.prereg_commit()
        self.assertEqual([r["run_id"] for r in analysis.select_rows(rows, commit or COMMIT)
                          if r.get("tag") != "full"], [])



# ---------------------------------------------------------------- B5: the analysis on top of the loader
def real_rows():
    return [json.loads(l) for l in run_eval.RESULTS.read_text().splitlines() if l.strip()]


class B5Allowlist(unittest.TestCase):
    def test_synthetic_rows(self):
        good = row(run_id="g", module="toposort", test_file="writer")
        bad = [row(run_id="t", tag="pilot"), row(run_id="c", design_commit="b" * 40),
               row(run_id="s", scorer_revision=None)]
        null = row(run_id="g", module="toposort", test_file="null_test.py")
        self.assertEqual(analysis.writer_rows(analysis.select_rows([good, null, *bad], COMMIT)), [good])

    def test_real_file_includes_checkpoint_rows_and_only_full_writer_rows(self):
        rows = analysis.writer_rows(analysis.select_rows(real_rows(), analysis.prereg_commit()))
        ids = {r["run_id"] for r in rows}
        for rid in ("B4-full-sonnet55-addict-s2", "B4-full-sonnet55-skijack_ast-s3"):
            self.assertIn(rid, ids)
        self.assertTrue(all(r["tag"] == "full" and r["test_file"] == "writer" for r in rows))
        self.assertGreaterEqual(len(rows), 42)

    def test_every_writer_module_has_a_set(self):
        sets = analysis.corpus_sets()
        rows = analysis.writer_rows(analysis.select_rows(real_rows(), analysis.prereg_commit()))
        self.assertEqual({r["module"] for r in rows} - set(sets), set())


class B5LogicRecompute(unittest.TestCase):
    def test_stored_logic_score_equals_recomputed_for_every_full_run(self):
        rows = analysis.writer_rows(analysis.select_rows(real_rows(), analysis.prereg_commit()))
        keys = [(r["run_id"], r["module"], r["test_file"]) for r in rows]
        muts = analysis.load_mutants(keys)
        self.assertGreaterEqual(len(rows), 42)
        for r, k in zip(rows, keys):
            with self.subTest(run=r["run_id"]):
                self.assertEqual(len(muts[k]), r["mutants_used"] + r["apply_errors"])
                self.assertEqual(analysis.logic_from_mutants(muts[k]), (r["score_logic"], r["logic_mutants_n"]))

    def test_pilot_recompute_matches_b3_backfill(self):
        """The drift table recomputes pilot logic scores; they must equal derive_b3's backfill."""
        back = [json.loads(l) for l in (run_eval.ROOT / "derived/b3_pilot_runs.jsonl").read_text().splitlines() if l.strip()]
        pilot = [r for r in real_rows() if r.get("tag") == "pilot" and r.get("test_file") == "writer"]
        muts = analysis.load_mutants([(r["run_id"], r["module"], r["test_file"]) for r in pilot])
        stored = {b["run_id"]: b["score_logic"] for b in back}
        self.assertEqual(len(pilot), 30)
        for r in pilot:
            self.assertEqual(analysis.logic_from_mutants(muts[(r["run_id"], r["module"], "writer")])[0],
                             stored[r["run_id"]])

    def test_constants_and_apply_errors_are_left_out(self):
        recs = [{"operator": "core/NumberReplacer", "status": "survived"},
                {"operator": "core/AddNot", "status": "killed"},
                {"operator": "core/AddNot", "status": "timeout"},
                {"operator": "core/AddNot", "status": "survived"},
                {"operator": "core/AddNot", "status": "apply_error"}]
        self.assertEqual(analysis.logic_from_mutants(recs), (0.6667, 3))


class B5Bootstrap(unittest.TestCase):
    VALS = [0.54, 0.72, 0.85, 0.86, 0.95, 1.0, 0.38]

    def test_fixed_seed_is_deterministic_and_order_independent(self):
        a = analysis.bootstrap(self.VALS)
        analysis.bootstrap([0.1, 0.2])               # an unrelated call in between
        self.assertEqual(analysis.bootstrap(self.VALS), a)
        self.assertEqual(analysis.BOOT_SEED, 20261117)
        self.assertEqual(analysis.BOOT_N, 10_000)

    def test_input_order_does_not_matter(self):
        self.assertEqual(analysis.bootstrap(list(reversed(self.VALS))), analysis.bootstrap(self.VALS))

    def test_full_output_is_identical_across_hash_seeds(self):
        import os
        import subprocess
        import sys
        outs = {subprocess.run([sys.executable, str(run_eval.ROOT / "analysis.py")], capture_output=True, text=True,
                               check=True, env={**os.environ, "PYTHONHASHSEED": h}).stdout for h in ("0", "1", "12345")}
        self.assertEqual(len(outs), 1)

    def test_other_seed_differs_and_intervals_bracket_the_estimate(self):
        (lo, hi), (mlo, mhi) = analysis.bootstrap(self.VALS)
        self.assertNotEqual(analysis.bootstrap(self.VALS, seed=1), ((lo, hi), (mlo, mhi)))
        self.assertTrue(min(self.VALS) <= lo <= sum(self.VALS) / 7 <= hi <= max(self.VALS))
        self.assertTrue(mlo <= 0.85 <= mhi)

    def test_constant_values_give_a_point_interval(self):
        self.assertEqual(analysis.bootstrap([0.5] * 4, n=50), ((0.5, 0.5), (0.5, 0.5)))


class B5HandExample(unittest.TestCase):
    def test_mean_median_range(self):
        rows = [{"module": m, "x": v} for m, vs in
                {"a": [0.5, 0.7, 0.9], "b": [0.2, 0.4, 0.3], "c": [0.5, None, 0.5]}.items() for v in vs]
        pm = analysis.per_module(rows, analysis.field("x"))
        self.assertAlmostEqual(pm["a"]["mean"], 0.7)
        self.assertAlmostEqual(pm["a"]["range"], 0.4)
        self.assertAlmostEqual(pm["b"]["mean"], 0.3)
        self.assertAlmostEqual(pm["b"]["range"], 0.2)
        self.assertEqual((pm["c"]["n"], pm["c"]["mean"], pm["c"]["range"]), (2, 0.5, 0.0))   # None skipped
        s = analysis.summarize([pm[m]["mean"] for m in "abc"])
        self.assertEqual(s["n"], 3)
        self.assertAlmostEqual(s["mean"], 0.5)           # (0.7 + 0.3 + 0.5) / 3
        self.assertAlmostEqual(s["median"], 0.5)         # middle of 0.3, 0.5, 0.7

    def test_quantile_interpolates(self):
        self.assertAlmostEqual(analysis.quantile([0.0, 1.0, 2.0, 3.0], 0.5), 1.5)
        self.assertAlmostEqual(analysis.quantile([0.0, 1.0, 2.0, 3.0], 0.025), 0.075)
        self.assertEqual(analysis.quantile([4.0], 0.975), 4.0)



class B5bCompleteness(unittest.TestCase):
    """B5b: only modules with all their planned runs (full_plan.json) enter across-module statistics."""

    def plan_file(self, d, runs):
        p = Path(d) / "full_plan.json"
        p.write_text(json.dumps({"runs": [{"run_id": f"R-{m}-s{i}", "module": m} for m, n in runs.items()
                                          for i in range(1, n + 1)]}))
        return p

    def test_partial_module_is_kept_out_of_statistics_but_listed(self):
        with tempfile.TemporaryDirectory() as d:
            planned = analysis.planned_runs(self.plan_file(d, {"toposort": 3, "mergedeep": 3}))
        rows = ([row(run_id=f"R-toposort-s{i}", module="toposort", arm_status="ran", score_logic=0.5 + i / 10,
                     mutation_score=0.5, score_constants=None, writer_stop="writer_done") for i in (1, 2, 3)]
                + [row(run_id="R-mergedeep-s2", module="mergedeep", arm_status="ran", score_logic=0.99,
                       mutation_score=0.9, score_constants=0.5, writer_stop="writer_done")])
        complete, partial = analysis.split_complete(rows, planned)
        self.assertEqual({r["module"] for r in complete}, {"toposort"})
        self.assertEqual([r["run_id"] for r in partial], ["R-mergedeep-s2"])
        pm = analysis.per_module(analysis.scored(complete), analysis.field("score_logic"))
        self.assertNotIn("mergedeep", pm)
        self.assertAlmostEqual(analysis.summarize([v["mean"] for v in pm.values()])["mean"], 0.7)
        table = "\n".join(analysis.partial_table(partial, planned, analysis.corpus_sets()))
        self.assertIn("mergedeep", table)
        self.assertIn("0.9900", table)
        self.assertIn("1 of 3 planned runs present", table)
        self.assertIn("missing s1, s3", table)

    def test_real_output_keeps_partial_modules_out_of_statistics(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            analysis.main()
        out = buf.getvalue()
        stats, partial = out.split("PARTIAL MODULES (descriptive, not in across-module statistics)")
        stats = stats.split("DRIFT CHECK")[0]     # the drift table is per module and marks partial modules
        partial = partial.split("UPSTREAM COMPARISON")[0]
        for m in ("ai_video_generator_safety", "blackmamba_open_source_r_power_estimator", "hangzhou_mahjong_ai_value",
                  "synaptiq_retrieval", "wtftd_war_thunder_full_t_blk", "zagentic_ir_schema"):
            with self.subTest(module=m):
                self.assertNotIn(m, stats.split("COMPLETENESS RULE")[1])
                self.assertIn(m, partial)
        self.assertIn("excluded for incompleteness: 6 modules", out)
        self.assertIn("logic score (headline)                       primary  n= 7", out)
        self.assertIn("logic score (headline)                       baseline n= 7", out)

    def test_planned_count_comes_from_full_plan_json(self):
        rows = [row(run_id=f"R-toposort-s{i}", module="toposort") for i in (1, 2)]
        with tempfile.TemporaryDirectory() as d:
            two = analysis.planned_runs(self.plan_file(d, {"toposort": 2}))
            three = analysis.planned_runs(self.plan_file(d, {"toposort": 3}))
        self.assertEqual(len(analysis.split_complete(rows, two)[0]), 2)      # 2 of 2 planned: complete
        self.assertEqual(len(analysis.split_complete(rows, three)[0]), 0)    # 2 of 3 planned: partial
        plan = json.loads((run_eval.ROOT / "full_plan.json").read_text())
        real = analysis.planned_runs()
        self.assertEqual(analysis.PLAN, run_eval.ROOT / "full_plan.json")
        self.assertEqual(sum(map(len, real.values())), plan["n_runs"])
        self.assertEqual(real, {m: {r["run_id"] for r in plan["runs"] if r["module"] == m} for m in real})


class B6aAssertionKillCorrected(unittest.TestCase):
    def test_hand_example(self):
        """7 used mutants (1 apply error excluded), 2 of them null-killed, 3 assertion kills of which 1 is
        null-killed. Stored rule: 3 / (7 - 2) = 0.6. Corrected: 2 / 5 = 0.4."""
        m = lambda status, kind=None, triv=False: {"status": status, "kill_kind": kind, "trivially_killed": triv}
        recs = [m("killed", "assertion", True), m("killed", "collection_error", True),
                m("killed", "assertion"), m("killed", "assertion"), m("killed", "test_exception"),
                m("survived"), m("timeout"), m("apply_error")]
        self.assertEqual(analysis.assertion_kill_nontrivial_corrected(recs), 0.4)
        used = [r for r in recs if r["status"] != "apply_error"]   # the stored (frozen) rule, for contrast
        stored = run_eval.ratio(sum(r["kill_kind"] == "assertion" for r in used),
                                len(used) - sum(r["trivially_killed"] for r in used))
        self.assertEqual(stored, 0.6)

    def test_all_null_killed_gives_zero_like_run_eval_ratio(self):
        recs = [{"status": "killed", "kill_kind": "collection_error", "trivially_killed": True}]
        self.assertEqual(analysis.assertion_kill_nontrivial_corrected(recs), 0.0)

    def test_real_runs_match_stored_when_no_null_killed_mutant_dies_by_assertion(self):
        rows = analysis.scored(analysis.writer_rows(analysis.select_rows(real_rows(), analysis.prereg_commit())))
        muts = analysis.load_mutants([(r["run_id"], r["module"], r["test_file"]) for r in rows])
        for r in rows:
            recs = muts[(r["run_id"], r["module"], r["test_file"])]
            if not any(x["trivially_killed"] and x.get("kill_kind") == "assertion" for x in recs):
                with self.subTest(run=r["run_id"]):
                    self.assertEqual(analysis.assertion_kill_nontrivial_corrected(recs),
                                     r["assertion_kill_rate_nontrivial"])


class WrapUpPreregFallback(unittest.TestCase):
    """Without git history (a published copy) there is no prereg-v1 tag; analysis uses the recorded hash."""
    def call(self, tag):
        import contextlib
        import io
        from unittest import mock
        err = io.StringIO()
        with mock.patch.object(run_eval, "prereg_commit", return_value=tag), contextlib.redirect_stderr(err):
            return analysis.prereg_commit(), err.getvalue()

    def test_no_tag_uses_recorded_hash_and_says_so(self):
        commit, err = self.call(None)
        self.assertEqual(commit, "c530e5168b2d14d1f473ae316039ac9b27d52929")
        self.assertIn("fallback", err)
        self.assertIn(commit, err)

    def test_tag_present_is_used_silently(self):
        self.assertEqual(self.call(analysis.RECORDED_PREREG_COMMIT), (analysis.RECORDED_PREREG_COMMIT, ""))

    def test_tag_on_another_commit_stops(self):
        with self.assertRaises(SystemExit):
            self.call("b" * 40)

    def test_recorded_hash_is_the_one_in_decisions_and_the_tag(self):
        self.assertIn(f"`{analysis.RECORDED_PREREG_COMMIT}`", (run_eval.ROOT / "DECISIONS.md").read_text())
        tag = run_eval.prereg_commit()
        if tag:
            self.assertEqual(tag, analysis.RECORDED_PREREG_COMMIT)

    def test_fallback_output_equals_tag_output(self):
        import contextlib
        import io
        from unittest import mock
        outs = []
        for tag in (analysis.RECORDED_PREREG_COMMIT, None):
            buf = io.StringIO()
            with mock.patch.object(run_eval, "prereg_commit", return_value=tag), \
                    contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                analysis.main()
            outs.append(buf.getvalue())
        self.assertEqual(outs[0], outs[1])


if __name__ == "__main__":
    unittest.main()
