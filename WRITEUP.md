# Write-up (v1)

Every number below is copied from the output of `analysis.py` (tag `full`, `prereg-v1` commit
`c530e516…`, scorer revision B3). The design is in DESIGN.md and the reasons are in DECISIONS.md.

## 1. The 30-second story

I asked one AI model (Claude Sonnet 5.5) to write unit tests for 14 real Python modules, three
times each, and then planted small bugs in each module to see how many the tests caught. Every test
passed on the real code and the tests ran nearly every line, yet they caught only about 81% of the
logic bugs on the newer modules and about 90% on the older, well-known ones (logic scores 0.8097 and
0.8985, section 3). Coverage alone overstated how good the tests were.

## 2. What was measured and how

- **Writer:** one model, one frozen prompt, effort low. Up to 3 calls per run, with the writer shown
  its own test results and coverage after each one. 3 runs per module.
- **Corpus:** a primary set of newer modules and a baseline set of older libraries, reported
  separately and never pooled. v1 covers 14 complete modules (primary 7, baseline 7, 42 runs).
- **Mutation testing (cosmic-ray):** a fixed, seeded sample of planted bugs per module. The headline
  is the **logic score**: the share of those bugs the tests catch, leaving out number-constant
  replacements. Every module has at least 15 logic mutants, so none is excluded.
- **No-test control:** a null suite that only imports the module. Mutants it already "kills" are
  reported separately (the non-trivial measures).
- **Gaming detector:** a static check that drops tests which read the module's source or skip
  themselves. No writer test was dropped (kept_fraction 1.0000 in both sets).
- **Leakage audit:** the writer never sees mutants, scores or reference tests. In scoring, test code
  runs unprivileged and cannot read the mutant list or modify the module.
- **Pre-registration:** the measures, the headline and the analysis plan were frozen at git tag
  `prereg-v1` before the full run. The across-module statistics are means and medians of the
  per-module means, with 95% bootstrap intervals over modules.

## 3. Results

| measure | primary (n=7) | baseline (n=7) |
|---|---|---|
| **logic score, mean [95% CI]** | **0.8097 [0.7004, 0.9110]** | **0.8985 [0.8565, 0.9375]** |
| logic score, median [95% CI] | 0.8500 [0.7244, 0.9524] | 0.9027 [0.8583, 0.9514] |
| all-mutant score, mean | 0.7846 | 0.8767 |
| mean within-module range of logic score (threshold 0.0368) | 0.0485 (above) | 0.0169 (below) |
| line coverage, mean | 1.0000 | 0.9935 |
| first-iteration pass rate, mean | 0.7619 | 0.8095 |
| estimated cost per run, mean | $0.0760 | $0.0571 |
| writer wall time per run, mean | 29.8 s | 23.0 s |
| scoring wall time per run, mean | 71.2 s | 77.9 s |

- **Coverage is not fault detection.** Every complete primary module has mean line coverage 1.0000.
  On trace2task_experience_runtime, the logic score is 0.5400 on all 3 runs: the tests execute every
  line but miss nearly half of the logic bugs.
- **First attempt:** 33/42 runs passed all their own tests on the first try.
- **Cost:** $2.7963 in total over 42 runs. No run failed (0 of 49 allowlisted runs).
- **Noise:** on baseline the run-to-run spread is below the pre-registered 0.0368. On primary it is
  0.0485, mostly from one module: trace2task_experience spans 0.6533–0.8667 across its 3 runs.

## 4. What I can claim, and what I cannot

**Can claim:** on these 14 modules, with this prompt, setup and mutant sample, Sonnet 5.5 had logic
score 0.8097 [0.7004, 0.9110] on the primary set and 0.8985 [0.8565, 0.9375] on the baseline set.
Validity (kept_fraction 1.0000) and line coverage (1.0000 / 0.9935) were near ceiling, as
conditions, at $0.0760 / $0.0571 per run.

**Cannot claim:**
- Any newer-vs-older (contamination) effect. The two sets differ in more than age, they are small,
  and they are never pooled or tested against each other.
- Anything about other models or other prompts.
- "AI tests are good" in general.
- Anything precise about the primary set beyond its interval. The headline depends on which modules
  are in it: 0.8097 with all 7, 0.7780 without skijack_ast, and 0.7393 without the 3 AI-trace
  modules.

## 5. Limitations

- Planted bugs (mutants) are a proxy for real defects.
- Equivalent mutants (changes that don't alter behaviour) count as survivors and cap every score.
- Whole-module test generation is unlike real test writing, which happens against a diff.
- Unit tests only.
- One model and one prompt.
- The operator set has no statement-deletion or return-value mutants.
- Number-constant mutants mix meaningful changes with arbitrary tuning values. They are reported
  separately and left out of the headline.
- Many newer candidate modules showed traces of AI authorship. In v1, 3 of the 7 complete primary
  modules carry one.
- 3 runs hit the iteration limit, and their last suite was scored without the writer seeing its
  result. Dropping them moves the primary headline from 0.8097 to 0.8070.
- skijack_ast is at the ceiling (logic 1.0000 on every run).
- Run-to-run noise on primary (0.0485) is above the pilot's 0.0368, driven by one module.
- Staged execution for budget: only modules with all 3 planned runs are analysed. The 6 partial
  modules are shown descriptively in the `analysis.py` output only.
- Related work: not yet verified.

## 6. Not run, by decision

- Wave 2: every remaining planned run in `full_plan.json`, including the missing runs of the 6
  partial modules (budget).
- Sensitivity 3, sampled vs all mutants (cost/benefit; DECISIONS.md, Wrap-up v1).
- The upstream comparison against the maintainers' own tests (only 5 complete modules qualify).
- The Haiku, Gemini and no-coverage-feedback arms.

## 7. What carries forward

- Mutation score as the check that coverage is not.
- The no-test (null) control, which separates real kills from import-time kills.
- The static gaming detector.
- The leak-hardened scoring sandbox: privilege split, root-only mutant list, state wiped before
  every test run.
- The cost-capped, resumable driver, with hard stops and a refuse-to-start estimate.
