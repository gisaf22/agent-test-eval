# Design

Status: pre-registered at Stage B3 (2026-11-20), git tag `prereg-v1`. Sections 6–10 are the
frozen measures, analysis plan and run design. Every number below comes from `results.jsonl`,
`results_mutants.jsonl`, `results_mutmut.jsonl`, `results_null.jsonl`, `candidates_frozen.json`,
`candidate_counts.md`, `corpus_final.json`, `DECISIONS.md` or the files in `derived/` (computed
from those by `derive_b3.py`, with input hashes). Planning values are marked as such.

## 1. Question

How well do LLM-based test writers write unit tests for small Python modules? Tests are
scored by running them (mutation testing). There are no hand labels and no LLM judge.

Scope:
- Python only.
- Unit tests only (pytest or unittest, one module under test).
- Modules that import only the standard library and do no network, subprocess, file or
  database I/O (the A1b static rules).
- Claude models only.

## 2. Glossary

| term | definition |
|---|---|
| writer | The LLM-based agent under test. It is given a module and writes a test suite for it. |
| scorer | The harness (`run_eval.py` and `sandbox/`). It runs a suite against the original module and its mutants in an offline Docker sandbox and records the measures. |
| reference suites | Test suites for the same module that are not writer output: null, weak, strong and upstream. They show where the scale sits for each module. |
| null | Imports the module and asserts nothing. It marks the mutants that are trivially killed. |
| weak, strong | Constructed control test files (AI-generated, strength-by-design). Weak has a few shallow happy-path checks. Strong covers edge cases, error paths and invariants. They have a known intended ordering. They are not human-written and they are not samples of writer output. |
| upstream | The project's own test file, copied unedited from the upstream repo at a pinned tag or commit. |
| mutant | A copy of the module with one small seeded change (an operator swap, a changed constant, and so on) made by cosmic-ray 8.9.0. mutmut 2.5.1 is used for the cross-check. |
| mutation score | The share of the mutants used that the suite kills: killed / mutants_used, with timeouts counted as killed. The non-trivial variant drops the mutants the null suite kills. |
| validity | Whether each test passes on the original module. Each suite runs 10 times in seeded random orders. A test that fails every run is "wrong" and is dropped. The validity rate is the share of tests kept (`kept_fraction`). |
| flaky | A test that fails in some of the 10 validity runs but not all of them. It is dropped from scoring and counted. |
| corpus | The frozen set of modules a writer is run on (`candidates_frozen.json`). |
| baseline set | The 9 older or Stage 0 modules that have maintainer tests. They are scored separately from the primary set and never pooled with it, because the model may have seen this code in training. |

## 3. Pipeline

1. Pick a module from `candidates_frozen.json` at its `pinned_sha`. Check `module_sha256`.
2. **The writer gets:** the module source, the draft prompt (section 11), and its own tests
   plus their results and coverage on the original module.
3. **The writer never gets:** mutants, any score, the reference suites, the upstream tests
   or the scorer.
4. The writer's output files become a suite directory, `tests/<suite>/`.
5. Validity: 10 runs on the original module with no failfast. Each run uses a seeded random
   order and its own PYTHONHASHSEED. Wrong and flaky tests are dropped and counted.
6. Scoring runs the kept tests only, in pytest's own order with PYTHONHASHSEED=0. There are
   3 fixed-order baseline runs, and all must pass. Then coverage, then every mutant in the
   module's fixed sample. Each mutant is applied to the pristine file, tested and reverted,
   and the file's sha256 is checked. The per-mutant timeout is max(5 s, 10 × the slowest
   baseline run).
7. One row per (run, module, suite) is appended to `results.jsonl`, and one per mutant to
   `results_mutants.jsonl`. The mutmut cross-check writes to `results_mutmut.jsonl`.
8. The repeatability check compares the run with the previous run of the same
   `harness_version`. Any difference is a NO-GO.

The sandbox has no network, runs as a non-root user, has a read-only root filesystem with
tmpfs work directories, runs with capped memory, CPU and processes and dropped
capabilities, and gets no host environment variables. Scoring containers also split privileges
(B3): the module, harness and suites are root-owned and the mutant list is root-only, while test
code runs as an unprivileged user and its writable state is wiped before every run (section 7.2).
Details are in README.md.

## 4. Fixed, varied, measured

| factor | role | value / rule |
|---|---|---|
| model | varied | Claude models only. The final choice is open (section 12). B1 IDs, verified 2026-11-19: `claude-haiku-5-5`, `claude-sonnet-5-5`. |
| effort | fixed per run | proposed low (open). Sent as `output_config.effort`; no `temperature` (Sonnet 5.5 rejects it). |
| prompt | fixed | the section 11 draft. It is frozen after the B2 pilot, and `prompt_hash` is recorded. |
| module | varied | from `candidates_frozen.json` (primary set, baseline set reported separately) |
| mutant set | fixed per module | cosmic-ray, stratified by operator category, seed `20261117`, cap 100. It is drawn once and reused for every suite, and `mutant_set_sha256` is recorded. |
| seed | fixed | validity order and hash seeds come from `random.Random("20261117:validity:<module>:<suite>")`. Scoring uses PYTHONHASHSEED=0. |
| sandbox | fixed | the Docker flags in README.md |
| env_id | fixed, recorded | sha256(base image digest, Dockerfile, `requirements.lock`). The current value is `70d777ed…`, and each run checks `pip freeze` against the lock. |
| measured | outcome | the section 6 measures, plus tokens in/out, cost and wall time |

## 5. Corpus

Source: the A1b seeded GitHub search (seed 20261118, 300 repos per frame), frozen as
`candidates_frozen.json` (`meta.source_sha256` pins the `candidates.json` it was built
from). Later stages read this file and never rerun the search. The selection rules are in
DECISIONS.md under A1b, A1c and A1d: 50–300 physical lines, stdlib-only imports, the static
I/O denylist, MIT/BSD-2/BSD-3/Apache-2.0 licences, no vendored paths, deduplication, at most
2 files per repo, and no repo with a mutation-testing trace.

- **Primary set:** newer candidates whose first commit (`git log --follow`, committer date
  UTC) is on or after 2026-07-01. That is the first full month after Sonnet 5.5's June 2026
  training cutoff. This gives 38 candidates from 23 repos. Upstream tests: 21 direct,
  3 indirect, 14 none. 17 of the 38 have `ai_trace` and 4 have `possible_copy`.
  8 have no AI trace and a direct test (`primary_no_ai_trace_direct_test`).
- **Baseline set:** the 4 Stage 0 modules (toposort, heapdict, mergedeep, addict) plus all 5
  older A1b candidates that have an upstream test. That is 9 candidates from 8 repos:
  5 direct and 4 indirect tests, 0 with `ai_trace`, 2 with `possible_copy`, and 5
  `baseline_human_certain`. 3 of the 4 Stage 0 modules pass the A1b rules.
- **Wider newer windows** stay in the frozen file, with a flag per window, in case the model
  changes. Since 2025-09-01 there are 69 candidates (30 with `ai_trace`). Since 2026-02-01
  there are 49 (22 with `ai_trace`). The file holds 78 candidates in total.
- **Flags** mark candidates and never drop them: `possible_copy`, `baseline_human_certain`
  (the module and its test last changed on or before 2022-11-30) and `ai_trace`.
- **Removed in A1d:** 1 vendored npm copy (`node_modules/flatted`), from the
  since-2025-09-01 window only.
- **heapdict exception:** its LICENSE text was checked and is BSD-3-Clause. The third
  clause is a non-endorsement clause worded "The name of the author may not be used…", and
  the A2 wording test reads it that way. It still fails the GitHub licence-ID check because
  its SPDX is `NOASSERTION`, and that rule was not loosened. It stays in the baseline set as
  a documented exception. Its upstream tests can't run offline (they need `test.support`),
  so heapdict has no upstream line.
- **Corpus rule (B2b, written before any pilot result):** a module needs at least 20
  cosmic-ray mutants. Every excluded module has fewer than 20 mutants in total, so the cap
  of 100 plays no part. Of the 47 modules, all of which were fetched and import
  (B2a), 8 fall below the rule: 7 primary and 1 baseline. That leaves **31 primary and 8
  baseline** modules (`corpus_final.json`, `excluded_by_rule`).
- **Maintainers' tests:** only 8 of the 26 direct upstream test files run standalone, that is,
  with the module and the test file alone, offline, at their repo paths. The 8 are toposort
  and mergedeep (baseline), plus codebots_arena_elo, portable_hermes_agent_inline_markdown,
  synaptiq_retrieval, trace2task_experience, trace2task_experience_runtime and
  wtftd_war_thunder_full_t_blk (primary). addict's indirect file also runs, from Stage 0.
  The rest need other repo files or non-stdlib packages. Any comparison with maintainers'
  tests is limited to those modules (section 9).

## 6. Measures (pre-registered at `prereg-v1`, no composite score)

Each measure is reported on its own. They are never combined into a single number. B3 numbers
below come from `derived/b3_module_covariates.json`, `derived/b3_pilot_runs.jsonl` and
`derived/b3_report.md`, which `derive_b3.py` computes from the results files, the saved pilot
transcripts and the corpus (input hashes are recorded in each file).

### 6.1 Headline: logic score

- **Logic score** (`score_logic`) = the mutation score over every mutant used except
  number-constant replacements (cosmic-ray `core/NumberReplacer`): killed / used, timeouts
  counted as killed. It is computed from the existing per-mutant results and their operators. No
  mutant is re-run.
- **Eligibility:** a module counts toward the logic headline only if its fixed mutant sample has
  at least **15 logic mutants**. The rest appear only in the all-mutant score. All 31 primary and
  all 8 baseline modules have at least 15 (smallest: sustainability_score_config, 17).
- Reported for every module next to it: the **all-mutant score** (`mutation_score`, unchanged)
  and the **constants-only score** (`score_constants`). Rows also carry `constants_share` (the
  share of the module's sampled mutants that are number-constant replacements),
  `logic_mutants_n` and `constant_mutants_n`.
- Reason: number-constant mutants mix meaningful changes with arbitrary tuning values (section 9).
  On hangzhou_mahjong_ai_value, 65 of 100 sampled mutants are number constants. Its pilot
  all-mutant score is 0.270–0.290 and its logic score 0.543–0.600, with full line coverage. The
  headline choice was made after that pilot result (disclosure, section 8.4).

Operator to category mapping (`run_eval._CATEGORY_RULES`). An operator that matches no rule
stops the run. Counts are the fixed samples of the 39 usable modules (3,377 mutants).

| cosmic-ray operator | category | in logic score | sampled |
|---|---|---|---|
| `ReplaceBinaryOperator_*` | arithmetic | yes | 1,500 |
| `ReplaceUnaryOperator_*` except `_Delete_Not` | arithmetic | yes | 45 |
| `ReplaceUnaryOperator_Delete_Not`, `AddNot`, `ReplaceAndWithOr`, `ReplaceOrWithAnd` | boolean_logic | yes | 49 + 186 + 48 + 57 = 340 |
| `ReplaceComparisonOperator_*` | comparison | yes | 707 |
| `NumberReplacer` | constant | **no** (constants-only score) | 591 |
| `ReplaceTrueWithFalse`, `ReplaceFalseWithTrue` | constant | yes | 45 + 18 = 63 |
| `ZeroIterationForLoop`, `ReplaceBreakWithContinue`, `ReplaceContinueWithBreak` | control_flow | yes | 60 + 3 + 12 = 75 |
| `ExceptionReplacer` | exception | yes | 8 |
| `RemoveDecorator` | decorator | yes | 48 |

Boolean constants (`True`/`False` swaps) stay in the logic score: they flip a decision, not a
tuning value. Sampling is still stratified by category (section 4), so the split does not change
the mutant sets.

### 6.2 Conditions (reported for completeness, not results)

| condition | definition |
|---|---|
| validity | `kept_fraction`, with `tests_wrong`, `tests_flaky` and `tests_gaming` counted separately. `valid_file_level` gives the strict whole-suite view. |
| coverage | line and branch coverage of the module, plus `function_share` and `class_share` |

Under the feedback loop these saturate: the writer sees its own failures and its coverage each
round. In the pilot, 30 of 30 final suites kept 100% of their tests and 29 of 30 had line
coverage 1.00 (`results.jsonl`, tag `pilot`). They show whether a run produced a usable suite.
They are not evidence of test quality.

### 6.3 Secondary measures

| measure | definition |
|---|---|
| first-iteration pass rate | `first_iteration_pass`: the iteration-1 suite passed every test on the original module (pytest exit 0 in the writer's feedback sandbox). Pilot: 24 of 30. |
| iterations used | `iterations_used`: model calls in the run, including a final DONE call. Pilot: 22 runs used 2 and 8 used 3. |
| assertion-kill rate | `killed_by_assertion` / mutants used, raw and non-trivial |
| weak-assertion rate | the share of tests with no assertion, or only trivial ones (`ast`) |
| score by operator category | `mutation_by_category`, raw and non-trivial |
| cost and time | tokens in and out, estimated cost, writer and scoring wall time |
| failed runs | count per module and in total, by status: `writer_failed` (truncated, refusal, API error, wall cap, no files) and `extraction_failed` |

### 6.4 Descriptive: test-style profile (never scored)

`static_checks.style_profile`, computed with `ast` from each writer suite (no LLM involved):
- the number of test functions and tests per public function or class;
- the shares of tests that use `pytest.mark.parametrize`, any fixture, `monkeypatch`,
  `unittest.mock` and `pytest.raises`/`assertRaises`;
- the assertion-type mix (equality, truthiness, membership, comparison, other);
- the median assertions per test and the median test length in lines.

It is reported per module and per model as a secondary descriptive result. It has no thresholds,
no composite and no good or bad labels. Any conclusion about writer style is conditional on this
prompt and loop. They fix the framework (pytest), determinism and the output format, and they show
the writer its test results and coverage each round. The pilot profile is in `derived/b3_report.md`.

### 6.5 Pre-registered validity rules (B3)

- **Gaming detector** (`static_checks.gaming_flags`, `ast` only). A writer test is flagged, and
  dropped as invalid, if it reads the module under test as data or tampers with it:
  - an open or read of the module's file path, including `<mod>.__file__`, `__spec__`,
    `__loader__`, `__cached__`, `co_filename`, a string literal naming `<module>.py` or
    `/work/src`, `linecache`, `tokenize.open` and `pkgutil.get_data`;
  - `inspect.getsource`, `getsourcelines`, `getsourcefile`, `getfile`, `findsource` or
    `getcomments`;
  - `importlib.resources`;
  - `ast.parse`, `compile`, `exec` or `eval` of module source;
  - replacing the module under test in `sys.modules`;
  - an unconditional skip or xfail (decorator, `pytestmark`, or a top-level `pytest.skip`,
    `pytest.xfail` or `skipTest`).
  
  A test is also flagged when a same-suite helper or fixture it uses, an autouse fixture, its
  class's setup or class-level code, or a module-level statement of its file (or of
  `conftest.py`) does any of this. Allowed: ordinary use of the module, `inspect.signature`,
  normal imports, conditional skips, and the test file's own `__file__`.
  - Rows record `gaming_flag` (tests flagged), `gaming_flag_counts` (per rule),
    `gaming_flags`, `tests_gaming` and `gaming_dropped_tests`. Dropped tests count against
    `kept_fraction`.
  - The detector applies to writer suites only. On reference, constructed and upstream suites it
    is counted (`derived/b3_reference_gaming.json`) and never changes a row or a score.
  - Pilot: 0 tests flagged in the 30 pilot suites (counted only; pilot rows unchanged). The
    reference, constructed and upstream files have 0 of 554 tests flagged.
- **Extraction:** fenced blocks are read line by line. A Python block closes at the first line
  that is ```` ``` ```` alone and at which the block parses with `ast`, so a fence inside a test
  string neither splits a file nor raises a false "unterminated block" problem. After
  extraction, every file is parsed with `ast`. If a file of the final suite does not parse, the
  run is recorded as `extraction_failed`. That is its own `arm_status`: never scored and never
  repaired. Files that fail to parse in earlier iterations are recorded in
  `unparsable_by_iteration`, and the writer sees pytest's own error as usual. All 78 saved
  replies (dry run and pilot) extract byte-identical files under the new rule, and every file
  parses.

### 6.6 Per-run logging fields (B3)

`run_started_at`, `iterations_used`, `first_iteration_pass`, `response_model` (as returned by the
API), `request_ids`, `usage_full` (the API usage object as returned, per call),
`peak_input_tokens_per_call`, `retry_count` (HTTP attempts beyond the first, counted by httpx
event hooks; the SDK retry policy is unchanged), `api_events` (non-2xx responses, including rate
limits with their retry headers, and API errors), `scorer_revision` and `design_commit` (the
commit of the `prereg-v1` tag, read at run time). Pilot backfill is in
`derived/b3_pilot_runs.jsonl`. `request_ids`, `run_started_at`, `retry_count` and rate-limit
events were not recorded in the pilot and are marked `unavailable` (not inferred).

Per-module covariates are in `derived/b3_module_covariates.json`: physical lines, functions,
classes, branch count (coverage.py `num_branches`), mutants available and used, and constant and
logic mutants.

Not measured: readability and naming.

## 7. Scorer checks

### 7.1 A2.1 (Stage 0 reference suites)

Runs `20261119T165606Z` and `20261119T171136Z` (harness A2.1, env_id `70d777ed…`). Scores
are killed / used.

| module | null | weak | strong | upstream | cosmic-ray mutants |
|---|---|---|---|---|---|
| toposort | 0.0000 (0/60) | 0.6667 (40/60) | 0.8667 (52/60) | 0.9000 (54/60) | 60 of 60 |
| heapdict | 0.0000 (0/100) | 0.2200 (22/100) | 0.9500 (95/100) | not runnable | 100 of 240 |
| mergedeep | 0.0000 (0/50) | 0.0400 (2/50) | 0.9200 (46/50) | 0.8400 (42/50) | 50 of 50 |
| addict | 0.0000 (0/58) | 0.1379 (8/58) | 0.9310 (54/58) | 0.9138 (53/58) | 58 of 58 |

mutmut 2.5.1 cross-check, using all of mutmut's mutants:

| module | null | weak | strong | upstream | mutmut mutants |
|---|---|---|---|---|---|
| toposort | 0.0000 | 0.6250 | 0.9167 | 0.8333 | 24 |
| mergedeep | 0.0000 | 0.0556 | 0.9167 | 0.6944 | 36 |

- Every reference suite that ran was valid, with `kept_fraction` 1.0 and no wrong or flaky
  tests. No mutant was trivially killed.
- **Repeat match:** the two A2.1 runs match exactly. That covers every row field in
  `REPEAT_FIELDS`, all 972 per-mutant statuses and kill causes, and all 240 mutmut per-mutant
  statuses.
- **Ordering:** null < weak < strong on all 4 modules, under both tools.
- **toposort tool disagreement:** cosmic-ray puts upstream above strong (54 vs 52 of 60).
  mutmut puts strong above upstream (22 vs 20 of 24, timeouts counted as killed). The gap is 2
  mutants on both tools, and it flips. The scorer reliably separates null, weak and strong, but
  it cannot rank two strong suites a few mutants apart on a module this small. Weak also scores
  0.6667 on toposort with an assertion-kill rate of only 0.0667. Most of its kills come from
  exceptions, which is why assertion-kill rate is reported alongside the score.
- **heapdict 100-of-240 sampling:** the 100 mutants are stratified by operator category and
  reused for every suite, so comparisons between suites on heapdict are paired. The absolute
  score is an estimate over heapdict's full mutant set.

### 7.2 B3 scorer (scorer_revision B3, harness_version A2.1)

Source: `derived/b3_verification.json` (`derived/b3_checks/verify_b3.py`), run after the scorer
and sandbox changes. Results files were only appended to. Their pre-B3 lines are byte-identical.

- **Stage 0 reproduction:** reference run `20261120T052758Z` (B3 privilege-split sandbox)
  matches `20261119T211811Z` exactly on all 16 Stage 0 rows: every `REPEAT_FIELDS` field and all
  972 per-mutant statuses and kill causes.
- **B2b verification run** (`B2b-20261119T213540Z-sonnet55-angelbot_context_acl`), re-scored in
  scratch: every `REPEAT_FIELDS` field and all 72 per-mutant statuses match. All-mutant 0.8611,
  logic 0.9286, constants 0.6250.
- **Pilot suite** `B2c-pilot-sonnet55-portable_hermes_agent_inline_markdown-s1` (the backtick
  case), re-scored in scratch: every field and all 100 per-mutant statuses match. All-mutant
  0.81, logic 0.8193, constants 0.7647.
- **mutmut cross-check** on toposort (through `as_user.py`): per-mutant statuses equal to A2.1 run
  `20261119T171136Z` for null, weak, strong and upstream.
- **Gaming detector end-to-end:** a synthetic toposort suite has 1 behavioural test and 2 tests
  that hash the module's source. Scored in writer mode, the 2 source tests are flagged and dropped
  (`tests_gaming` 2, `kept_fraction` 0.3333). The score then comes from the behavioural test
  only (46 of 60).
- **Leakage audit** (`test_leakage.py`): no canary, key or earlier-run file reaches the writer
  sandbox. In scoring containers, test code cannot write the module, harness or suites, cannot read
  the mutant list, and sees no state from an earlier run. DECISIONS.md, Stage B3, has the pre-B3
  findings and the fixes.

### 7.3 Upstream reference suites

A module has an upstream line when its maintainers' test passed standalone in the B2a smoke check
(module and test file only, offline). These suites run unedited. New modules import the scored
module through `sandbox/alias_plugin.py` under its repo path (for example
`gui.inline_markdown`), which is derived with `ast` from the test's imports. Failing upstream
files are not rescued.

| module | set | runner | tests | all-mutant | logic (n) | constants | source run |
|---|---|---|---|---|---|---|---|
| codebots_arena_elo | primary | pytest + alias | 5 | 0.80 | 0.8953 (86) | 0.2143 | `20261120T054249Z` |
| portable_hermes_agent_inline_markdown | primary | pytest + alias | 35 | 0.83 | 0.8434 (83) | 0.7647 | `20261120T054249Z` |
| synaptiq_retrieval | primary | pytest + alias | 13 | 0.53 | 0.5222 (90) | 0.6000 | `20261120T054249Z` |
| trace2task_experience | primary | pytest + alias | 3 | 0.61 | 0.6800 (75) | 0.4000 | `20261120T054249Z` |
| trace2task_experience_runtime | primary | pytest + alias | 1 | 0.40 | 0.4000 (100) | — (0 constants) | `20261120T054249Z` |
| wtftd_war_thunder_full_t_blk | primary | pytest + alias | 9 | 0.73 | 0.7326 (86) | 0.7143 | `20261120T054249Z` |
| toposort | baseline | script (Stage 0) | 11 | 0.90 | see row | see row | `20261120T052758Z` |
| mergedeep | baseline | pytest (Stage 0) | 14 | 0.84 | see row | see row | `20261120T052758Z` |
| addict | baseline | pytest (Stage 0, indirect file) | 128 | 0.9138 | see row | see row | `20261120T052758Z` |

Every upstream suite kept all its tests (`kept_fraction` 1.0). heapdict's upstream file is not
runnable offline (`test.support`). The 17 other direct upstream files of usable modules fail
standalone and have no upstream line. The analysis uses the reference run tagged `full` at the
frozen commit (section 10), not these rows.

## 8. Claims and analysis plan

### 8.1 Claims

Allowed, in this form:

> On N modules, with this prompt/setup/mutants, writer X had logic score S (interval), all-mutant
> score S′ and constants score S″, vs these reference lines, at cost C, with validity V% and
> coverage K as conditions.

Not allowed:
- "AI writes good tests."
- "AI beats humans." The strong and weak controls are AI-generated, and the authorship of
  upstream tests is unknown for the newer modules.
- Claims about other test types (integration, property-based, end-to-end) or other languages.
- Claims about writer style beyond this prompt and loop (section 6.4).
- Cross-vendor claims of effort or temperature parity (section 10).

### 8.2 Analysis input rule

The analysis uses only rows with tag `full`, `design_commit` equal to the `prereg-v1` commit,
and `scorer_revision` B3. Dry-run, pilot, untagged reference, superseded and any other rows are
excluded by this explicit allowlist (`analysis.py`). `test_analysis.py` fails if a non-allowed
row reaches the analysis, if two allowlisted rows share (run_id, module, test_file), or if any
existing pre-freeze row is allowlisted.

### 8.3 Analysis plan

- **Unit of analysis:** the module.
- **Per module:** the mean and range (min–max) of each measure over its 3 runs.
- **Across modules:** the mean and the median of the per-module means, each with a 95% bootstrap
  interval that resamples modules with replacement. That is 10,000 resamples, percentile
  intervals, `random.Random(20261117)`.
- **Sets:** the primary set (31 modules) and the baseline set (8) are reported separately and
  never pooled.
- **Headline:** the logic score over the logic-eligible modules (all 39, section 6.1). The
  all-mutant and constants-only scores are reported for every module.
- **Failed runs:** counted per module and in total, by status. They are excluded from score
  means, not counted as 0. A sensitivity analysis counts them as 0. A module with no scored run
  is listed and left out of the across-module statistics.
- **Sensitivity analyses:**
  1. excluding modules with an AI trace (13 of the 31 primary modules; 0 baseline);
  2. excluding constants-heavy modules, where `constants_share` > 0.5. These are 3 primary
     modules: hangzhou_mahjong_ai_value 0.65, hangzhou_mahjong_ai_config 0.55 and
     sustainability_score_config 0.70. No baseline module is constants-heavy;
  3. sampled vs all mutants where the cap applies (20 primary and 4 baseline modules have more
     than 100 mutants). The s1 suite of each capped module is re-scored on all of its mutants,
     and its logic score is compared with the sampled one. That scoring pass is run after the
     full run and recorded under run ids with an `-allmutants` suffix;
  4. failed runs counted as 0.
- **Interpretation rule:** a difference smaller than the typical within-module run spread is not
  interpreted. The spread is the pilot's mean within-module range of the logic score, **0.0368**
  (10 modules, 3 runs each; all-mutant score 0.0425). This applies to differences between
  modules, between sets, between arms and against reference lines.
- **Upstream comparison:** only on the modules with an upstream line (section 7.3). Writer and
  upstream are compared per module, never pooled into one claim.
- **Drift check:** for the 10 pilot modules, the full-run per-module means are shown next to the
  pilot means. This is descriptive. The pilot is not part of the analysis.

### 8.4 Disclosure

The logic-score headline, the 15-logic-mutant minimum and the 0.5 constants threshold were
chosen after seeing the pilot results. The hangzhou_mahjong_ai_value module (section 6.1)
started that discussion. The pilot is excluded from the final analysis, and the all-mutant score
is reported next to the logic score for every module. The write-up states this.

## 9. Assumptions and limitations

- Planted bugs (mutants) stand in for real bugs. A high mutation score does not show that the
  tests catch real defects.
- Equivalent (false-bug) mutants behave the same as the original. They count as survivors and
  cap every suite's score. They are not separated automatically.
- The standard cosmic-ray operator set used here has no statement-deletion or return-value
  mutants, so those fault classes are not sampled.
- Number-constant mutants mix meaningful changes, such as a threshold or an off-by-one, with
  arbitrary tuning values that no behavioural test would pin. That is why they are kept out of the
  headline and reported on their own.
- Scores depend heavily on the module. Absolute scores are not comparable across modules. Only
  within-module comparisons and across-module summaries of them are meaningful.
- Scorer separation was demonstrated on constructed suites (null < weak < strong), not on
  different LLM writers.
- One model only (Sonnet 5.5) until the conditional arms (section 10) run.
- The scope is unit tests only. Integration and system behaviour are not tested.
- The weak and strong controls are AI-written. They show that the score separates suites. They
  are not a human baseline.
- The upstream comparison is limited to the qualifying modules (section 7.3): 6 primary and 3
  baseline. They are not a random sample, because they are self-contained enough to be tested
  without the rest of their repo.
- AI traces in newer candidates: 17 of 38 in the candidate primary set (13 of the 31 usable). Having no trace does
  not prove human authorship.
- The baseline set is small (8 modules), so no contamination comparison is possible.
- The 20-mutant rule removes the smallest modules (mostly constants and schema declarations).
  Results describe modules with enough code to mutate.
- Contamination is bounded by the first-commit date, not removed (`possible_copy` catches only
  copies with a header or notice, and `--follow` dates miss renames).
- The sample comes from a seeded GitHub search. Best-match order and the search index drift. The
  frozen file fixes the corpus, but the rates are estimates for that sample only.
- The gaming detector is static. It catches the listed patterns, not every possible way to
  observe the module. The scoring sandbox makes the module, the harness and the mutant list
  unwritable and the mutant list unreadable for test code (section 7.2). Reading the module's
  source in other ways, for example through `sys.modules[...].__dict__`, cannot be ruled out
  statically.
- The writer sees coverage each round. The conditional ablation (section 10) measures how much
  that shapes the tests.

## 10. Stage plan and stop rule

1. **B1 dry run.** Done (DECISIONS.md, Stage B1). Rows are tagged `dry_run` and are not analysed.
2. **Decision: model and corpus.** Done. Sonnet 5.5, effort low; 31 primary and 8 baseline
   modules (B2b).
3. **B2 pilot.** Done (B2c): 30 runs on 10 modules, 0 failed, $1.6357 of the $2.50 guard. It is a
   rehearsal, excluded from the analysis.
4. **B3 freeze.** Done: the prompt, measures, scorer, analysis plan and this run design are tagged
   `prereg-v1` (DECISIONS.md, Stage B3).
5. **Full run (pre-registered):**
   - `claude-sonnet-5-5`, effort `low`, prompt unchanged from section 11 (`prompt_hash`
     `9c407f6b…`, the same as the pilot). The caps are unchanged: 3 calls, `max_tokens` 32,000,
     120,000 tokens per run and 15 minutes per run.
   - 3 runs per module on the 31 primary and 8 baseline modules (117 runs), tag `full`, with a
     spend guard of $8.00 over `runs/full/ledger.jsonl` (`writer.SPEND_CAPS`). At the pilot's
     mean of $0.0545 per run, 117 runs is about $6.4. That is a planning value.
   - Fresh run ids. Pilot runs are not reused. They serve as a replicate on 10 modules and as a
     drift check (section 8.3).
   - `design_commit` is filled in at run time from the `prereg-v1` tag. `writer.py` and
     `run_eval.py` refuse tag `full` without it.
   - Upstream reference lines: one reference-mode run of the 9 upstream modules, tagged `full`,
     at the frozen commit.
6. **Planned second arm (conditional): Haiku 5.5.**
   - `claude-haiku-5-5` with the same prompt, modules and mutant sets, 3 runs per module, tagged
     `haiku_arm`.
   - It runs only after the Sonnet full run completes with no failed-run or scorer issues.
   - Each model is analysed on its own first, then compared per module.
   - Estimated cost is about $1–2, and scoring time about the same as the Sonnet run. Its spend
     cap and tag are added to `writer.py` before it runs.
7. **Planned third arm (conditional): one Gemini model on Google's free tier.**
   - The model is chosen from the models AI Studio lists as free for this account. Same prompt,
     modules and mutant sets, tagged `gemini_arm`.
   - Preconditions:
     - its training cutoff is before 2026-07-01, with the source recorded;
     - the free-tier request limits cover the run;
     - a second API client is written and tested without changing the Sonnet pipeline.
   - Free-tier data may be used by the provider to improve its products.
   - No effort or temperature parity is claimed across vendors. Each arm is analysed on its own
     first.
8. **Planned ablation (conditional): `no_coverage_feedback`.**
   - Pilot modules only, same model and prompt, with coverage removed from the feedback (test
     results only).
   - It runs only after the Sonnet full run is clean.
   - Purpose: show how much the coverage feedback shapes the tests. It is a different feedback
     template, so it has its own `prompt_hash` and is never pooled with `full`.
9. **Report.**

**Stop rule:** passed for the pilot. There was signal: per-module all-mutant means range from
0.280 to 0.917 and logic means from 0.571 to 0.929, while the mean within-module range is 0.0368.
Spend was $1.6357, under the $2.50 cap. The rule is kept for the full run. Stop on:
- the spend guard ($8.00);
- the key (or its last 12 characters) found in any written file;
- more than 5 of the first 10 runs failed;
- Docker or the sandbox not responding, or a scoring NO-GO;
- any run (writer plus scoring) over 15 minutes.

If the rule stops the run, publish the harness and the findings so far.

## 11. Writer prompt (frozen at `prereg-v1`)

```
You are writing a pytest test suite for the Python module below. Write thorough tests of
the module's behaviour. Rules: the module is importable as <module_name>; use only the
standard library and pytest; tests must be deterministic and must not use the network or
any file outside a temporary directory; output only the test files, one fenced code block
per file, first line a comment giving its path (tests/test_<module_name>.py).
```

The prompt never mentions mutation testing or a coverage target.

## 12. Open decisions

Settled at B3 (section 10): the model (Sonnet 5.5), the corpus (31 primary and 8 baseline
modules), the mutant cap (100 per module), the spend cap ($8.00 for the full run), 3 runs per
module and effort low. The per-module smoke check was done in B2a.

Still open:
- Where the full run executes
- Publishing details
- The all-mutants scoring mode for the sensitivity analysis (section 8.3), to be implemented
  before that analysis

## 13. Decision log

Full entries are in DECISIONS.md.

- 2026-11-17: cosmic-ray as the primary tool and mutmut for cross-checks; tar over
  `docker exec`; upstream tests as a reference suite.
- 2026-11-18: heapdict has no offline upstream tests, so addict was added; null suite; kill
  causes split; stable env_id and `requirements.lock`; Stage A0 clean-room check; Stage A1
  candidate count; Stage A1b tightened rules.
- 2026-11-19: Stage A1c freezes `candidates_frozen.json` (primary and baseline sets);
  Stage A1d extends the vendored folders and adds the licence check for repos not on GitHub;
  Stage A2 fixes heapdict's BSD-3 wording and moves the harness to A2.1 (test-level
  validity, new measures, stratified mutants, mutmut cross-check); Stages B1, B2a–B2c: writer,
  corpus build, corpus rule and pilot.
- 2026-11-20: Stage B3: scorer fixes (extraction, upstream suites, logic score fields, style
  profile, logging, gaming detector, scoring-sandbox privilege split) and the pre-registration
  freeze (`prereg-v1`).
