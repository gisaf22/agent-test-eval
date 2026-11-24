# agent-test-eval

> **Results:** the v1 write-up is in [WRITEUP.md](WRITEUP.md): one model, 14 modules, mutation testing.
> The design is in [DESIGN.md](DESIGN.md) (pre-registered at tag `prereg-v1`) and the reasons are in [DECISIONS.md](DECISIONS.md).
> Third-party sources are not included. See [Reproducibility](#reproducibility) for what a fresh clone can and cannot re-run.

Prototype measurement loop for evaluating how well AI agents write tests for
code modules. A test file is scored by mutation testing: it runs against the
original module and against seeded mutants inside an offline Docker sandbox.

## Corpus

| module | version | licence | lines | upstream tests |
|---|---|---|---|---|
| toposort | 1.10 | Apache-2.0 | 95 | `test/test_toposort.py` @ tag 1.10 |
| heapdict | 1.0.1 | BSD-3-Clause | 115 | not runnable offline: needs `test.support` (official Python images strip the stdlib `test` package) |
| mergedeep | 1.3.4 | MIT | 100 | `mergedeep/test_mergedeep.py` @ tag v1.3.4 |
| addict | 2.4.0 | MIT | 159 | `test_addict.py` @ tag v2.4.0 |

`corpus/metadata.json` records source URLs, sha256 hashes (wheels checked against PyPI) and the upstream repo, tag, commit and path of each upstream test file.

## Test arms

| arm | file | what it is |
|---|---|---|
| null | `tests/<name>/null_test.py` | imports the module and asserts nothing; defines which mutants are *trivially killed* |
| strong | `tests/<name>/strong_test.py` | constructed control test file (AI-generated, strength-by-design): edge cases, error paths, invariants |
| weak | `tests/<name>/weak_test.py` | constructed control test file (AI-generated, strength-by-design): a few shallow happy-path checks |
| upstream | `tests/<name>/upstream_test.py` | the project's own test file, copied unedited from the upstream repo |

The strong and weak files are controls with a known intended ordering. They
show that the score can tell test files apart. They are not samples of agent
output.

## Method

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

## Files

- `run_eval.py`: host-side orchestration, stdlib only. `--writer-meta <meta.json>` scores a writer run alongside the module's reference suites.
- `corpus_build.py`: Stage B2a. It fetches the frozen candidates at their pinned SHAs (read with `ast` only on the host), smoke-checks them in the sandbox, records the mutant sets and null-suite timings, and writes `corpus_final.json` with the pilot draw.
- `writer.py`: the test writer (Anthropic SDK, in `.venv`). It reads the key from `AGENT_EVAL_API_KEY` only and writes `runs/<tag>/<run_id>/` (transcript, per-iteration files, final suite, meta) and `runs/<tag>/ledger.jsonl` (per-call tokens and cost). `test_writer.py` checks that no request leaks mutants, scores or reference suites.
- `sandbox/`: Dockerfile, lock file, the in-container runner, the pytest plugins (`killtype_plugin.py`, `suite_plugin.py`, `alias_plugin.py` for upstream tests that import the module by its repo path), the script wrapper and `as_user.py`
- `static_checks.py` (B3): `ast`-only gaming detector (pre-registered; writer suites only) and descriptive test-style profile. Tests: `test_static_checks.py`
- `analysis.py` (B3): the analysis input allowlist (tag `full`, `design_commit` = `prereg-v1`). Tests: `test_analysis.py`
- `derive_b3.py` (B3): derived files in `derived/` (module covariates, pilot backfill, reference gaming counts, report tables). It never writes a results file
- `test_leakage.py` (B3, needs Docker): canary and privilege audit of the writer-loop and scoring sandboxes
- `conftest.py` (wrap-up): under pytest, skips Tier 2 tests whose inputs are absent, with the reason
- `results.jsonl`: one row per (run, module, suite), append-only. Rows from harness A2.1 carry `harness_version`, and model fields (`model_id`, `effort`, `prompt_hash`, tokens, cost) are null for reference suites.
- `results_mutants.jsonl`: one row per (run, module, suite, mutant)
- `results_null.jsonl`: null-suite rows scored once per module (keyed by module, harness_version, env_id, mutant set, null file) and reused by writer scoring runs. Append-only.
- `results_mutmut.jsonl`: one row per (run, module, suite) for the mutmut cross-check

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
  `ast` only). `corpus/` must exist first. The fetch rewrites `corpus_fetch.json` (timestamps; error messages
  with local paths), so restore it afterwards:

  ```
  python3 corpus_build.py fetch
  git checkout -- corpus_fetch.json
  ```

- The 4 Stage 0 baseline modules (toposort, heapdict, mergedeep, addict) are **not** fetched automatically.
  `corpus/metadata.json` pins each one by package version, wheel URL and sha256 (module file and wheel), and
  pins its upstream test by repo, commit and path. Place them by hand at `corpus/<m>/<m>.py` and
  `tests/<m>/upstream_test.py`.
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

## Run

```
python3 run_eval.py [--max-mutants 100] [--modules toposort,heapdict,mergedeep,addict] [--mutmut toposort,mergedeep]
```

This needs Docker with the arm64 image buildable. The first build needs network access; the eval itself does not. It is Tier 2: the modules must be in `corpus/` first (see Reproducibility).
