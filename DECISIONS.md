# Decisions

Entries 2026-11-17 to 2026-11-18 (before Stage A0) were backfilled during Stage A1 from the commit history and README. Dates are the dates of the commits that introduced them.

## 2026-11-17 — cosmic-ray is the primary mutation tool; mutmut for cross-checks (8bc0f6a)

- Reason: cosmic-ray's mutants can be listed, sorted by (operator, occurrence) and capped with a seed, so the mutant set can be reproduced. It also runs any test command, which the sandbox runner needs.
- Cost: scores depend on one tool's operator set. mutmut is the planned cross-check, but it has not been run yet: it is not in `sandbox/requirements.lock`, and only `.mutmut-cache` is in `.gitignore`.

## 2026-11-17 — files go in as a tar over `docker exec`, not `docker cp` (8bc0f6a)

- Reason: Docker refuses `docker cp` into containers that have a read-only root filesystem, even when the target is a tmpfs path. The sandbox runs `--read-only`, and that flag is kept.
- Cost: the harness has its own small tar writer (`run_eval.tar_bytes`) and needs `tar` in the image. Copy errors show up as `tar` stderr rather than Docker errors.

## 2026-11-17 — upstream maintainers' tests are a third arm (8271540)

- Reason: the strong and weak controls are constructed. The project's own unedited tests are a real-world reference point to score agent output against.
- Cost: each module needs its upstream test file pinned to a tag or commit (recorded in `corpus/metadata.json`), and some need special runners. toposort's file calls `unittest.main()` at import time, so it runs as `__main__` through `sandbox/script_wrapper.py` instead of under pytest. The arms are not run in an identical way.

## 2026-11-18 — heapdict's upstream tests can't run offline; addict added as a fourth module (74d112f)

- Reason: heapdict's upstream tests import `test.support`. Official Python images strip the stdlib `test` package, and the sandbox has no network. So heapdict has no upstream arm. addict (MIT, 2.4.0, 159 lines, upstream `test_addict.py` at v2.4.0) was added so that three modules still have all arms.
- Cost: heapdict's arms are incomplete, which makes cross-module comparisons uneven. Adding a module is also more corpus to maintain. Vendoring `test.support` was rejected because it would edit the upstream setup.

## 2026-11-18 — null arm: import only, no assertions (74d112f)

- Reason: some mutants are killed just by importing the module, for example a mutant that raises at import time. The null arm finds those mutants, and `mutation_score_nontrivial` leaves them out, so a test file isn't credited for kills it didn't earn.
- Cost: one more arm per module, about 25% more sandbox runtime. Scores now come in two variants (raw and non-trivial) that have to be reported together.

## 2026-11-18 — kill types split into assertion, test exception, crash and timeout (74d112f)

- Reason: a raw "killed" count mixes real assertion failures with incidental errors. Stored columns: `killed_by_assertion`, `killed_by_test_exception`, `killed_by_collection_error`, `killed_by_crash` and `timeouts`. The first failure decides the cause. `assertion_kill_rate` is derived from them.
- Cost: this needs a pytest plugin (`sandbox/killtype_plugin.py`) and unittest result parsing, so it is more harness code that could misclassify kills. `killed_by_error` (test exception, collection error and crash added together) is kept so that older rows can still be compared.

## 2026-11-18 — stable env_id and `requirements.lock` (74d112f)

- Reason: Docker's local image ID changes on every rebuild, even a fully cached one, so it can't identify an environment. `env_id = sha256(base_image_digest, dockerfile_sha256, packages_sha256)`. The lock pins every package, including transitive ones. Packages are installed with `--no-deps` and then `pip check`, and each run checks the built image's `pip freeze` against the lock.
- Cost: env_id hashes the inputs, not the built image (see Stage A0), so the `pip freeze` check is what verifies the build. Upgrading a package means regenerating the lock by hand. Rows before this change carry `image_digest` instead, so they aren't directly comparable.

## 2026-11-18 — Stage A0: clean-room check

- No project containers (`ate-<module>-*`) were present, so nothing was removed. No prune commands were run.
- Rebuilt `agent-test-eval-sandbox:stage0` with `docker build --no-cache`. The image ID changed (38e27b643ee6 → 94cfca9733a8), which is expected. The env_id still matches the latest rows (`c05c6a512e9e1642…`), and the built image's `pip freeze` equals `sandbox/requirements.lock`.
- Caveat: env_id is hashed from the pinned inputs (FROM digest, Dockerfile, lock), not from the built image. A match therefore shows the inputs are unchanged. The pip-freeze check is what verifies the build output.
- Reproduced toposort (null, strong, weak and upstream arms) with the unmodified harness (`run_eval.evaluate_module`), writing rows to a scratch file instead of `results.jsonl`. The results match run 20261118T044236Z exactly: mutants_used, killed, survived and score, plus all 240 per-mutant statuses. Counts as used/killed/survived/score: null 60/0/60/0.0, strong 60/52/8/0.8667, weak 60/40/20/0.6667, upstream 60/54/6/0.9.
- `results.jsonl` and `results_mutants.jsonl` were not modified (same md5 before and after).

## 2026-11-18 — Stage A1: candidate count (`corpus_select.py`, seed 20261118)

- Sampling frames: each bucket samples repos by creation date. The older bucket uses repos created 2008-01-01..2025-06-30, the newer bucket repos created 2025-09-01..2026-11-17. Each draw takes a uniform random creation day, `language:Python created:<day>`, a random page of the first 1000 search hits, and 10 random repos from that page. The three newer windows are nested and are all counted within the one newer sample.
  - Reason: the bucket rules apply to files, but search can only sample repos, so the frames are limited to repos that could hold files for each bucket.
  - Cost: the sample is spread evenly over days, not weighted by how many repos each day has; total_count per draw is kept so it can be reweighted later. GitHub's search index changes, so a rerun with the same seed may not draw the same repos. `candidates.json` lists the repos actually examined.
- Dates: committer date in UTC of the commits on the default branch that touch the path, without `--follow`. A renamed file therefore counts as first appearing at its new path. Author dates are recorded too.
- Licence: GitHub's SPDX licence must be MIT, BSD-2/3-Clause or Apache-2.0, a licence file in the repo root must contain that licence's wording, and the file's own header must not name a different SPDX ID or GPL. Repos with no detected licence (333 of 600) are excluded rather than inferred.
- Tests: recorded per repo (`has_tests`), not used as a filter. Counts are shown with and without tests.
- Stricter rules, never looser. Each was needed to apply the rules by code:
  - Test files are not candidates.
  - `eval`, `exec`, `compile`, `__import__`, `importlib`, `ctypes` and all of `asyncio` count as I/O, because static checks can't see through them.
  - Relative imports fail the stdlib-only check.
  - Blobs over 200 KB are not fetched.
  - The full ban list is in the `meta` block of `candidates.json`.
- First run crashed at draw 13: a transient search error was classified using the response body instead of stderr, so it was never retried. It was fixed to retry with backoff and still stop on a persistent rate limit. The rerun went into a fresh download directory. The search rate limit never blocked the count.
- 9 of the 300 newer repos were not evaluated (5 clone timeouts after 600 s, 3 failed tree listings, 1 connection failure). They stay in the denominator, so the newer rates are slightly low.
- No model and no final corpus were chosen.

## 2026-11-18 — Stage A1b: tightened selection rules (recount with seed 20261118)

Sampling is the same as in A1; it is written out exactly here. Each draw runs
`gh api -X GET search/repositories -f q="language:Python created:<YYYY-MM-DD>" -f per_page=100 -f page=<n>`.
No `sort` or `order` parameter is passed, so GitHub uses its default best-match order. Forks are left out by search's default. Archived repos are fetched and then dropped by the archived rule.
- Draw: the day is lo + randrange(span+1). n_pages = min(10, ceil(min(total_count, 1000)/100)) and page = 1 + floor(u·n_pages). The page's items are sorted by lower-case full_name, repos already sampled are removed, and 10 are drawn with `random.Random(sub_seed)`. The day, u and sub_seed come, in that order, from `random.Random(20261118)`. The older frame is drawn first, then newer, up to 300 unique repos each.
- Reason: makes the sample reproducible on paper. Cost: best-match order and the search index change over time, so the same seed can still give a different set of repos.

Full static I/O denylist. Any import of, or reference to, any of these excludes the file; references are resolved through import aliases.
- Modules, including submodules: asynchat, asyncio, asyncore, bz2, concurrent.futures.process, ctypes, dbm, fcntl, filecmp, fileinput, ftplib, glob, gzip, http, imaplib, importlib, linecache, logging.handlers, lzma, mailbox, mmap, msvcrt, multiprocessing, netrc, nntplib, pathlib, pipes, poplib, pty, select, selectors, shelve, shutil, smtpd, smtplib, socket, socketserver, sqlite3, ssl, subprocess, tarfile, telnetlib, tempfile, urllib, webbrowser, winreg, wsgiref, xmlrpc, zipfile, zipimport.
- Names: codecs.open, io.FileIO, io.open, io.open_code, logging.FileHandler, tokenize.open, os.{access, chdir, chmod, chown, fdopen, fork, forkpty, fwalk, kill, killpg, lchown, link, listdir, lstat, makedirs, mkdir, mkfifo, mknod, open, pipe, popen, posix_spawn, posix_spawnp, read, readlink, remove, removedirs, rename, renames, replace, rmdir, scandir, sendfile, startfile, stat, symlink, system, truncate, unlink, utime, walk, write}, os.path.{exists, getatime, getctime, getmtime, getsize, isdir, isfile, islink, ismount, lexists, realpath, samefile}.
- Prefixes: os.exec*, os.spawn*, os.wait*.
- Builtins (bare names): open, __import__, exec, eval, compile, breakpoint. `from x import *` also excludes the file.
- Reason: makes "no network, subprocess, file or database I/O" checkable by `ast`. Cost: conservative. Anything that can reach I/O through code the check can't see (all of asyncio, importlib, eval) is excluded even when the file only uses safe parts.

New or tightened rules:
1. **Line count = physical lines**, comments and blanks included, 50–300. The text is decoded as UTF-8 (BOM stripped), `\r\n` and `\r` are treated as line ends, and a final line without a newline counts. Reason: A1 used `str.splitlines()`, which also splits on \x0b, \x0c, \x1c–\x1e, \x85 and  , so it was not a physical-line count. Cost: a few files may move across the 50 or 300 boundary; the count of those is reported.
2. **Imports: standard library only** (`sys.stdlib_module_names` of Python 3.12, the sandbox's interpreter). Any relative import excludes the file. This was already enforced in A1 and is unchanged. Imports inside `try/except ImportError` fallbacks count too. Cost: stdlib-only modules that have an optional fast path are excluded.
3. **Upstream test file.** A test file is any non-vendored `.py` matching A1's test-path rule: `test_*.py`, `*_test.py`, `conftest.py`, `test.py`/`tests.py`, or inside a `test`/`tests`/`testing` directory. It "imports this module" when one of its imports resolves to the module's file. Resolution works roughly as Python's does:
   - `import a.b` gives `a.b`; `from a.b import c` gives `a.b` and `a.b.c`; relative imports resolve from the importing file's directory.
   - A name is looked up as `<root>/a/b.py` or `<root>/a/b/__init__.py`, with the roots being the repo root, `src/` and the importing file's directory. Importing `a.b` also loads `a/__init__.py`.
   - If no file is found that way, the fallback is a dotted-suffix match. A single-word name such as `mod` counts only if it is unambiguous in the repo.
   - Package `__init__.py` files pass imports on: whatever they import counts as imported by the test too, up to 3 hops. This is how `from pkg import f` reaches `pkg/mod.py` through `pkg/__init__.py`.

   Older candidates need at least one such file. All matching paths are recorded in `upstream_tests`, and `upstream_tests_direct` lists the test files that resolve to the module from their own imports without going through a package `__init__`. Newer candidates record the paths but don't need them. Reason: the older arm needs an upstream test to score against. The first version, a suffix match only, missed mergedeep's own test (`from mergedeep import …` through `mergedeep/__init__.py`); the probe on mergedeep and addict now finds both upstream tests. Cost: imports through `importlib`, `sys.path` changes to other roots, or more than 3 `__init__` hops are missed. A package `__init__` that imports every submodule makes one test file count for all of them, which is why `upstream_tests_direct` is kept as the stricter signal.
4. **Dates follow renames.**
   - First commit is the oldest entry of `git log --follow` (git's default 50% similarity) on the default branch.
   - Last change is the newest commit touching the path on the default branch at clone time. Both use the committer date in UTC.
   - `pinned_sha` is the default-branch HEAD the file was read from.
   - Path-only dates are also recorded, and files that change bucket because of `--follow` are counted.
   - Cost: `--follow` needs rename detection, and in a blob:none clone that fetches historical blobs, so it is slower. `--follow` can also join unrelated files that look similar.
5. **No vendored paths.** A file is excluded if any directory in its path is named `site-packages`, `_vendor`, `vendor` or `third_party`, matched case-insensitively. Vendored files are also never used as upstream test files. Reason: A1 counted 22 files from one committed `site-packages`. Cost: none intended. A first-party package that happens to be named `vendor` would be lost.
6. **Drop duplicates.** The key is sha256 of the content with every whitespace run collapsed to one space and leading and trailing whitespace stripped (`" ".join(text.split())`). Among files with the same key, the one kept is in the repo with the earliest root-commit committer date. Ties go to the file's first-commit date, then repo URL, then path. Exact duplicates inside one repo are dropped the same way.
   - Cost: this only catches copies inside this sample. A copy of an upstream file that isn't itself in the sample (such as A1's detectron2 copy) is not detected.
   - Collapsing indentation could in theory merge two files whose code differs only in indentation.
7. **Cap at 2 candidates per repo**, counted across buckets. If a repo has more than 2, `random.Random(f"20261118:{repo_url}").sample(sorted(paths), 2)` chooses which. Reason: A1 had one repo supplying 52 of 96 older files. Cost: discards valid candidates, and the counts no longer show how prolific a repo is.
8. **Exclude repos with a mutation-testing trace.**
   - Files checked, anywhere in the tree: `pyproject.toml`, `setup.cfg`, `tox.ini`, `requirements*` (as a file name or a directory name), `README*`, `CONTRIBUTING*`, `mutmut_config.py`, any file whose name contains `cosmic-ray`, `cosmic_ray` or `cosmicray`, `.github/workflows/*.yml|yaml`, `.gitlab-ci.yml`, `.travis.yml`, `.circleci/config.yml`, `azure-pipelines.yml`, `appveyor.yml`/`.appveyor.yml` and `Jenkinsfile`. Only files of 1 MB or less are read.
   - A repo is excluded if any of these files contains, case-insensitively, `mutmut`, `cosmic-ray`, `cosmic_ray`, `mutpy`, `mutatest` or `mutation testing`.
   - Reason: upstream tests tuned against a mutation tool would inflate that arm. Cost: a passing mention, such as a README listing tools, also excludes the repo. A repo with no committed trace stays in.

Rule order for the per-rule removal counts. Each file is counted under the first rule it fails. File-level rules run first: test file, not UTF-8, line count (1), unparseable, imports (2), I/O, file licence conflict, vendored (5), no history, date buckets (4), older without an upstream test (3). Then comes the repo-level trace rule (8), then duplicates (6), then the cap (7). Vendored is checked before the dates so that vendored trees don't need `git log --follow`.

Stage A1b implementation note (infrastructure, no rule change):
- The first full A1b run hit `ls-tree` timeouts on 8 of 600 repos.
- Cause: `git ls-tree -l` prints blob sizes, so in a blob:none clone git fetches every blob one by one just to report them.
- The tree is now listed without sizes, and the same caps (200 KB for `.py` files, 1 MB for trace files) are applied to the files on disk after checkout.
- This also explains some of A1's slow clones and its `empty_repo` and timeout outcomes.
- The recount was rerun from scratch with the same seed into a fresh download directory.
- Second infrastructure fix, during the A1b rerun:
  - Cause: `subprocess.run(timeout=…)` killed only the `git` process and then waited for its pipes. Lazily started `git fetch` children kept those pipes open, so one stalled fetch hung a worker for hours, and the run was stopped at 511/600.
  - Fix: git now runs in its own process group, and the whole group is killed on timeout. `http.lowSpeedLimit=1000` / `http.lowSpeedTime=60` abort stalled transfers.
  - The recount was rerun from scratch with the same seed into a fresh download directory.

## 2026-11-19 — Stage A1c: freeze the corpus input (`corpus_freeze.py` → `candidates_frozen.json`)

Two sets, taken from the existing A1b sample (seed 20261118) under the A1b rules. No search was rerun, no older-bucket sampling was added beyond that sample, and no rule was loosened.
- **(a) Primary corpus:** newer candidates whose first commit (`--follow`, committer date UTC) is on or after 2026-07-01, the first full month after Sonnet 5.5's June 2026 training cutoff. Candidates in the other two newer windows (since 2025-09-01 and since 2026-02-01) stay in the frozen file, flagged per window, in case the model changes.
- **(b) Baseline set:** the four Stage 0 modules (toposort, heapdict, mergedeep, addict) plus every older A1b candidate with an upstream test file, direct or indirect (all 5 older candidates). Purpose: a human-written reference line scored against maintainer tests. Writer results on (b) are reported separately and descriptively, never pooled with (a), because the model may have seen that code in training.
- Reason: the primary set should be code the model cannot have trained on; the baseline gives a reference with real maintainer tests.
- Cost: there is no contamination comparison (the older bucket is too small to compare against). Upstream tests for newer modules have unknown authorship and may be AI-written. The baseline set is small (9 modules).

**Later stages read `candidates_frozen.json` and never rerun the search,** because GitHub search results drift between runs (A1 vs A1b re-query overlap was 290/300 older and 232/300 newer). `meta.source_sha256` pins the `candidates.json` it was built from. Each record carries `pinned_sha` and `module_sha256`.

Contents per candidate: repo URL, path, pinned SHA, first-commit and last-change dates, licence, physical line count, the chosen `upstream_test` with `upstream_test_kind` (direct / indirect / none) and its last-change date and sha256, all upstream test paths, `windows` (one flag per newer window), `primary_set`, `baseline_set`, `seed_set`, `possible_copy`, `baseline_human_certain`, `ai_trace`.
- Chosen upstream test: direct tests are preferred over indirect ones. Within the pool, a test whose stem (without `test_`/`_test`) equals the module stem is chosen first, then one that contains it, then the first path in sorted order. For Stage 0 the test is the one pinned in `corpus/metadata.json`.

Stage 0 modules through the A1b rules (`corpus_select.evaluate_repo`, unchanged, on fresh full-history blob:none clones of the upstream repos at default-branch HEAD). They are flagged `baseline_set` and `seed_set` whether or not they pass:
- mergedeep: passes, with a direct upstream test.
- addict: passes, with an indirect upstream test (reached through `addict/__init__.py`).
- toposort: the licence rule can't be evaluated as written, because the repo is on GitLab and has no GitHub SPDX. The remaining rules pass (run with the corpus licence, Apache-2.0, which the licence file's wording confirms), with a direct upstream test.
- heapdict: fails the licence rule. Its GitHub SPDX is `NOASSERTION`, and the A1b wording test reads its LICENSE as BSD-2-Clause: clause 3 says "The name of the author", not "Neither the name". `corpus/metadata.json` labels it BSD-3-Clause. Rerun with BSD-2-Clause, every other rule passes, with a direct upstream test.
- `pinned_sha` for Stage 0 is the corpus pin (tag commit), where the module is byte-identical to the corpus file. `rules_evaluated_at_sha` is the HEAD the rules ran on.

Mechanical flags. These only flag a candidate; none of them drops one.
- **`possible_copy`**: the module header or the repo's root licence file names a different owner or project. The header is the leading comments and docstrings, up to the first other statement, capped at 40 lines. A signal is any of:
  - (i) a copyright holder in the header with no token in common with the repo's owner or name;
  - (ii) a github/gitlab/bitbucket URL to a different repo, in the header or the licence file;
  - (iii) a provenance phrase in the header ("copied/adapted/taken/ported/derived/modified/forked/vendored from", "this file is part of", "identical copy");
  - (iv) a licence-file copyright holder that does not match the repo and contains an organisation word (Inc, Ltd, LLC, Team, Foundation, …).
  - Cost: an author's own company counts as a different holder (toposort's "True Blade Systems, Inc." is flagged). Copies with no header and no notice are missed.
- **`baseline_human_certain`**: the last change to the module file and to its chosen upstream test file (path-only `git log`, committer date UTC) are both on or before 2022-11-30.
- **`ai_trace`**: either of these:
  - the tree at `pinned_sha` has a file named `CLAUDE.md`, `AGENTS.md` or `.cursorrules` (anywhere, any case), a path inside a `.cursor` directory, or `.github/copilot-instructions.md`;
  - a commit touching the module (path-only and `--follow`) or any of its upstream test files has a message matching the `AI_MARKERS` regex in `corpus_freeze.py` (e.g. `Co-Authored-By:` naming Claude/Copilot/Cursor/Codex/Gemini/Devin/Aider, "Generated with [Claude Code]", `noreply@anthropic.com`), or an author/committer identity such as `copilot-swe-agent[bot]` or `Claude`.
  - **No trace does not prove human authorship:** AI assistance often leaves no marker, trailers get stripped, and agent instruction files may be untracked.

Found while flagging, not acted on: `ghostmkg/Recipe-Hub:apps/web/node_modules/flatted/python/flatted.py` is a vendored npm package (ISC header in an MIT repo). The A1b vendored-directory list does not include `node_modules`, and the file-licence rule checks only SPDX tags and GPL wording. It is flagged `possible_copy` and kept. Whether to tighten either rule is open.

## 2026-11-19 — Stage A1d: vendored folders extended; licence check for non-GitHub repos

- **Rule 5 (vendored paths) now also excludes `node_modules`, `bower_components`, `.venv`, `venv` and `dist-packages`.** The match is case-insensitive on any directory in the path, and the same rule applies to upstream test files. The change is in `corpus_select.VENDORED_DIRS`, so later reruns use it. `corpus_freeze.py` applies it to `candidates_frozen.json` and lists what it removes in `removed_candidates`.
  - Reason: the A1c count exposed a gap. `ghostmkg/Recipe-Hub:apps/web/node_modules/flatted/python/flatted.py`, a copy of the npm package flatted, had passed the A1b rules. No scores exist yet and no corpus has been chosen, and the extension only removes copied third-party code.
  - Effect: 1 candidate is removed, in the since-2025-09-01 window only. It removes 0 from the 2026-02-01 window, 0 from the primary 2026-07-01 window and 0 from the baseline set. Across the 60 sampled repos that had candidates or rule-3 losses, no other `.py` file sits under these folders. So no upstream-test resolution, deduplication or cap choice changes, and the candidates already in the frozen file need no recount.
  - Cost: `candidates.json` and `candidate_counts.md` (A1b) still reflect the old list; the frozen file is the current one. A first-party folder that happens to be named `venv` would be lost.
- **Licence rule for repos not on GitHub:** the root licence file's text must match exactly one of MIT, BSD-2-Clause, BSD-3-Clause and Apache-2.0, using the A1b wording test (`corpus_select.licence_family`). That match is taken as the licence, with no GitHub licence ID required. GitHub repos keep the A1b rule (GitHub SPDX plus wording).
  - Reason: GitLab repos have no GitHub SPDX, so A1c could not evaluate toposort.
  - Effect: toposort's `LICENSE.txt` matches Apache-2.0 only, so toposort passes all A1b rules. 3 of the 4 Stage 0 modules now pass.
  - Cost: wording is the only check. There is no independent licence detection to cross-check it against.
- Open, not changed: heapdict's licence label in `corpus/metadata.json` (see the A1c entry). Its LICENSE has three clauses, the third being "The name of the author may not be used to endorse or promote products derived from this software without specific prior written permission." That is a BSD-3-style non-endorsement clause; BSD-2-Clause has no third clause. The A1b wording test reads the text as BSD-2-Clause only because it looks for "neither the name" or "names of its contributors".

## 2026-11-19 — Stage A2: licence wording for heapdict's BSD-3 clause

- `corpus_select.licence_family` now also reads "the name of the author may not be used to endorse or promote products derived from this software" as the BSD-3-Clause non-endorsement clause. heapdict stays recorded as BSD-3-Clause in `corpus/metadata.json`.
- Reason: heapdict's LICENSE has three clauses. The third is that non-endorsement clause, in a different wording from "Neither the name …". Reading it as BSD-2-Clause was wrong, because BSD-2-Clause has no third clause.
- Effect:
  - None of the 600 A1b repos has that phrase in its root licence file, so the A1b counts are unchanged.
  - In `candidates_frozen.json`, only heapdict's record changes: `licence_file_wording` is now BSD-3-Clause and the wording failure is gone. heapdict still fails the GitHub licence rule (SPDX `NOASSERTION`), which was not loosened.
- Cost: one more phrase to maintain. Other non-endorsement wordings would still read as BSD-2-Clause.

## 2026-11-19 — Stage A2: harness upgrades (`run_eval.py`, harness_version A2 → A2.1)

- **Test-level validity.** Each suite runs 10 times on the original code without failfast. Every run uses a seeded random test order and its own PYTHONHASHSEED, both drawn from `random.Random("20261117:validity:<module>:<suite>")`.
  - A test that fails, or is missing from, any run is dropped: "wrong" if it fails all 10 runs, "flaky" if only some. Rows record `kept_fraction`, `wrong_tests` and `flaky_tests`. `valid_file_level` keeps the old strict view: every run of the whole suite passed.
  - Scoring runs (3 fixed-order baseline runs, coverage, mutants) use pytest's own order and PYTHONHASHSEED=0, and run the kept tests only. Dropped tests are removed by node id through `sandbox/suite_plugin.py`; the unittest wrapper does the same for script mode.
  - A suite is a directory, `tests/<suite>/` in the container, holding one or more files. pytest collects it with its default file patterns; script mode needs exactly one file.
  - Reason: one bad test should not zero a whole suite, and order or hash dependence must be visible. Cost: 10 extra runs per suite, about 5–25 s per module. A test that fails only under some order the 10 runs did not draw goes undetected.
- **New outcome measures**, reported only and used by no check:
  - line and branch coverage (coverage.py `--branch`, module only, fixed order, kept tests);
  - `function_share`: functions with at least one executed body line. Def and decorator lines run at import and are not counted;
  - `class_share`: classes with an executed line inside one of their methods. Classes without methods are left out and counted;
  - weak-assertion rates (`ast`): tests with no assertion, and tests whose only assertions are trivial (`assert <const>`, `x == x`, `assertTrue(<const>)`, `assertEqual(x, x)`). Same-file helpers that assert count, up to 3 levels deep;
  - `n_tests` (collected at runtime), `n_tests_static`, `n_test_files`;
  - `mutation_by_category`, raw and non-trivial, next to the existing kill-cause split.
- **Mutant sampling.** The sample is stratified by operator category:
  - categories: arithmetic, comparison, boolean_logic, constant, control_flow, exception, decorator (`_CATEGORY_RULES`). An operator that matches none stops the run.
  - Each category gets a share of the cap in proportion to its size (largest remainder, at least 1 each), and is sampled with `random.Random("20261117:<category>")`.
  - The cap is `--max-mutants`, default 100 (it was 200 and unstratified). The sample is drawn once per module, reused for every suite, and its sha256 is recorded in `mutant_sampling`.
  - Each mutant is applied to the pristine file, tested and reverted, and the file's sha256 is checked before each mutant and at the end.
  - Effect: only heapdict (240 mutants) is sampled. The other modules have ≤100 mutants and use all of them, as before.
  - Cost: heapdict scores now come from 100 mutants instead of 200, so they can't be compared directly with Stage 0 rows.
- **Schema.** Rows add `harness_version`, `suite`, `suite_files` (path and sha256), `sandbox_python`, `env_id_inputs` (`base_image_digest`, `dockerfile_sha256`, `packages_sha256`), `mutant_sampling` and `validity_runs`. `model_id`, `effort`, `prompt_hash`, `tokens_in`, `tokens_out` and `estimated_cost` are null on reference suites. `run_id`, `seed` and `wall_seconds` were already there. `flaky_runs_failed` still counts failed fixed-order baseline runs.
- **mutmut cross-check:** mutmut 2.5.1, with pony 0.7.19, junit-xml 1.9, glob2 0.7 and six 1.17.0 added to `sandbox/requirements.lock`.
  - Reason: mutmut 2 mutates the file in place and runs any test command. So it uses the same suite command (failfast, kept tests, script mode for toposort's upstream tests) without changing the layout. mutmut 3 would add libcst and textual, and its trampoline design copies the source into `mutants/`, outside the `src/` path the tests import.
  - It runs over all of mutmut's mutants. Rows go to `results_mutmut.jsonl` (new, append-only). Score = (killed + timeout) / (killed + timeout + survived + suspicious).
  - Cost: the image changes, so the env_id changes (`c05c6a51…` → `70d777ed…`); the image tag is now `:a2`. mutmut 2 is in maintenance.
- **Repeatability** compares against the previous run with the same `harness_version`. It covers every suite (it used to cover only the controls), the fields in `REPEAT_FIELDS`, every per-mutant status and kill cause, and mutmut per-mutant statuses. Any difference is a NO-GO.
- **A2 → A2.1:**
  - Runs `20261119T162442Z` and `20261119T164023Z` (harness A2) matched each other exactly. But their static test discovery missed tests defined in in-file mixin classes: addict's upstream `AbstractTestsClass(object)` gave `n_tests_static = 0`. They also reported 0/0 shares as 0.0.
  - A2.1 follows in-file base classes of test classes, and reports 0/0 outcome shares as null. It also adds the static fields to `REPEAT_FIELDS`. Scores, validity and coverage counts are unaffected.
  - The two A2 runs stay in the append-only files and are superseded by the A2.1 runs.

## 2026-11-19 — Stage B1: model facts verified from the official docs

Source: the English Markdown versions of platform.claude.com/docs/en/ `about-claude/models/overview`, `about-claude/pricing`, `build-with-claude/effort`, `build-with-claude/thinking`, `models/sonnet-5-5/overview` and `models/haiku-5-5/overview`, fetched 2026-11-19.

- **Model IDs:** `claude-haiku-5-5` and `claude-sonnet-5-5`. On the Claude API the alias and the ID are the same, with no date suffix.
- **Prices per million tokens:** Haiku 5.5 is $0.10 in and $0.50 out for prompts up to 100,000 tokens, and $0.50 in and $2.50 out above that. Sonnet 5.5 is $2 in and $10 out. Thinking tokens are billed as output. `writer.py` books cache writes at 1.25x and cache reads at 0.10x, but B1 sends no `cache_control`, so neither occurred.
- **Temperature:** on Sonnet 5.5, "setting `temperature`, `top_p`, or `top_k` returns a 400 error." Haiku 5.5's page says to omit all three. `writer.py` sends none of them.
- **Effort:** the setting is `output_config.effort` with the values `low`, `medium`, `high`, `xhigh` and `max`, and both models support all five. The defaults are `high` on Sonnet 5.5 and `medium` on Haiku 5.5. Haiku 5.5 supports `low` itself, so B1 ran both models at `low`.
- **Thinking:** adaptive thinking is on by default on both models. `writer.py` omits `thinking`, and thinking text comes back empty by default.
- **Training cutoff:** June 2026 for both, which matches the DESIGN.md section 5 primary-set window.
- Nothing above contradicts DESIGN.md.

## 2026-11-19 — Stage B1: writer and dry run (`writer.py`, `test_writer.py`)

- **`writer.py`** is its own script on the Anthropic Python SDK (`anthropic` 2.10.0, installed in `.venv` only). The harness stays stdlib-only.
  - The prompt is the DESIGN.md section 11 block, read from DESIGN.md at run time and sent as one paragraph, followed by the module source.
  - Each feedback turn sends the pytest exit code and the last 8,000 characters of pytest output, then `coverage report -m`, from a fresh offline container that holds only `src/<module>.py` and the writer's files.
  - Every reply must be the complete suite again, or `DONE`. The final suite is the last reply that contained files.
  - `prompt_hash` = sha256 of (section 11 text, feedback template, parse-error template).
- **Caps:**
  - at most 3 model calls per run;
  - `max_tokens` 16,000 per call (streaming);
  - 120,000 tokens in plus out per run, checked before each call;
  - 15 minutes per run;
  - $2.00 for all dry-run calls together. The guard sums `runs/dry_run/ledger.jsonl` and refuses any call whose worst case (estimated input, full `max_tokens` output) would pass the cap.
- **No server-side refusal fallback.** A fallback would silently swap the model under test, so a refusal ends the run instead.
- **Key handling:** the key is read only from `AGENT_EVAL_API_KEY` and popped from the environment before any `docker` subprocess starts. It is never logged. A byte scan of every tracked, untracked and `.git` file found neither the key nor its last 12 characters.
- **Scoring:** `run_eval.py --writer-meta runs/dry_run/<run_id>/meta.json` adds the writer suite (`test_file = "writer"`) after the module's null, weak, strong and upstream suites in one invocation, so the writer suite gets the same validity runs, mutant set, coverage and measures.
  - Rows carry the writer's `run_id` and `tag`, and every row of that invocation is tagged `dry_run`.
  - `seed` and `wall_seconds` already mean the harness seed and the scoring time, so the writer's values go in `writer_seed` and `writer_wall_seconds`. `writer_iterations`, `writer_stop` and `writer_parse_failures` are added too.
  - Tagged runs never serve as the repeatability baseline. A writer invocation compares only its own module's reference suites against the latest untagged run.
  - All 4 invocations matched `20261119T171136Z` exactly, so scoring was unchanged and `harness_version` stays A2.1.
- **`test_writer.py`** (`.venv/bin/python -m unittest test_writer`) fails if any logged request payload has any of the following, unless the item also occurs in the module source or the writer's own replies:
  - mutant or score vocabulary;
  - a reference or upstream test line;
  - a score-like number, a system prompt or a sampling parameter.
  
  It also checks that the feedback sandbox receives only the module and the writer's files, and that the detector fires on planted leaks. It passed on the synthetic loop and on all saved transcripts.
- **Incident:** the first call (`B1-20261119T180914Z-haiku55-toposort`) succeeded, but `writer.py` crashed reading `_request_id`, which the streamed message lacks, before it logged the usage. That call's worst case ($0.008143) is booked in the ledger with `usage_lost: true`. The run was not scored and was rerun under a new run_id.
- **Dry-run spend:** $0.0761 in total, including the booked worst case. The rows are tagged `dry_run` and are excluded from analysis.

## 2026-11-19 — Stage B2a: writer max_tokens 32,000; truncated replies fail the run

- `MAX_TOKENS_PER_CALL` goes from 16,000 to 32,000 for every model. Reason: in B1, Haiku 5.5 used 14,684 of 16,000 on mergedeep at effort `low`. Thinking counts toward `max_tokens`, so larger modules or higher effort would truncate. Calls are streamed, so a larger limit carries no timeout risk.
  - Cost: the spend guard's worst case per call doubles (Sonnet 5.5: $0.32 of output), so the guard refuses a call sooner.
  - `RUN_TOKEN_CAP` stays at 120,000, so a third call can now be refused by the cap in heavy runs. If that happens it is recorded as `stop=token_cap`.
- Every call records its `stop_reason` in the transcript's `response` event and in the ledger. `meta.json` gets `stop_reasons`.
- A reply that stops at `max_tokens` marks the run `failed_truncated`:
  - it is not parsed;
  - the sandbox does not run;
  - the run's suite is empty, even if an earlier iteration produced files;
  - `run_eval.py --writer-meta` refuses to score it.
  
  Reason: a cut-off reply can still parse into a shorter suite, which would understate the writer without any visible sign. Truncation is counted as a run outcome instead. Tested in `test_writer.py` (`test_max_tokens_reply_fails_run_without_parsing`).
- The final `DONE` call is kept as it is.
- No API calls were made in B2a.

## 2026-11-19 — Stage B2a: corpus build and sandbox smoke check (`corpus_build.py`)

- **Scope:** all 47 primary-set (38) and baseline-set (9) candidates in `candidates_frozen.json`. No model API calls were made.
- **Fetch:**
  - Each module was fetched from raw.githubusercontent.com at its `pinned_sha`, along with its licence file and its direct upstream test when there is one (23 new tests).
  - Every module's sha256 matches `module_sha256`. No upstream test sha differs from a recorded value.
  - On the host, downloaded code is only read as bytes and parsed with `ast`. Upstream tests are stored as `corpus/<name>/upstream_test.txt`, so host-side pytest can never collect them.
  - The 4 Stage 0 modules keep their existing files, which match their pins (A1c).
- **Corpus names:** new modules are stored as `corpus/<name>/<name>.py`, with `<name>` = `<repo slug, max 24 chars>_<file stem>`.
  - Reason: several stems collide (`config`, `schema`), and SKIjack's `ast.py` would shadow the stdlib `ast` that pytest imports.
  - The module text is unchanged and only the file name differs. `meta.json` records the repo, SHA, original path, licence, dates and flags.
- **Smoke check**, offline sandbox only, Python 3.12 (pinned image):
  - **Flat import** (`import <name>`, as the scorer imports it): 47 of 47 pass. Nothing is excluded.
  - **Upstream tests:** each direct test runs with the module and the test file at their repo paths, and no other repo files. 8 of 26 pass. That count includes Stage 0 toposort and mergedeep, taken from A2.1.
  - The failures are recorded, not acted on. Most need other repo modules or non-stdlib packages (numpy 3). heapdict needs `test.support`.
  - Upstream-test failures are not exclusions. Whether a failing upstream file can serve as a reference suite is a later decision.
  - **Fixed:** the first SKIjack upstream run reported a false `ast` shadowing error. It came from the check's own PYTHONPATH, which included the module's directory. The fix drops that directory for stdlib-named modules, and the rerun gives the real reason (`aviary_kernel` missing).
- **Mutants:** cosmic-ray 8.9.0 with `run_eval.select_mutants`: stratified by operator category, seed 20261117, cap 100.
  - toposort's set hash matches Stage 0 (`c3047d07…`), so the rule carried over unchanged. No operator fell outside `_CATEGORY_RULES`.
  - 8 modules have fewer than 20 mutants and are flagged, not dropped: wdcnet_config_schema 0, home_assistant_budget_bo_const 2, sustainability_score_model 3, d3_frame_selector 4 (baseline), marigold_v2_registry 7, hermes_telegram_stickers_schemas 8, sentineledgeai_bounded 18, django_cfg_results 19. wdcnet_config_schema has no mutants at all, so it cannot yield a mutation score.
- **Null-suite timing:** run once per module through `run_eval.evaluate_module`, so it is the same code path as scoring: validity ×10, 3 baselines, coverage, mutants.
  - Rows went to `smoke_null.jsonl` and `smoke_null_mutants.jsonl`, not `results.jsonl`, because these are timing and smoke runs with no reference suites.
  - The laptop slept during the run. The two modules whose runs spanned a sleep (zagentic_ir_schema, codex_memories_redaction) were rerun, and the latest record is used.
  - Sum of null times: 2,736 s for all 47 modules (primary 2,198 s, baseline 539 s). A 100-mutant module takes about 75–81 s.
- **Projection** (scoring only; writer time and API time excluded):
  - The writer suite is assumed to take 1.2× the null time. That is the largest writer/null ratio seen in B1 (1.08–1.19).
  - As built, each writer run is scored in its own invocation that re-runs null: 3 × (1 + 1.2) × null = 6.6 × null. That gives about **5.0 h for all 47 modules and 4.0 h for the primary set** at 3 runs per module and 1 model.
  - With one shared null per module it would be 4.6 × null, about 3.5 h (primary 2.8 h).
  - Any upstream or other reference suites re-run per invocation would add about 1× null each.
- **Pilot:** `random.Random(20261118).sample(sorted names of the usable primary modules, 10)`, where usable = fetched with a matching sha256, imports in the sandbox and has a valid null suite (all 38). The draw:
  - ai_video_generator_text, angelbot_context_acl, blackmamba_open_source_r_power_estimator, codex_memories_redaction, hangzhou_mahjong_ai_value, hermes_telegram_stickers_schemas, home_assistant_budget_bo_analytics, portable_hermes_agent_inline_markdown, role_aware_financial_age_sanitize, sentineledgeai_pdf.
  - hermes_telegram_stickers_schemas has only 8 mutants, all constants. The rule was not changed to avoid it.
- **Open for B2b:** `writer.py` and `run_eval.suite_specs` look modules up in `corpus/metadata.json`, which has only the 4 Stage 0 modules. Both must read `corpus/<name>/meta.json` (or `corpus_final.json`) before the pilot can run. That change was not made here.
- **Files:** `corpus_build.py` (fetch / smoke / final), `corpus_fetch.json`, `smoke_results.jsonl`, `smoke_null.jsonl`, `smoke_null_mutants.jsonl` and `corpus_final.json`, plus `corpus/<name>/` and `tests/<name>/null_test.py` for the 43 new modules.

## 2026-11-19 — Stage B2b: corpus rule, pilot replacement, corpus-wide metadata, stored null rows, pilot tag

- **Corpus rule:** a module needs at least 20 cosmic-ray mutants to be in the corpus. The rule was written before any pilot result existed; no pilot run had been made.
  - Reason: with fewer than 20 mutants, one mutant moves the score by more than 5 points. wdcnet_config_schema has none at all.
  - Applied in `corpus_build.py final`, giving 31 primary and 8 baseline usable modules. These move to `excluded_by_rule`, with mutant counts: wdcnet_config_schema 0, home_assistant_budget_bo_const 2, sustainability_score_model 3, marigold_v2_registry 7, hermes_telegram_stickers_schemas 8, sentineledgeai_bounded 18, django_cfg_results 19 (primary); d3_frame_selector 4 (baseline).
- **Pilot:** the 9 modules from the B2a draw that pass the rule are kept. hermes_telegram_stickers_schemas (8 mutants) is replaced.
  - Rule: R = sorted names of the usable primary modules not already in the pilot. The replacement is the first element of `random.Random(20261118).sample(R, len(R))`.
  - Result: **zagentic_doi** (100 of 640 mutants; its direct upstream test does not run standalone).
  - The pilot is now ai_video_generator_text, angelbot_context_acl, blackmamba_open_source_r_power_estimator, codex_memories_redaction, hangzhou_mahjong_ai_value, home_assistant_budget_bo_analytics, portable_hermes_agent_inline_markdown, role_aware_financial_age_sanitize, sentineledgeai_pdf, zagentic_doi.
  - `corpus_final.json` records `pilot_b2a_draw`, `pilot_replacements` and `pilot`.
- **Corpus-wide metadata:** `run_eval.module_meta()` reads the module file, its sha256 and the fixed mutant set's sha256 from `corpus_final.json` for any usable module. Stage 0 upstream-test details still come from `corpus/metadata.json`.
  - The harness now checks the module sha256 before each module.
  - It also checks that the drawn sample equals the fixed set (`mutant_set_sha256`, cap 100), and stops if it differs.
  - Reference mode includes strong and weak only where those files exist, which is Stage 0 only.
  - `writer.py` uses the same lookup, so a module excluded by the rule cannot be written for.
  - The sandbox environment is the same for every module (README), so there is nothing per-module to read for it.
  - Upstream suites for new modules are not wired in, because their tests need their repo layout. That stays open for the 6 primary modules whose upstream tests run standalone.
- **Stored null rows:** in writer mode, the null suite is scored once per module. The scored row and its per-mutant statuses are appended to `results_null.jsonl` (append-only), keyed by module, harness_version, env_id, mutant_set_sha256 and the null file's sha256.
  - Later writer runs on that module reuse the stored null for the trivially-killed set instead of re-scoring it. The writer row records `null_source` (reused or not, and the run_id the null came from).
  - Writer-suite scoring is unchanged.
  - Writer mode no longer re-runs strong, weak or upstream. Repeatability is checked by reference-mode runs only, which still score null themselves.
  - Reference mode also stores its null row when no row for that key exists yet.
  - Reason: null re-scoring was about half the projected scoring time. The null result depends only on the key, so re-scoring it adds time and no information.
  - Effect on the B2a projection: per module, 1 null plus 3 writer runs at 1.2 × null, so 4.6 × null instead of 6.6 × null. For the 39 usable modules that is about 3.4 h (2.7 h primary) at 3 runs and 1 model.
- **Run tags:** `writer.py --tag` accepts only tags that have a spend cap:
  - `dry_run`: $2.00, ledger `runs/dry_run/ledger.jsonl`;
  - `pilot`: $2.50, ledger `runs/pilot/ledger.jsonl`.
  
  Each tag's guard sums only its own ledger. Tested in `test_writer.py` (`test_spend_caps_are_per_tag`).
- **Verification:**
  - **Stage 0 reproduction:** reference run `20261119T211811Z` used the modified harness: corpus_final lookup, sha256 and mutant-set pins, null storage. It matched `20261119T171136Z` exactly on all 16 Stage 0 rows: every `REPEAT_FIELDS` field and every per-mutant status and kill cause (GO). It also stored the 4 Stage 0 null rows.
  - **Writer run:** `B2b-20261119T213540Z-sonnet55-angelbot_context_acl` (Sonnet 5.5, effort low, tag `dry_run`, excluded from analysis) used 2 calls, 4,750 in / 2,060 out, $0.0301, 13 s. The scoring run stored angelbot_context_acl's null row (2 import-time kills, as in B2a).
    - Writer row: 25/25 tests kept, mutation score 0.861 (62/72), non-trivial 0.857, assertion-kill rate 0.681, line and branch coverage 1.00, weak-assertion rate 0.00.
  - **Reuse path:** the same writer suite was re-scored with results redirected to a scratch file (nothing appended to the results files). It reused the stored null, scored only the writer suite (58 s instead of 111 s), matched the original writer row on every `REPEAT_FIELDS` field, and added no row to the null store.
  - **Checks:** `test_writer.py` passes, including the saved-transcript isolation check. A key scan of 735 tracked, untracked and `.git` files found nothing. Dry-run spend is $0.1062 in total.

## 2026-11-19 — Stage B2c: `results_null.jsonl` is append-only

- Added to the append-only list in CLAUDE.md, next to `results.jsonl`, `results_mutants.jsonl` and `results_mutmut.jsonl`.
- Reason: writer rows point at a stored null row by key and run_id (`null_source`). Editing or deleting a stored row would silently change the trivially-killed set behind every writer row that reused it.

## 2026-11-19 — Stage B2c: pilot design (written before any pilot run)

- **Modules:** the 10 in `corpus_final.json` `pilot` (B2b): ai_video_generator_text, angelbot_context_acl, blackmamba_open_source_r_power_estimator, codex_memories_redaction, hangzhou_mahjong_ai_value, home_assistant_budget_bo_analytics, portable_hermes_agent_inline_markdown, role_aware_financial_age_sanitize, sentineledgeai_pdf, zagentic_doi.
- **Writer:** `claude-sonnet-5-5`, effort `low`, 3 runs per module (30 runs). Prompt exactly as DESIGN.md section 11, unchanged (`writer.py` reads it from DESIGN.md). Caps unchanged from B2a/B2b: 3 calls per run, `max_tokens` 32,000, 120,000 tokens per run, 15 minutes per run.
- **Tag and spend:** `pilot`, guard $2.50 over `runs/pilot/ledger.jsonl` (B2b). Expected spend about $1.
- **Status of the results:** a rehearsal. Pilot rows are tagged `pilot` and excluded from the final analysis unless a later decision says otherwise.
- **Run ids and order:** `B2c-pilot-sonnet55-<module>-<seed>`, seed labels `s1`, `s2`, `s3` (labels only; the API has no seed). Sequential and seed-major: `s1` on all 10 modules, then `s2`, then `s3`, so the first 10 runs cover every module once. Driver: `pilot.py`.
- **Resumable:** a run_id with a row in `results.jsonl` is skipped. A run dir with `meta.json` but no row is scored without calling the writer again. A run dir without `meta.json` stops the driver: the writer was interrupted after spend may have occurred, and the run is not retried.
- **Failed runs:** `failed_truncated`, `refusal`, `api_error` (after the SDK's fixed policy, `max_retries=2`, unchanged from B1) or `wall_cap`, or a run with no suite files, gets one row in `results.jsonl` with `arm_status = "writer_failed"`, the writer fields and null score fields (null, not 0, so a failed run cannot pass for a suite that killed nothing). It is never scored, retried or dropped. Whether failed runs count as 0 in the analysis is left to the analysis plan.
  - This replaces the B2a behaviour where `run_eval.py --writer-meta` exited on `failed_truncated` without a row, and crashed on an empty suite. Tested in `test_writer.py` (`test_failed_writer_run_gets_an_unscored_row`).
- **Scoring:** the full writer-mode harness (A2.1): test-level validity with 10 seeded reruns, the fixed mutant set, coverage, weak-assertion rate, category split. The stored null is reused where one exists. Only angelbot_context_acl has one (from the B2b dry run; the null key does not depend on the tag). The other 9 modules score and store their null on their first pilot run, as designed in B2b.
- **Isolation check:** `test_writer.reference_lines` now also reads `corpus/<module>/upstream_test.txt`. Before, the upstream tests of new modules were not part of the leak check. Run after the pilot on every saved transcript.
- **Upstream comparison:** of the pilot modules, only portable_hermes_agent_inline_markdown has a standalone upstream test. Upstream suites for new modules are still not wired into the scorer (B2b open item; the file imports `gui.inline_markdown` and must stay unedited), and the pilot does not wire them.
- **Stop rules:** the spend guard; the key (or its last 12 characters) found in any written results file, ledger or run file (byte scan after every run); more than 5 of the first 10 runs failed; Docker or the sandbox not responding, or a scoring NO-GO; any run whose writer plus scoring time passes 15 minutes.

## 2026-11-19 — Stage B2c: pilot results (rehearsal, tag `pilot`, excluded from analysis)

- **Completed:** 30 of 30 runs, sequential, no stop rule triggered. 0 failed runs (no truncation, refusal or API error; every call `end_turn`). 68 calls. Spend $1.6357 of the $2.50 guard (ledger and rows agree). No key bytes in any results file, ledger or run file. `test_writer.py` passes on all 30 pilot transcripts, with the upstream-test leak check now included. 9 null rows stored (angelbot reused the B2b one).
- **Per run:** mean $0.055 (range $0.017–$0.122), writer 22 s, scoring 98 s (first run per module ~155 s including the null; later runs ~80 s). Longest writer+scoring run: under 4 minutes.
- **Projection, 31 primary modules × 3 runs:** about $5.1 and 3.1 h sequential, at the pilot's per-run mean. The per-module cost spread is wide (ai_video_generator_text ~$0.10 per run), so this is a planning value.
- **Revise path:** 8 of 30 runs sent a second suite. 6 went from a failing pytest exit to exit 0. 2 were revisions of an already-passing suite. Every final suite kept 100% of its tests (858 tests, 0 wrong, 0 flaky).
- **Spread:** within-module min–max across 3 runs is 0.000–0.125. No module has a run at or above 0.95 (highest 0.917, role_aware_financial_age_sanitize, all 3 runs).
- **Observations for the freeze (no change made):**
  - Validity is at 100% on every run because the writer sees its own failures and fixes them before the final suite. As a measure it mainly separates runs that could not fix their failures.
  - Line coverage is 1.00 on 29 of 30 runs. The writer receives `coverage report -m` every iteration (DESIGN.md section 3), so coverage is something the writer can optimise directly, and it is at ceiling here.
  - The "unterminated code block" parse problem (portable_hermes_agent_inline_markdown s1) is a false positive: test strings contain literal ```` ``` ````. All 33 tests were extracted, and the problem is logged, not sent to the writer.
  - hangzhou_mahjong_ai_value scores 0.27–0.29 with full coverage. 65 of its 100 mutants are constants, 8 killed. The suites run every line but do not pin the value tables.
  - Writer DONE costs a full call that resends the whole conversation (about a third of a 3-call run's input tokens).
- **Upstream comparison:** not available. Only portable_hermes_agent_inline_markdown has a standalone upstream test, and upstream suites for new modules are not wired into the scorer.

## 2026-11-20 — Stage B3: scorer fixes (scorer_revision B3)

- **Scope:** no model API calls. No results row was edited or deleted. The four results files
  were hashed before any change, and their first 172 / 12,382 / 32 / 14 lines are byte-identical
  afterwards (prefix sha256 checked after the B3 runs; the files now have 200 / 14,554 / 32 / 19 lines). New data is appended rows (section h) or derived files in
  `derived/` (`derive_b3.py`, which records the sha256 of every input).
- **Versioning:** `harness_version` stays A2.1, and rows add `scorer_revision: "B3"`. Reason: the
  scores of every existing suite type are unchanged (h), and the stored-null key holds
  `harness_version`. Bumping it would re-score 14 stored nulls without changing them.
  `design_commit` pins the code of later runs.
- **a. Extraction** (`writer.fenced_blocks`, `writer.unparsable`):
  - Fences are read line by line. A Python block closes at the first ```` ``` ````-only line at
    which it parses with `ast`; if none parses, it closes at the first such line.
  - The B2c "unterminated code block" was the old odd-backtick count: portable_hermes s1 has
    literal ```` ``` ```` inside one-line test strings. Extraction itself was already right there.
  - Check: all 78 saved replies (dry run and pilot, 43 with files) extract byte-identical files
    (sha256 per file, before and after). No problem is reported, and every extracted file parses.
    `test_writer.Extraction` keeps this as a regression test against the `iter_<n>/` files on disk.
  - **Assumption, stated here:** `extraction_failed` applies to the *final* suite. A file that does
    not parse in an earlier iteration is recorded in `unparsable_by_iteration`, and the writer sees
    pytest's own error as before. Reason: the loop exists to let the writer fix its errors, and only
    the final suite is scored. `run_eval.py` re-checks with `ast` before scoring, which covers older
    `meta.json` files. `extraction_failed` is its own `arm_status` with null scores.
- **b. Upstream reference suites:** wired for every module whose upstream test passed standalone
  in B2a (`run_eval.upstream_spec`).
  - Primary: codebots_arena_elo, portable_hermes_agent_inline_markdown, synaptiq_retrieval,
    trace2task_experience, trace2task_experience_runtime, wtftd_war_thunder_full_t_blk.
  - Baseline: toposort and mergedeep (direct; Stage 0 wiring unchanged), plus addict (indirect,
    Stage 0).
  - The files run unedited. `sandbox/alias_plugin.py` maps the repo import path, derived with
    `ast` from the test's imports, to the scored module object.
  - The 17 direct upstream files that failed standalone are not rescued.
  - First reference run: reference run `20261120T054249Z` (untagged, appended): all 6 valid with every test kept. All-mutant scores 0.40–0.83 (DESIGN.md section 7.3). The 5 new null rows were stored.
- **c. Per-run fields:** `first_iteration_pass`, `iterations_used`, `constants_share`,
  `logic_mutants_n`, `constant_mutants_n`, `score_logic`, `score_constants`, and
  `design_commit` (null until `prereg-v1` exists).
  - Constants are `core/NumberReplacer` only. Boolean `True`/`False` swaps stay in the logic score.
  - Pilot backfill: `derived/b3_pilot_runs.jsonl`.
  - Logic mutants per module (`derived/b3_module_covariates.json`): **31 of 31 primary and 8 of 8
    baseline modules have at least 15.** The smallest is sustainability_score_config with 17. The
    count was taken from the fixed mutant sets only. No writer score was used to set the threshold.
- **d. Style profile** (`static_checks.style_profile`, `ast` only): written into new writer rows
  (`style_profile`). The pilot values are in `derived/b3_pilot_runs.jsonl`, with the per-module
  summary in `derived/b3_report.md`. Descriptive only.
- **e. Logging:** `writer.HttpLog` records every HTTP attempt through httpx event hooks.
  - Recorded: the status, `request-id` and retry headers, and no request headers.
  - Derived from it: `retry_count`, `api_events`, `request_ids`, `response_model`, `usage_full`,
    `peak_input_tokens_per_call` and `run_started_at`.
  - The SDK retry policy is unchanged (`max_retries=2`).
  - Tested against the real SDK with an `httpx2.MockTransport` (429, then a streamed 200; no
    network).
  - Pilot backfill: `response_model`, `usage_full` and the peak are taken from the saved replies.
    `request_ids` (null in all 30 pilot transcripts), `run_started_at`, `retry_count` and rate-limit
    events are marked `unavailable`.
  - Module covariates: physical lines, functions, classes, branches (coverage.py `num_branches`
    from the B2a null), and mutants available and used.
- **f. Gaming detector:** see DESIGN.md section 6.5 for the rule.
  - Writer suites: flagged tests are dropped as invalid (`tests_gaming`, `gaming_flag`,
    `gaming_flag_counts`).
  - Unit tests (`test_static_checks.py`): 14 synthetic cheats, each shown to pass on the original
    and fail on a mutant of a synthetic module, and 8 unconditional skip forms, all flagged. One
    file of ordinary tests (including `inspect.signature`, `monkeypatch` and conditional skips) is
    not flagged.
  - Two fixes came out of that testing:
    - `co_filename` was missed and is now caught;
    - the `<module>.py` literal matched `test_addict.py` (addict's upstream test), and now matches
      whole path components only, skipping docstrings and `__main__` blocks.
  - Counts, with rows unchanged: **0 tests flagged in the 30 pilot suites**, and 0 of 554 in the
    73 reference, constructed and upstream files.
  - End-to-end through the scorer: a synthetic toposort suite with 1 behavioural test and 2 source-hash tests, scored in writer mode in scratch. The 2 source-hash tests are dropped (`tests_gaming` 2), and the score comes from the behavioural test only (46 of 60).
- **g. Leakage audit** (`test_leakage.py`, Docker):
  - **Writer-loop sandbox: no finding.**
    - Setup: canaries planted in `tests/<m>/`, `corpus/<m>/`, `runs/`, the repo root (results and
      mutants files) and `sandbox/`; a canary key under `AGENT_EVAL_API_KEY` and
      `ANTHROPIC_API_KEY` in the host env; and a scoring container with a canary mutant list
      running at the same time.
    - Result: a probe walking the whole filesystem (≥1,000 files and ≥10 MB scanned, asserted) and
      the environment found no canary and no key.
    - `/work` held only the module and the probe. Nothing was left from the previous iteration (a
      fresh container each time). The probe ran as uid 10001 with no network.
    - Positive control: the same probe fails when a canary is put in the sandbox.
  - **Scoring sandbox, pre-B3 layout: findings, fixed.**
    - The pre-B3 runner was run in its old single-user layout with the same probe. As uid 10001,
      test code could:
      - append to, chmod, rename or shadow the module;
      - write the harness and its own suite;
      - read the mutant list (`/work/harness/mutants.json`) and cosmic-ray's session DB
        (`/tmp/cr_session.sqlite`, which lists every mutant);
      - see files from an earlier test run in `/tmp` and `/dev/shm`. pytest also keeps its last 3
        basetemp directories there.
    - Fix:
      - `/work` is root-owned, and the runner is exec'd as root with only `SETUID`, `SETGID` and
        `KILL`. Test processes run as uid 10001 with no capabilities.
      - The mutant list, validity seeds and the cosmic-ray config and session are in `/work/ctl`
        (root, 0700).
      - The test-writable places are wiped, as the test user, before every test run.
      - mutmut's test command goes through `sandbox/as_user.py`.
    - After the fix, the probe finds nothing on 3 consecutive runs, and the module is `root 644`.
  - **Writer prompt:** unchanged. `prompt_hash` is `9c407f6b…`, the same before and after the B3
    edits and the same as the pilot.
  - **Stored nulls:** all 14 rows carry the current env_id (`70d777ed…`). None is flagged for
    rescoring. `run_eval.py` now prints any row with another env_id (`null_store_env_check`).
  - **Known gap:** the detector is static. Test code can still read the module's source through
    the imported module object, for example via `__dict__` and code objects. DESIGN.md section 9.
- **h. Nothing moved** (run after f and g; `derived/b3_checks/verify_b3.py`,
  `derived/b3_verification.json`): 
  - Stage 0 reproduction `20261120T052758Z` (appended, untagged) matches `20261119T211811Z`
    exactly: all 16 rows and 972 per-mutant statuses and kill causes (GO).
  - The B2b verification run and the pilot suite portable_hermes s1, re-scored in scratch, match
    their stored rows on every `REPEAT_FIELDS` field and every per-mutant status (72 and 100).
  - The mutmut statuses on toposort equal A2.1 `20261119T171136Z`.
  - Nothing moved.
- **Test changed:** `test_writer.test_spend_caps_are_per_tag` pinned the cap table. It now also
  expects `full: 8.00`, the guard this stage adds on purpose. The existing caps are unchanged.
- **Repeatability check:** compares each module with the latest earlier untagged run that scored
  it. Before, it compared with the latest run overall, which would report "only in one run" for
  modules that run never had. Reference mode accepts `--tag full`, and only once `prereg-v1`
  exists.

## 2026-11-20 — Stage B3: pre-registration (`prereg-v1`)

Recorded in DESIGN.md sections 6–10. Every number comes from the derived files or the results
files named there.

- **Headline:** the logic score (all mutants except number-constant replacements), from the
  existing per-mutant results. A module counts toward the headline if it has at least 15 logic
  mutants (all 39 do). The all-mutant and constants-only scores are reported for every module.
  Validity and coverage are conditions, not results (pilot: 100% kept on 30 of 30, line coverage
  1.00 on 29 of 30).
- **Secondary measures:** first-iteration pass rate, iterations used, assertion-kill rate,
  weak-assertion rate, score by operator category, cost and time, and failed runs.
- **Descriptive:** the style profile, conditional on this prompt and loop.
- **Analysis plan:**
  - The module is the unit: per-module mean and range over 3 runs.
  - Across modules: mean and median with a 95% percentile bootstrap over modules (10,000
    resamples, `random.Random(20261117)`).
  - The primary and baseline sets are reported separately.
  - Sensitivity analyses: excluding AI-trace modules (13 primary); excluding constants-heavy
    modules (`constants_share` > 0.5: 3 primary); sampled vs all mutants on capped modules (20
    primary, 4 baseline); failed runs counted as 0.
  - Interpretation rule: differences below the pilot's mean within-module range of the logic score
    (**0.0368**) are not interpreted.
  - **Assumptions, stated here:**
    - Failed runs are excluded from score means and counted, with "count as 0" as a sensitivity
      analysis. B2c left this to the analysis plan.
    - The bootstrap settings.
    - The all-mutants sensitivity re-scores each capped module's s1 suite under an `-allmutants`
      run id, after the full run. That scoring mode is not implemented yet.
- **Analysis input rule:** only rows with tag `full`, `design_commit` equal to the `prereg-v1`
  commit and scorer_revision B3 (`analysis.py`, `test_analysis.py`).
- **Full run:**
  - Sonnet 5.5, effort low, prompt unchanged (`9c407f6b…`), 3 runs on each of the 31 primary and
    8 baseline modules, with fresh run ids. Tag `full`, spend guard $8.00.
  - Planning cost at the pilot's mean per run ($0.0545) is about $6.4.
  - Pilot runs are a replicate on 10 modules and a drift check, and are never reused.
- **Conditional arms:**
  - `haiku_arm`: Haiku 5.5, after a clean Sonnet run, about $1–2.
  - `gemini_arm`: one Gemini free-tier model. Preconditions: a cutoff before 2026-07-01 with the
    source recorded, free-tier limits that cover the run, and a separate tested client. Free-tier
    data may be used by the provider. No parity claim.
  - `no_coverage_feedback` ablation: pilot modules, after a clean Sonnet run.
- **Stop rule:** passed for the pilot (signal found; spend $1.6357 under $2.50). Kept for the full
  run.
- **Disclosure:** the logic-score headline, the 15-logic-mutant minimum and the 0.5 constants
  threshold were chosen after seeing pilot results. hangzhou_mahjong_ai_value (65 of 100 mutants
  are number constants; all-mutant 0.270–0.290 against logic 0.543–0.600) triggered the
  discussion. The pilot is excluded from the final analysis, and the all-mutant score is reported
  next to the logic score. The write-up states this.
- **Freeze:** the commit tagged `prereg-v1` is recorded in the entry below (it cannot appear in its own commit).

## 2026-11-20 — Stage B3: `prereg-v1` commit

- `prereg-v1` is a local tag on commit `c530e5168b2d14d1f473ae316039ac9b27d52929` (not pushed). Rows of the full run record it as `design_commit`.

## 2026-11-20 — Stage B4: full-run driver (`run_full.py`) and checkpoint stop (deviation log)

- **Driver:** `run_full.py`, one resumable command. Preflight on every start, a plan built once (`full_plan.json`, 117 runs, seed 20261120, never reshuffled), and the hard stops of DESIGN.md section 10 plus the B4 additions (response_model change, more than 10% failed once 20 are done, a watched code or corpus file changed). Tested without API calls in `test_run_full.py`.
- **Container cleanup:** the sandbox containers carry no Docker label, so the preflight matches them by name (`ate-<corpus module>-<8 hex>`) and the project image, and removes only those, by name. The project creates no volumes.
- **Checkpoint stop at run 5 (`B4-full-sonnet55-skijack_ast-s3`):** the scoring exit was 1, and the driver stopped with "scoring NO-GO".
  - Cause: skijack_ast has 0 branches (`derived/b3_module_covariates.json`), so `branch_coverage` is null (A2.1: 0/0 shares are null). The console summary in `run_eval.main` formats it with `:.2f` and raises `TypeError`. That happens after every row and the null were appended, and before the GO/NO-GO line.
  - The rows are complete and correct. Results files were only appended to.
  - The same crash will happen on every run of the two branchless modules, skijack_ast and sustainability_score_config (6 planned runs).

## 2026-11-20 — Stage B4b: tolerated branchless summary crash (deviation log)

- **Handling:** only `run_full.py`, its tests and this file changed. The writer, scorer (`run_eval.py`), sandbox, prompt (DESIGN.md) and corpus files are byte-identical to `prereg-v1` (blob hashes checked by the preflight on every start). No results row was edited.
- **Rule** (`run_full.tolerance_problems`). A scoring exit 1 is accepted only if all of these hold:
  - the module has 0 branches in `derived/b3_module_covariates.json`, which the preflight now also checks against the tag;
  - the output ends in exactly one traceback whose frames (file, line, function, source line) and exception line equal run 5's saved `scoring_log.txt`: `run_eval.py:1000 <module>`, then `run_eval.py:954 main`, then `TypeError: unsupported format string passed to NoneType.__format__`;
  - the run's full rows are present: the writer row, plus the null row when this run stored the null (a run that reuses a stored null has only the writer row, by design, B2b);
  - each row has the same field set as the other scored full rows of its `test_file`, with `arm_status` ran, `design_commit` prereg-v1, `scorer_revision` B3 and `harness_version` A2.1;
  - the score fields are non-null, except `score_constants`, which must be null exactly when the module has 0 constant mutants (0/0);
  - `coverage.branch_coverage` is null (not 0) with `num_branches` 0;
  - the stored-null env check that `main()` skipped (`null_store_env_check`) is empty.
  
  Any other exit 1 stays a hard stop. The run limit (15 min) covers the module-budget check that `main()` also skipped.
- **Record:** each tolerated run is appended to `derived/b4_tolerated_runs.jsonl` and counted in `runs/full/progress.txt`. On every start the driver re-checks any scored run whose `driver.json` has a non-zero scoring exit and is not yet recorded. Run 5 was checked this way and qualified.
- **Stopped state:** `runs/full/STOPPED.txt` from run 5 was renamed to `runs/full/STOPPED-run5-20261120.txt` (kept as a record) so the preflight can start.
- **Analysis-plan note:** branch coverage is null for branchless modules (skijack_ast, sustainability_score_config). Those modules are excluded from branch-coverage means, and the n behind each branch-coverage mean is reported. Branch coverage is a condition, not a result (DESIGN.md section 6.2), and no other measure changes.

## 2026-11-23 — Stage B4c: staged execution, wave 1 defined before any further run (deviation log)

- **Reason:** API budget. The Console balance is $2.93 after the checkpoint's $0.34, below the planning cost of the remaining runs.
- **Rule** (`run_full.wave1_modules`, written before any run after the checkpoint): wave 1 is all 3 planned runs of 7 primary and 7 baseline modules, drawn with a fresh `random.Random(20261123).sample(sorted names, 7)` on each of the two sorted lists of usable modules in `corpus_final.json` (31 primary, 8 baseline). Wave 2 is every other planned run. The 39-module design and `full_plan.json` (117 runs, seed 20261120) are unchanged; runs keep their plan order inside each wave.
- **Wave 1 draw:**
  - Primary: trace2task_experience, role_aware_financial_age_sanitize, wtftd_war_thunder_full_t_minimap, skijack_ast, intent_relations, blackmamba_open_source_r_vision, trace2task_experience_runtime.
  - Baseline: toposort, databroker_pivot, moirai_abstract_process_handler, heapdict, addict, depthcharge_log, mergedeep.
  - 42 runs; 2 already done in the checkpoint (addict-s2, skijack_ast-s3), 40 remaining.
- **Driver:** `--wave 1` runs only the wave-1 run_ids not yet completed; `--wave all` (default) runs every one not completed. `--spend-cap X` is a hard stop on cumulative `full` spend in `runs/full/ledger.jsonl`, checkpoint included: the same before-run check as the outer guard (spend + largest run so far would pass X) and the after-run check (spend passed X). The $8.00 guard stays the outer limit (`--spend-cap` above 8 is rejected). At start the driver prints the wave-1 modules, completed and remaining runs, and an estimate of the remaining writer cost (each module's mean per-run cost from pilot and full `meta.json` where known, else the mean over all known runs), and refuses to start (exit 2, no STOPPED.txt, no writer call) if spend so far plus that estimate exceeds the cap. At this entry: wave 1 estimate $2.04, projected total $2.38. Tested without API calls in `test_run_full.py` (`Waves`).
- **Unchanged:** writer, scorer, sandbox, prompt and corpus files are byte-identical to `prereg-v1` (preflight blob-hash check). No results row was edited.
- **Reporting:** the 9 checkpoint runs count toward the full set either way. If wave 2 is never run, the results are reported as a 14-module study (7 primary, 7 baseline), with the staged execution and the budget reason stated as a limitation.

## 2026-11-23 — Stage B5: analysis code (`analysis.py`, `test_analysis.py`)

- **Scope:** no model API calls, no writer or scorer runs. Only `analysis.py`, `test_analysis.py` and this file changed. The pre-registered loader (`allowed`, `select_rows`, `check_rows`, `load_analysis_rows`) and its 6 tests are unchanged from `prereg-v1`. `analysis.py` is not among the driver's frozen paths (`run_full.FROZEN_PATHS`). The file names follow DESIGN.md section 8.2.
- **Inputs (read-only; sha256 printed on every run):**
  - `results.jsonl`: analysis rows. Allowlist: tag `full`, `design_commit` = prereg-v1 (`c530e516…`), scorer_revision B3, then writer rows only. Null and other rows are counted and excluded.
  - `results_mutants.jsonl`: recomputes and checks `score_logic` for every allowlisted run (49 of 49 equal at this entry), and gives the pilot logic scores for the drift check.
  - `corpus_final.json` (sha256 `4d57f98e…`): set membership (primary or baseline) and `flags.ai_trace` only. Results rows do not carry these.
  - `full_plan.json` (sha256 `e125da58…`): planned run ids per module.
- **All-planned-runs rule (clarification of DESIGN.md section 8.3, not a deviation):** section 8.3 defines per-module values over a module's 3 runs. A module enters the across-module statistics, the within-module range and every sensitivity analysis only if each of its planned run ids in `full_plan.json` has an allowlisted writer row (scored or failed). The count comes from the plan and is not hard-coded.
  - Modules with fewer rows stay allowlisted and counted. They appear in a separate table, "partial modules (descriptive, not in across-module statistics)", with per-run values, run counts, the missing seeds and the reason.
  - At this entry: 20 allowlisted modules (49 rows). 14 are complete (7 primary, 7 baseline, 42 rows). 6 primary modules (7 rows) are excluded for incompleteness: ai_video_generator_safety, blackmamba_open_source_r_power_estimator, hangzhou_mahjong_ai_value, synaptiq_retrieval and wtftd_war_thunder_full_t_blk (1 of 3 each), and zagentic_ir_schema (2 of 3). These are checkpoint runs of modules outside wave 1 (B4c).
  - A failed run counts as present for completeness. It is then excluded from score means and counted, as section 8.3 says.
- **Bootstrap:** module-level percentile intervals for the mean and the median. 10,000 resamples with replacement (`rng.choices`), 2.5 and 97.5 percentiles by linear interpolation between closest ranks. Every interval starts a fresh `random.Random(20261117)` and resamples from the sorted per-module values, so an interval depends only on the values, not on call order or input order. Every statistic prints its n.
- **Hash-seed bug, fixed:** the first B5 commit (`5d93d3a`) built some bootstrap inputs by iterating a Python `set` of module names. Set order varies with PYTHONHASHSEED, so the seeded resamples, and hence the intervals (up to about 0.004), varied between processes. Point estimates were unaffected. Fix in `ea87e20`: the bootstrap sorts its input. `test_analysis` checks that the full output is byte-identical under several PYTHONHASHSEED values.
- **Drift check:** a separate code path reads tag-`pilot` writer rows only for the descriptive drift table (DESIGN.md section 8.3). Pilot logic scores are recomputed from `results_mutants.jsonl`, because pilot rows predate `score_logic`, and are tested against `derived/b3_pilot_runs.jsonl` (30 of 30 equal). Pilot rows never pass the allowlist. The table is per module, covers every allowlisted module that was also in the pilot, and marks partial modules.
- **Other definitions used:**
  - The within-module range is the mean of max − min of the logic score over each complete module's scored runs. It is shown next to the pre-registered 0.0368.
  - Branch-coverage means exclude modules with null branch coverage (branchless, B4b), with n printed.
  - The constants-only score's n counts modules with a non-null value.
  - The style profile gets the same across-module summary. It is descriptive and never scored.
- **Exploratory sensitivities, labelled "NOT PRE-REGISTERED, post-hoc" in the output:**
  - (a) without the runs that stopped at `max_iterations`;
  - (b) without skijack_ast (logic score 1.0 on every run);
  - (c) `mutation_score_nontrivial` per module and across modules.
- **Open items:**
  - Sensitivity 3 (sampled vs all mutants) is not available. The `-allmutants` scoring mode is not implemented (DESIGN.md section 12).
  - The upstream comparison is not available. The tag-`full` reference-mode run of the upstream suites (DESIGN.md section 10.5) has not been done.
  - Wave 2 (B4c) has not been run.

## 2026-11-23 — Wrap-up (v1)

- **Scope:** no model API calls, no writer or scorer runs. Only DECISIONS.md and the new WRITEUP.md changed. Frozen `prereg-v1` files are unchanged. The results files are byte-identical to the backup `~/agent-test-eval-backups/20261123-1417` (same size, same lines: 258 / 19,408 / 32 / 28).
- **The study is reported as v1: 14 complete modules (7 primary, 7 baseline), 42 runs**, under the all-planned-runs rule (Stage B5). The 6 partial checkpoint modules (7 runs: ai_video_generator_safety, blackmamba_open_source_r_power_estimator, hangzhou_mahjong_ai_value, synaptiq_retrieval, wtftd_war_thunder_full_t_blk, zagentic_ir_schema) are shown descriptively only and are not in any across-module statistic.
- **B6a** (`66bcce0`, post-hoc): the corrected non-trivial assertion-kill rate also drops null-killed mutants from the numerator. It equals the stored value on 42 of 42 runs, because no null-killed mutant was killed by an assertion. The stored field is unchanged.
- **Not run, by decision (B6b):**
  - Sensitivity 3, sampled vs all mutants (DESIGN.md 8.3). Cost/benefit: the B6 scoping estimated about 96 min of scoring for the s1 suites of the 8 capped complete modules, and about 197 min for all 3 suites. wtftd_war_thunder_full_t_minimap alone (2,157 mutants) would exceed the 20-min module budget. The check would be expected to shift decimals, not conclusions. Not implemented; `allmutants.py` was not built.
  - The upstream comparison (DESIGN.md 7.3, 10.5). Only 5 of the 14 complete modules have an upstream line (trace2task_experience, trace2task_experience_runtime, toposort, mergedeep, addict), too few for more than anecdotes. The tag-`full` reference-mode run was not done.
- **Wave 2 not run (budget, Stage B4c):** every planned run outside wave 1, including the missing runs of the 6 partial modules. `full_plan.json` (117 runs) is unchanged. Results are reported as the 14-module study that B4c names, with the staged execution and the budget reason stated as limitations.
- **Conditional arms not run:** `haiku_arm` (Haiku 5.5), `gemini_arm` (one Gemini free-tier model) and the `no_coverage_feedback` ablation (DESIGN.md 10, items 6–8). Their preconditions (a clean, complete Sonnet full run) were not met, and no budget was allocated.
- **Write-up:** `WRITEUP.md`. Every number in it is copied from a fresh `analysis.py` run at this entry.

## 2026-11-23 — Wrap-up: reproducibility fixes and the host `__pycache__` finding

- **Scope:** no model API calls, no writer or scorer runs, nothing re-run to investigate. Frozen `prereg-v1` files are unchanged. Changed: `analysis.py`, `test_analysis.py` (post-prereg tests only; the 6 pre-registered tests are unchanged), the new `conftest.py`, README.md, LICENSE (holder: Safari Fred Gisa) and this file.
- **Commit fallback** (`analysis.prereg_commit`): when the `prereg-v1` tag is missing (a copy without git history), the analysis uses the recorded commit `c530e5168b2d14d1f473ae316039ac9b27d52929` and says so on stderr. stdout, and so every table, is unchanged. If the tag exists, it must equal that hash or the analysis stops. Only `main()` and the post-prereg tests use it; the pre-registered loader is unchanged.
- **Published copy:**
  - Ships `corpus/metadata.json`: Stage 0 metadata only, no third-party code.
  - Run 5's `scoring_log.txt` is **not** shipped. It holds no third-party source (0 module lines; only `run_eval.py` frames). But it records absolute host paths, and `run_full.parse_traceback` accepts frames only from the current checkout's `run_eval.py`, so the 11 tests that use it cannot pass in a copy at any other path anyway.
  - `conftest.py` skips each Tier 2 test, with the reason, when its specific input (Stage 0 module, fetched module, run 5 log, `prereg-v1` tag) is absent. In this working copy nothing is skipped.
  - README.md documents Tier 1 (re-run the analysis on the shipped results) and Tier 2 (re-scoring: Docker plus a fetched corpus; Stage 0 placed by hand from `corpus/metadata.json`).
- **Finding: host-compiled `.pyc` files in `corpus/` and `tests/`** (untracked, git-ignored, not in any export). From file birth and modification times, `.pytest_cache`, git log and an `ast` read of the collected files:
  - All are `cpython-310`, so they come from the host `.venv` (Python 3.10.14). The scoring sandbox runs Python 3.12, so none came from the sandbox.
  - **2026-11-17 21:12 and 23:38 EST, Stage 0:** `corpus/{toposort,heapdict,mergedeep}/__pycache__` appeared 1 min after those module files (21:11), and `corpus/addict/__pycache__` 38 s after `addict.py` (23:38:12). Both are before the Stage 0 commits `8bc0f6a` (21:31) and `74d112f` (00:01). Pytest-tagged `.pyc` of the Stage 0 strong, weak, null and addict upstream suites are from the same minutes. So during Stage 0 the 4 baseline modules (PyPI packages, wheel sha256 checked) were imported, and their code executed, on the host, with their suites run by host pytest. This predates the "never import or execute downloaded code outside the sandbox" rule (CLAUDE.md, added in `ffdefc7`, 2026-11-19 12:38) and the newer-module corpus.
  - **2026-11-23 01:27 EST:** a host pytest run from the repo root, 1 min before the B4c commit `aba10ac` (01:28). It collected every test file: `.pytest_cache/v/cache/lastfailed` lists 158 files (runs 98, tests 59, derived 1), all failed at collection. No corpus `.pyc` is newer than 2026-11-18, so no corpus module was imported. In all 158 files, only imports, definitions and constants come before the module import, so only stdlib and pytest imports ran. This run created the `.pyc` of 43 null suites and of the toposort, heapdict and mergedeep upstream tests.
  - **Not determined:** the exact commands. Shell history was not read.
  - **Effect on results: none.** Scoring copies source files only into the sandbox (`.pyc` are never sent), and the results files are append-only and match the backups.
  - **Action:** none on the files. Since then, tests are run by naming the test files (never a bare `pytest` at the root).
