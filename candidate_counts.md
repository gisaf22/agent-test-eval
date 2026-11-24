# Stage A1b candidate counts

Generated 2026-11-19T15:12:02+00:00 by `corpus_select.py` (seed 20261118, Python 3.12.13).
**Estimates from a seeded sample, not totals.** Each frame examined at most 300 GitHub repos. Rules and their order are in DECISIONS.md (Stage A1b).

| bucket | repos examined | repos with ≥1 candidate | repo rate (95% CI) | candidates after cap | with upstream test found |
|---|---|---|---|---|---|
| older | 300 | 4 | 1.3% (0.5%–3.4%) | 5 | 5 |
| newer_since_2025-09-01 | 300 | 46 | 15.3% (11.7%–19.8%) | 69 | 33 |
| newer_since_2026-02-01 | 300 | 30 | 10.0% (7.1%–13.9%) | 48 | 29 |
| newer_since_2026-07-01 | 300 | 22 | 7.3% (4.9%–10.9%) | 37 | 24 |

## Removed by each rule (after dates; per bucket)

| bucket | rule 4 follow renames | rule 3 no upstream test | rule 8 mutation trace | rule 6 duplicate | rule 7 cap |
|---|---|---|---|---|---|
| older | 0 | 64 | 2 | 0 | 3 |
| newer_since_2025-09-01 | 0 | 0 | 0 | 5 | 105 |
| newer_since_2026-02-01 | 15 | 0 | 0 | 5 | 77 |
| newer_since_2026-07-01 | 0 | 0 | 0 | 5 | 43 |

Rule 8: 1 cloned repos have a committed mutation-testing trace; 1 of them had candidates and were removed.

Newer windows are nested. Rule 3 applies only to older; for newer, "with upstream test found" is recorded, not required.
Cross-frame finds (counted in no row above): {'older-frame→newer_since_2025-09-01': 1, 'older-frame→newer_since_2026-02-01': 1, 'older-frame→newer_since_2026-07-01': 1}
Sample overlap with Stage A1 (same seed, search re-queried): {'older': '290/300', 'newer': '232/300'}

## File-level funnel (first failing rule, per sample frame)

**older** repo outcomes: archived 14, has_candidates 6, licence_not_allowed 238, no_candidates 42

**older** files: candidate 11, file_licence_conflict 4, io_builtin 5, io_module 99, io_name 9, line_count 951, non_stdlib_import 551, older_no_upstream_test 64, relative_import 116, test_file 272, unparseable 24, vendored_path 22

**older** rule 1 effect vs A1's splitlines count: {'in_by_splitlines_out_by_physical': 0, 'out_by_splitlines_in_by_physical': 0}

**newer** repo outcomes: archived 1, has_candidates 46, licence_not_allowed 161, no_candidates 92

**newer** files: candidate 179, io_builtin 9, io_module 955, io_name 11, line_count 4219, non_stdlib_import 3379, older_no_upstream_test 1, relative_import 270, test_file 1215, vendored_path 1

**newer** rule 1 effect vs A1's splitlines count: {'in_by_splitlines_out_by_physical': 0, 'out_by_splitlines_in_by_physical': 0}

