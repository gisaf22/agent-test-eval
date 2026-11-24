# agent-test-eval

A pre-registered experiment that measures how well one AI model (Claude Sonnet 5.5) writes unit tests for real
Python modules, scored by mutation testing in an offline, leak-hardened Docker sandbox.

**Start here**
- [WRITEUP.md](WRITEUP.md): the results, what can and cannot be claimed, and the limitations.
- [DESIGN.md](DESIGN.md): the plan, measures and analysis, pre-registered at git tag `prereg-v1`.
- [DECISIONS.md](DECISIONS.md): the reasoning behind each stage, the deviations and what was not run.

**Headline** (from [WRITEUP.md](WRITEUP.md) section 3; 14 complete modules, 3 runs each):

| measure | primary (n=7) | baseline (n=7) |
|---|---|---|
| **logic score, mean [95% CI]** | **0.8097 [0.7004, 0.9110]** | **0.8985 [0.8565, 0.9375]** |

Licence: MIT ([LICENSE](LICENSE)) for this repository's own code and data. The third-party modules it tests are not
included; they keep their own licences (MIT, Apache-2.0, BSD-3-Clause), listed per module in `corpus_final.json`.

## Repo map

| path | what it is |
|---|---|
| **Docs** | |
| [README.md](README.md) | this file |
| [WRITEUP.md](WRITEUP.md) | one-page v1 write-up: story, method, results, claims, limitations, what was not run |
| [DESIGN.md](DESIGN.md) | design and pre-registered plan (measures, validity rules, analysis plan, stage plan, frozen writer prompt) |
| [DECISIONS.md](DECISIONS.md) | dated decision log, stage by stage, including deviations and findings |
| [CLAUDE.md](CLAUDE.md) | standing rules for the coding agent that worked in this repo (append-only results, no key in the repo, untrusted code) |
| [LICENSE](LICENSE) | MIT licence |
| [candidate_counts.md](candidate_counts.md) | Stage A1b table: seeded estimates of how many GitHub modules meet the corpus rules |
| [.gitignore](.gitignore) | ignores the venv, caches, coverage and mutation-tool state |
| **Core code** | |
| [run_eval.py](run_eval.py) | the scorer: runs suites against the module and its sampled mutants (cosmic-ray) in the scoring sandbox and appends rows to the results files |
| [writer.py](writer.py) | the test writer: asks the model for a pytest suite, shows it only its own test results and coverage, up to 3 calls; logs tokens and cost |
| [run_full.py](run_full.py) | the resumable full-run driver: preflight checks, fixed plan, writer then scorer per run, hard stops and spend caps |
| [analysis.py](analysis.py) | the pre-registered analysis: allowlisted rows only, per-module means and bootstrap intervals; prints every table the write-up uses |
| [static_checks.py](static_checks.py) | `ast`-only gaming detector (drops tests that read the module's source or skip themselves) and descriptive style profile |
| [corpus_select.py](corpus_select.py) | Stage A1/A1b: seeded GitHub search and counts of candidate modules under the corpus rules |
| [corpus_freeze.py](corpus_freeze.py) | Stage A1c: freezes the selected candidates into `candidates_frozen.json` |
| [corpus_build.py](corpus_build.py) | Stage B2a: `fetch` downloads the frozen modules at pinned SHAs (sha256-checked, read with `ast` only); `smoke` and `final` built `corpus_final.json` |
| [pilot.py](pilot.py) | Stage B2c pilot driver (10 modules x 3 runs; a rehearsal, excluded from the analysis) |
| [derive_b3.py](derive_b3.py) | Stage B3: computes the files in `derived/` from the results files; never writes a results file |
| **Tests** (run with pytest; see Reproducibility) | |
| [conftest.py](conftest.py) | skips Tier 2 tests, with the reason, when their inputs are absent |
| [test_analysis.py](test_analysis.py) | the analysis allowlist, logic-score recomputation, bootstrap determinism, completeness rule, commit fallback |
| [test_static_checks.py](test_static_checks.py) | the gaming detector against synthetic cheats, and the style profile |
| [test_writer.py](test_writer.py) | writer isolation: no request contains mutants, scores or reference suites; reply extraction; API logging |
| [test_run_full.py](test_run_full.py) | the driver's plan, resume and every hard stop, with fake writer and scorer |
| [test_leakage.py](test_leakage.py) | Docker leakage audit: canaries and privilege checks for the writer and scoring sandboxes |
| **Data and results** (append-only) | |
| [results.jsonl](results.jsonl) | one row per (run, module, suite): validity, coverage, mutation and logic scores, cost, writer fields |
| [results_mutants.jsonl](results_mutants.jsonl) | one row per mutant per suite: operator, status, kill cause, null-killed flag |
| [results_null.jsonl](results_null.jsonl) | stored null-suite rows and their per-mutant statuses, reused when writer suites are scored |
| [results_mutmut.jsonl](results_mutmut.jsonl) | mutmut cross-check rows (toposort and mergedeep) |
| [candidates.json](candidates.json) | Stage A1b output: search funnel, sampled repos and candidate modules |
| [candidates_frozen.json](candidates_frozen.json) | the frozen corpus input: repo, pinned SHA, path, licence and sha256 per candidate |
| [corpus_fetch.json](corpus_fetch.json) | record of the B2a fetch (source URL, licence, upstream test, errors) per candidate |
| [corpus_final.json](corpus_final.json) | the usable corpus: 31 primary and 8 baseline modules, mutant sets, exclusions, pilot draw |
| [full_plan.json](full_plan.json) | the full-run plan: 117 runs (39 modules x 3), seed 20261120, `design_commit` |
| [smoke_results.jsonl](smoke_results.jsonl) | B2a smoke check per candidate (import, upstream test, null suite, mutant counts) |
| [smoke_null.jsonl](smoke_null.jsonl) | B2a null-suite rows |
| [smoke_null_mutants.jsonl](smoke_null_mutants.jsonl) | B2a null-suite per-mutant rows |
| **Folders** | |
| [runs/](runs/) | run records for `dry_run` (B1, plus the B2b verification run), `pilot` (B2c) and `full` (B4): per run `meta.json`, `driver.json` (pilot and full) and the final `suite/`; per tag `ledger.jsonl`; `full/` also holds `progress.txt` and the run-5 stop record. Transcripts, per-iteration files and logs are not shipped |
| [sandbox/](sandbox/) | the scoring sandbox: pinned Dockerfile and `requirements.lock`, the in-container runner, pytest plugins (kill cause, suite order, upstream import alias), script wrapper, `as_user.py` |
| [tests/](tests/) | reference suites: `null_test.py` (imports only) for each of the 47 candidates; `strong_test.py` and `weak_test.py` controls for the 4 Stage 0 modules (AI-written, built to differ in strength: they show the score separates suites, they are not samples of agent output) |
| [derived/](derived/) | B3 and B4 derived data: module covariates, pilot backfill, reference gaming counts, verification results, the synthetic gaming check, tolerated runs, and `b3_report.md` |
| [corpus/](corpus/) | `metadata.json` only (Stage 0 modules: wheel URLs, versions, sha256s, upstream test pins). Third-party sources are not shipped |

## Reproducibility

A published copy has no third-party code (`corpus/` holds only `metadata.json`), no git history, and none of
the model transcripts or scoring logs. That gives two tiers.

### Setup (host)

Python 3.10 (tested with 3.10.14). `analysis.py` uses the standard library only. The tests need pytest, and
the writer and driver tests need the Anthropic SDK (no API call is made by any test):

```
python3 -m venv .venv
.venv/bin/pip install pytest==9.2.0 anthropic==2.10.0
```

### Tier 1: works on a fresh clone

Re-run the analysis on the shipped results files. The output is byte-identical to the tables behind
WRITEUP.md. Without git history there is no `prereg-v1` tag, so `analysis.py` uses the commit recorded in
DECISIONS.md (`c530e516…`) and says so on stderr.

```
python3 analysis.py
.venv/bin/python -m pytest -q test_analysis.py test_static_checks.py test_run_full.py test_writer.py test_leakage.py
```

Run the tests with pytest: `conftest.py` skips the Tier 2 tests below, with the reason, when their inputs are
absent. `python -m unittest` does not read it.

### Tier 2: re-scoring needs Docker and a fetched corpus

- Fetch the newer modules, their licences and upstream tests at their pinned SHAs (sha256-checked, read with
  `ast` only). `corpus/` must exist (it does in a clone, because `corpus/metadata.json` is shipped). The fetch rewrites `corpus_fetch.json` (timestamps; error messages
  with local paths), so restore it afterwards:

  ```
  python3 corpus_build.py fetch
  git checkout -- corpus_fetch.json
  ```

- The 4 Stage 0 baseline modules are **not** fetched automatically: toposort 1.10 (Apache-2.0), heapdict 1.0.1
  (BSD-3-Clause), mergedeep 1.3.4 (MIT) and addict 2.4.0 (MIT), from PyPI wheels.
  `corpus/metadata.json` pins each one by package version, wheel URL and sha256 (module file and wheel), and
  pins its upstream test by repo, commit and path. Place them by hand at `corpus/<m>/<m>.py` and
  `tests/<m>/upstream_test.py`. heapdict's upstream test cannot run offline (it needs the stdlib `test.support`
  package, which official Python images strip), so heapdict has no upstream line.
- Scoring (`run_eval.py`, below) needs Docker. The writer (`writer.py`) also needs an API key in
  `AGENT_EVAL_API_KEY`.
- Tests skipped in Tier 1, and what they need:

| tests | needs |
|---|---|
| `test_writer.py`: `test_detector_catches_leaks`, `test_max_tokens_reply_fails_run_without_parsing`, `test_spend_caps_are_per_tag`, `test_final_suite_that_does_not_parse_is_extraction_failed_and_unscored`, `test_fake_client_marks_retry_count_unavailable`, `test_retry_and_rate_limit_are_logged` | Stage 0 module toposort |
| `test_writer.py`: `test_payloads_clean_and_sandbox_holds_only_module_and_writer_files` | all 4 Stage 0 modules and angelbot_context_acl (fetched) |
| `test_leakage.py`: `test_scoring_sandbox_protects_module_and_mutants`, `test_writer_loop_sandbox_sees_no_canary_key_or_earlier_state` | Stage 0 module toposort and Docker |
| `test_run_full.py`: `BranchlessSummaryCrash` (10 tests), `Run5` (1 test) | run 5's `scoring_log.txt` (not published: it records absolute host paths) |
| `test_run_full.py`: `Preflight::test_frozen_files_match_tag` | the `prereg-v1` git tag |
| `test_writer.py`: `SavedTranscripts` (2 tests) | saved transcripts (not published); these skip by their own check |

### Scoring runs (Tier 2)

```
python3 run_eval.py [--max-mutants 100] [--modules toposort,heapdict,mergedeep,addict] [--mutmut toposort,mergedeep]
```

This needs Docker with the arm64 image buildable. The first build needs network access; the eval itself does not. It is Tier 2: the modules must be in `corpus/` first (see Reproducibility).

## How scoring works

Harness version A2.1 (see DECISIONS.md, Stage A2). A suite is a directory of one or more test files.

- **Test-level validity:** each suite runs 10 times on the original module without failfast, each run in a seeded random test order with its own PYTHONHASHSEED. A test that fails any run is dropped: "wrong" if it fails every run, "flaky" if only some. `kept_fraction` is recorded, and `valid_file_level` keeps the strict whole-suite view.
- **Scoring runs** use pytest's own order and PYTHONHASHSEED=0, on the kept tests only. There are 3 fixed-order baseline runs, and all must pass.
- **Mutants** come from cosmic-ray 8.9.0. They are sampled once per module, stratified by operator category (seed `20261117`, cap `--max-mutants`, default 100), and the same set is used for every suite. Each mutant is applied to the pristine file, tested and reverted, and the revert is checked.
- **Per-mutant timeout** is max(5 s, 10 × the slowest baseline run).
- **Outcome measures**, reported only: line and branch coverage, the share of functions and classes with an executed line, weak-assertion rates (`ast`), test and file counts, and mutation score by operator category.
- **mutmut 2.5.1 cross-check** (`--mutmut <modules>`): the same suite commands, all of mutmut's mutants, rows in `results_mutmut.jsonl`.
- Runners: pytest `-x` by default. toposort's upstream file calls `unittest.main()` at module level, which breaks pytest collection. It runs unedited as `__main__` through `sandbox/script_wrapper.py` with unittest failfast (`-f`).

### Kill causes

These add up to `killed`. The first failure decides the cause.

| column | meaning |
|---|---|
| `killed_by_assertion` | a test body raised `AssertionError` (incl. unittest `assert*` / `failures=`) or pytest `Failed` (`pytest.raises` "DID NOT RAISE") |
| `killed_by_test_exception` | any other exception during a test's setup, call or teardown (unittest `errors=`) |
| `killed_by_collection_error` | the test file could not be imported or collected, e.g. the mutant raises at import time |
| `killed_by_crash` | non-zero exit with no recorded failure (interpreter crash, OOM kill, pytest internal error) |
| `timeouts` | the run exceeded the per-mutant timeout |

`killed_by_error` equals `test_exception + collection_error + crash`. It is kept so new rows can be compared with earlier ones, where these three causes were not separated.

### Scores

| column | definition |
|---|---|
| `mutation_score` | killed / mutants_used, timeouts counted as killed (unchanged) |
| `trivially_killed` | mutants the null arm kills; flagged per mutant in `results_mutants.jsonl` |
| `mutation_score_nontrivial` | the same score with trivially-killed mutants removed from both numerator and denominator |
| `assertion_kill_rate` | killed_by_assertion / mutants_used |
| `assertion_kill_rate_nontrivial` | killed_by_assertion / (mutants_used − trivially_killed) |

In the analysis, a post-hoc corrected non-trivial assertion-kill rate also drops null-killed mutants from the
numerator (DECISIONS.md, Wrap-up v1). It equals the stored value on all 42 v1 runs.

## Sandbox and environment identity

Each module gets one long-lived container, run with these flags:

- `--network none`
- non-root uid 10001
- `--read-only` root filesystem, with tmpfs at `/work` and `/tmp`
- `--memory 512m`, `--cpus 1`, `--pids-limit 128`
- `--cap-drop ALL` and `no-new-privileges`
- no host environment variables

Scoring containers (B3) add a privilege split: `/work` is root-owned, and the in-container runner
is exec'd as root with only `SETUID`, `SETGID` and `KILL`. It starts every test process as uid 10001
with no capabilities. Test code cannot write, chmod, rename or shadow the module, the harness or the
suites, and cannot read `/work/ctl` (the mutant list and cosmic-ray's session). Everything the test
user can write (`/tmp`, `/dev/shm`, `/work/xchg`) is wiped before every test run. The writer's
feedback sandbox keeps the flags above and is a fresh container per iteration. `test_leakage.py`
checks both.

Files are streamed in as a tar over `docker exec`. `docker cp` can't be used because Docker refuses it on containers with a read-only root filesystem, even when the target is a tmpfs path.

Rows record `env_id = sha256(base_image_digest, dockerfile_sha256, packages_sha256)`:

- `base_image_digest` is the registry index digest pinned in `FROM`.
- `packages_sha256` hashes `sandbox/requirements.lock`, which pins every installed package, including transitive dependencies. The packages are installed with `--no-deps` followed by `pip check`.
- Each run checks that the built image's `pip freeze` matches the lock.

Docker's local image ID can't serve as this identifier, because it changes on every rebuild, even a fully cached one. Rows before this change carry that ID as `image_digest`.
