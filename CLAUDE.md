# CLAUDE.md

Standing rules for this repo. The design is in DESIGN.md and the reasons are in DECISIONS.md.

- Never edit or delete `results.jsonl` (or `results_mutants.jsonl` / `results_mutmut.jsonl` / `results_null.jsonl`). They are append-only.
- Commit locally. Do not push.
- The model API key lives only on the host. Never put it in the repo, in files, or in the sandbox.
- Never run Docker prune commands (`docker system/image/container/volume prune`) or anything else that can touch other Docker projects. Remove only this project's own containers (`ate-<module>-*`), by name.
- Downloaded code is untrusted. Read it with `ast` or as text. Never import or execute it outside the sandbox.
- The writer never sees mutants, scores, reference suites (null/weak/strong/upstream) or upstream tests.
- No composite score. Each measure is reported on its own.
