"""Wrap-up (v1): skip Tier 2 tests whose inputs are absent, with the reason. Nothing is skipped in a full
working copy. A published copy ships no third-party code (corpus/), no git history (prereg-v1 tag) and not
run 5's scoring log (it records absolute host paths). See README.md, "Reproducibility". The test files
themselves are unchanged. Applies under pytest only (`python -m unittest` does not read this file)."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
STAGE0 = ("toposort", "heapdict", "mergedeep", "addict")
RUN5_LOG = ROOT / "runs" / "full" / "B4-full-sonnet55-skijack_ast-s3" / "scoring_log.txt"


def corpus(*modules):
    return [ROOT / "corpus" / m / f"{m}.py" for m in modules]


def tag_missing():
    r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", "refs/tags/prereg-v1^{commit}"],
                       capture_output=True, text=True)
    return r.returncode != 0


# test node id prefix -> (required files, or a callable that is True when the requirement is missing; reason)
STAGE0_WHY = ("Tier 2: needs the Stage 0 module corpus/toposort/toposort.py (not auto-fetched; pinned by version "
              "and sha256 in corpus/metadata.json)")
REQUIREMENTS = {
    **{f"test_writer.py::{t}": (corpus("toposort"), STAGE0_WHY) for t in (
        "SyntheticLoop::test_detector_catches_leaks",
        "SyntheticLoop::test_max_tokens_reply_fails_run_without_parsing",
        "SyntheticLoop::test_spend_caps_are_per_tag",
        "Extraction::test_final_suite_that_does_not_parse_is_extraction_failed_and_unscored",
        "ApiLogging::test_fake_client_marks_retry_count_unavailable",
        "ApiLogging::test_retry_and_rate_limit_are_logged")},
    "test_writer.py::SyntheticLoop::test_payloads_clean_and_sandbox_holds_only_module_and_writer_files": (
        corpus(*STAGE0, "angelbot_context_acl"),
        "Tier 2: needs the 4 Stage 0 modules and corpus/angelbot_context_acl (run corpus_build.py fetch for the latter)"),
    **{f"test_leakage.py::LeakageAudit::{t}": (corpus("toposort"), STAGE0_WHY + "; also needs Docker") for t in (
        "test_scoring_sandbox_protects_module_and_mutants",
        "test_writer_loop_sandbox_sees_no_canary_key_or_earlier_state")},
    "test_run_full.py::BranchlessSummaryCrash::": (
        [RUN5_LOG], "Tier 2: needs run 5's scoring_log.txt (not published: it records absolute host paths)"),
    "test_run_full.py::Run5::": (
        [RUN5_LOG], "Tier 2: needs run 5's scoring_log.txt (not published: it records absolute host paths)"),
    "test_run_full.py::Preflight::test_frozen_files_match_tag": (
        tag_missing, "Tier 2: needs the prereg-v1 git tag (a published copy has no git history)"),
}


def pytest_collection_modifyitems(config, items):
    cache = {}
    for item in items:
        for prefix, (need, why) in REQUIREMENTS.items():
            if item.nodeid.startswith(prefix):
                if prefix not in cache:
                    cache[prefix] = need() if callable(need) else [str(p.relative_to(ROOT)) for p in need if not p.exists()]
                missing = cache[prefix]
                if missing:
                    detail = "" if missing is True else f" (missing: {', '.join(missing)})"
                    item.add_marker(pytest.mark.skip(reason=why + detail))
