#!/usr/bin/env python3
"""Stage A1c: freeze the corpus input from the existing A1b sample into candidates_frozen.json.

No GitHub search, no model API calls. Inputs:
  - candidates.json (A1b output, seed 20261118) and the A1b clones it was built from (--workdir)
  - the four Stage 0 modules (corpus/metadata.json); their upstream repos are cloned fresh
    (blob:none, full history) into --stage0-workdir, a new empty directory outside the project,
    and run through corpus_select's own rules (evaluate_repo, unchanged).
Downloads are read as text and parsed with `ast`; nothing downloaded is imported or run.
Later stages read candidates_frozen.json and never rerun the search. Run in isolated mode:

    python3.12 -I corpus_freeze.py --workdir <A1b clone dir> --stage0-workdir <new empty dir>
"""

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))          # -I drops the script dir; corpus_select is our own code
import corpus_select as cs                # noqa: E402

PRIMARY_WINDOW = "newer_since_2026-07-01"   # Sonnet 5.5 cutoff June 2026
HUMAN_CERTAIN_MAX = date(2022, 11, 30)      # last change on or before this date (UTC)

STAGE0_REPOS = {   # name -> (clone URL, GitHub full_name or None)
    "toposort": ("https://gitlab.com/ericvsmith/toposort.git", None),
    "heapdict": ("https://github.com/DanielStutzbach/heapdict.git", "DanielStutzbach/heapdict"),
    "mergedeep": ("https://github.com/clarketm/mergedeep.git", "clarketm/mergedeep"),
    "addict": ("https://github.com/mewwts/addict.git", "mewwts/addict"),
}

# ---------------------------------------------------------------- AI-trace rule (4b)
AI_TRACE_BASENAMES = {"claude.md", "agents.md", ".cursorrules"}
AI_MARKERS = re.compile(
    r"co-authored-by:[^\n]*\b(claude|anthropic|copilot|cursor|codex|openai|chatgpt|gpt-\d|gemini|devin|"
    r"aider|windsurf|codeium|jules)\b"
    r"|generated (?:with|by) \[?(?:claude|copilot|cursor|codex|chatgpt|gpt|gemini|aider|devin|windsurf|ai)\b"
    r"|noreply@anthropic\.com|cursoragent@cursor\.com|copilot-swe-agent|devin-ai-integration|"
    r"google-labs-jules|claude\.ai/code|claude code|chatgpt\.com/codex|^aider: ",
    re.I | re.M)
AI_IDENTITY = re.compile(r"^(claude|copilot|cursor agent|codex)$|\[bot\].*(copilot|devin|jules|codex|claude)|"
                         r"(copilot|devin|jules|codex|claude).*\[bot\]|noreply@anthropic\.com|cursoragent@", re.I)


def ai_tree_hits(paths):
    hits = []
    for p in paths:
        parts = p.split("/")
        if parts[-1].lower() in AI_TRACE_BASENAMES:
            hits.append(p)
        elif ".cursor" in parts[:-1]:
            hits.append(p)
        elif p.lower().endswith(".github/copilot-instructions.md"):
            hits.append(p)
    return hits


def ai_commit_hits(dest, paths, follow_paths=()):
    fmt = "--format=%H%x00%an%x00%ae%x00%cn%x00%ce%x00%B%x1e"
    seen, hits = set(), []
    jobs = [(p, False) for p in paths] + [(p, True) for p in follow_paths]
    for p, follow in jobs:
        r = cs.git(["log", fmt] + (["--follow"] if follow else []) + ["--", p], cwd=dest, timeout=600)
        if r.returncode != 0:
            hits.append({"path": p, "error": "git log failed"})
            continue
        for rec in r.stdout.decode("utf-8", "replace").split("\x1e"):
            rec = rec.strip("\n")
            if not rec:
                continue
            sha, an, ae, cn, ce, body = (rec.split("\x00") + [""] * 6)[:6]
            if sha in seen:
                continue
            seen.add(sha)
            m = AI_MARKERS.search(body)
            ident = next((x for x in (an, ae, cn, ce) if AI_IDENTITY.search(x)), None)
            if m or ident:
                hits.append({"sha": sha, "path": p, "match": m.group(0) if m else f"identity:{ident}"})
    return hits, len(seen)


# ---------------------------------------------------------------- possible-copy rule (3)
_COPYRIGHT = re.compile(r"copyright\s*(?:\(c\)|©)?\s*(?:\d{4}(?:\s*[-–,]\s*\d{4})*\s*,?)\s*(.+)", re.I)
_COPYRIGHT_NOYEAR = re.compile(r"copyright\s*(?:\(c\)|©)\s*(.+)", re.I)
_HOST_URL = re.compile(r"(?:github\.com|gitlab\.com|bitbucket\.org)[/:]([\w.-]+)/([\w.-]+)", re.I)
_PROVENANCE = re.compile(
    r"\b(?:copied|adapted|taken|borrowed|ported|derived|modified|forked|vendored|extracted|lifted)\s+from\b"
    r"|\bthis\s+(?:file|module|code)\s+is\s+(?:part\s+of|from)\b"
    r"|\b(?:identical|exact|verbatim)\s+copy\b", re.I)
_HOLDER_STOP = {"inc", "ltd", "llc", "and", "its", "affiliates", "the", "all", "rights", "reserved", "team",
                "contributors", "authors", "corp", "corporation", "gmbh", "company", "foundation", "project",
                "copyright", "holders", "holder", "author", "owner", "year", "fullname", "name"}
_ORG_MARKER = re.compile(r"\b(inc|ltd|llc|corp|corporation|gmbh|foundation|team|project|contributors|authors|"
                         r"affiliates|developers|university|institute|lab|labs)\b", re.I)


def _norm(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def header_text(text):
    """Leading comments and docstring(s): lines before the first statement that is not a string
    expression or a `from __future__` import, capped at 40 lines."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    end = len(lines)
    try:
        for node in ast.parse(text).body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            end = node.lineno - 1
            break
    except SyntaxError:
        pass
    return "\n".join(lines[:min(end, 40)])


def _holder_mismatch(holder, owner, repo):
    h = _norm(holder)
    if re.search(r"[\[<{]", h) and re.search(r"year|name|owner|holder", h):
        return False                                   # unfilled template placeholder
    ident = {re.sub(r"[^a-z0-9]", "", _norm(owner)), re.sub(r"[^a-z0-9]", "", _norm(repo))}
    ident_tokens = {t for x in (owner, repo) for t in re.split(r"[^a-z0-9]+", _norm(x)) if len(t) >= 3}
    toks = [t for t in re.split(r"[^a-z0-9]+", h) if len(t) >= 3 and t not in _HOLDER_STOP and not t.isdigit()]
    if not toks:
        return False
    joined = re.sub(r"[^a-z0-9]", "", h)
    if any(t in i for t in toks for i in ident) or any(t in joined for t in ident_tokens):
        return False
    return True


def copy_signals(text, owner, repo, licence_file=False):
    sig = []
    for line in text.split("\n"):
        m = _COPYRIGHT.search(line) or _COPYRIGHT_NOYEAR.search(line)
        if m:
            holder = m.group(1).strip().strip("\"'#*")
            if _holder_mismatch(holder, owner, repo) and (not licence_file or _ORG_MARKER.search(holder)):
                sig.append(f"copyright_holder:{holder[:80]}")
    for m in _HOST_URL.finditer(text):
        o, r = m.group(1).lower(), re.sub(r"\.git$", "", m.group(2).lower()).rstrip(".")
        if (o, r) != (owner.lower(), repo.lower()):
            sig.append(f"url:{m.group(1)}/{m.group(2)}")
    if not licence_file:
        for m in _PROVENANCE.finditer(text):
            sig.append(f"phrase:{m.group(0)}")
    return sorted(set(sig))


# ---------------------------------------------------------------- helpers
def sha256_file(fp):
    return hashlib.sha256(fp.read_bytes()).hexdigest()


def last_change(dest, path):
    r = cs.git(["log", "-1", "--format=%H %cI", "--", path], cwd=dest)
    out = r.stdout.decode().split()
    return (out[0], out[1]) if r.returncode == 0 and out else (None, None)


def pick_test(module_path, direct, all_tests):
    """Prefer direct tests; within the pool prefer stem equality, then stem containment, then path order."""
    if direct:
        kind, pool = "direct", sorted(direct)
    elif all_tests:
        kind, pool = "indirect", sorted(all_tests)
    else:
        return None, "none"
    stem = Path(module_path).stem if Path(module_path).stem != "__init__" else Path(module_path).parent.name
    def tstem(p):
        s = Path(p).stem
        return re.sub(r"^test_|_test$", "", s)
    for pred in (lambda p: tstem(p) == stem, lambda p: stem in tstem(p)):
        hit = [p for p in pool if pred(p)]
        if hit:
            return hit[0], kind
    return pool[0], kind


def owner_repo(url):
    parts = url.rstrip("/").split("/")
    return parts[-2], parts[-1]


def flags_for(rec, dest, licence_files):
    """Rules 3 (possible copy) and 4 (human-certain, ai_trace) for one candidate record."""
    owner, repo = owner_repo(rec["repo_url"])
    text = (dest / rec["path"]).read_bytes().decode("utf-8-sig")
    sig = copy_signals(header_text(text), owner, repo)
    for lf in licence_files:
        fp = dest / lf
        if fp.is_file() and not fp.is_symlink():
            sig += [f"licence_file:{s}" for s in copy_signals(fp.read_bytes().decode("utf-8", "replace"),
                                                              owner, repo, licence_file=True)]
    rec["possible_copy"] = bool(sig)
    rec["possible_copy_signals"] = sorted(set(sig))

    t = rec["upstream_test"]
    if t:
        rec["upstream_test_last_change_sha"], rec["upstream_test_last_change_date"] = last_change(dest, t)
        fp = dest / t
        rec["upstream_test_sha256"] = sha256_file(fp) if fp.is_file() else None
    else:
        rec["upstream_test_last_change_sha"] = rec["upstream_test_last_change_date"] = None
        rec["upstream_test_sha256"] = None
    rec["baseline_human_certain"] = bool(
        t and rec["upstream_test_last_change_date"]
        and cs.utc_date(rec["last_change_date"]) <= HUMAN_CERTAIN_MAX
        and cs.utc_date(rec["upstream_test_last_change_date"]) <= HUMAN_CERTAIN_MAX)

    r = cs.git(["ls-tree", "-r", "--name-only", "-z", rec.get("rules_evaluated_at_sha") or rec["pinned_sha"]], cwd=dest)
    tree = [p.decode("utf-8", "replace") for p in r.stdout.split(b"\0") if p]
    tree_hits = ai_tree_hits(tree)
    tests = sorted(set(rec["upstream_tests_all"]) | ({t} if t else set()))
    commit_hits, n_commits = ai_commit_hits(dest, [rec["path"]] + tests, follow_paths=[rec["path"]])
    rec["ai_trace"] = bool(tree_hits or [h for h in commit_hits if "sha" in h])
    rec["ai_trace_files"] = tree_hits
    rec["ai_trace_commits"] = commit_hits
    rec["ai_trace_commits_scanned"] = n_commits
    return rec


# ---------------------------------------------------------------- Stage 0 modules
def module_trace(dest, p, spdx):
    """First file-level rule that p fails, in corpus_select's order (None if all pass)."""
    if cs.is_test_path(p):
        return "test_file"
    raw = (dest / p).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "not_utf8"
    n = cs.physical_lines(text)
    if not (cs.MIN_LINES <= n <= cs.MAX_LINES):
        return f"line_count:{n}"
    try:
        tree = ast.parse(text, filename=p)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return "unparseable"
    why = cs.check_source(tree) or cs.file_licence_conflict(text, spdx)
    if why:
        return why
    if cs.is_vendored(p):
        return "vendored_path"
    plain, fol = cs.log_dates(dest, p, False), cs.log_dates(dest, p, True)
    if plain is None or fol is None:
        return "no_history"
    b = cs.buckets_for(cs.utc_date(fol["first_c"]), cs.utc_date(plain["last_c"]))
    if not b:
        return f"date_outside_buckets(first={fol['first_c'][:10]},last={plain['last_c'][:10]})"
    if b == ["older"]:
        return "older_no_upstream_test"    # reached only when evaluate_repo did not keep it
    return None


def stage0(meta, workdir, sample_hashes):
    out = []
    for m in meta:
        name = m["name"]
        clone_url, gh_name = STAGE0_REPOS[name]
        if gh_name:
            info = json.loads(subprocess.run(["gh", "api", f"repos/{gh_name}"], capture_output=True,
                                             check=True).stdout)
            gh_spdx = (info.get("license") or {}).get("spdx_id")
            item = {k: info.get(k) for k in ("full_name", "html_url", "created_at", "pushed_at", "size",
                                             "fork", "archived", "default_branch")}
            licence_rule = "pass" if gh_spdx in cs.ALLOWED_SPDX else f"fail: GitHub SPDX {gh_spdx}"
        else:
            gh_spdx = None
            item = {"full_name": "ericvsmith/toposort", "html_url": "https://gitlab.com/ericvsmith/toposort",
                    "fork": False, "archived": False, "default_branch": "master"}
            licence_rule = "non-GitHub: decided from licence file text below"
        # The licence rule is reported separately; the other rules run with the corpus licence so
        # each module gets a full rule trace.
        item["license"] = {"spdx_id": gh_spdx if gh_spdx in cs.ALLOWED_SPDX else m["licence"]}

        real_git = cs.git
        def git_redirect(args, cwd=None, inp=None, timeout=300, _url=clone_url, _gh=gh_name):
            if args and args[0] == "clone" and _gh is None:
                args = [a if a != "https://github.com/ericvsmith/toposort.git" else _url for a in args]
            return real_git(args, cwd=cwd, inp=inp, timeout=timeout)
        cs.git = git_redirect
        try:
            r = cs.evaluate_repo(item, "older", workdir)
            reasons = []
            if not licence_rule.startswith("pass"):
                reasons.append(f"licence:{licence_rule}")
            if r.get("outcome") == "licence_mismatch":
                # The wording test found another permitted family; record the failure, then rerun the
                # unchanged rules with that family (fresh directory) so rules 1-8 still get a trace.
                reasons.append(f"licence:fail: licence file wording reads as {r['licence_file_families']}, "
                               f"not {item['license']['spdx_id']}")
                fam = [f for f in r["licence_file_families"] if f in cs.ALLOWED_SPDX]
                if fam:
                    item = {**item, "license": {"spdx_id": fam[0]}}
                    r = cs.evaluate_repo(item, "older_licence_diag", workdir)
                    frame_dir = "older_licence_diag"
            else:
                frame_dir = "older"
        finally:
            cs.git = real_git
        if gh_name is None:
            # A1d licence rule for non-GitHub repos: the root licence file text must match exactly one
            # permitted family (corpus_select.licence_family), and that family is the licence.
            fams = r.get("licence_file_families") or []
            if len(fams) == 1 and fams[0] in cs.ALLOWED_SPDX and r.get("outcome") != "licence_mismatch":
                licence_rule = f"pass (non-GitHub; licence file text matches {fams[0]})"
                reasons = [x for x in reasons if not x.startswith("licence:non-GitHub")]
            else:
                reasons = [x if not x.startswith("licence:non-GitHub") else
                           f"licence:fail (non-GitHub; licence file text matches {fams})" for x in reasons]
        dest = workdir / frame_dir / item["full_name"].replace("/", "__")
        mods = [p.relative_to(dest).as_posix() for p in dest.rglob(m["module_file"])
                if ".git" not in p.parts and not cs.is_test_path(p.relative_to(dest).as_posix())]
        p = sorted(mods, key=len)[0]
        kept = next((c for c in r["candidates"] if c["path"] == p), None)
        if r.get("outcome") not in ("has_candidates", "no_candidates"):
            reasons.append(f"repo:{r.get('outcome')}")
        if kept is None:
            reasons.append(f"file:{module_trace(dest, p, item['license']['spdx_id'])}")
        if r.get("mutation_trace"):
            reasons.append(f"rule8_mutation_trace:{r['mutation_trace']}")
        text = (dest / p).read_bytes().decode("utf-8-sig")
        nh = cs.sha256_hex(" ".join(text.split()))
        if nh in sample_hashes:
            reasons.append(f"rule6_duplicate_of:{sample_hashes[nh]}")
        if kept and len(r["candidates"]) > cs.CAP_PER_REPO:
            import random
            chosen = random.Random(f"{cs.SEED}:{item['html_url']}").sample(sorted(c["path"] for c in r["candidates"]),
                                                                        cs.CAP_PER_REPO)
            if p not in chosen:
                reasons.append("rule7_cap")

        plain, fol = cs.log_dates(dest, p, False), cs.log_dates(dest, p, True)
        head = r.get("pinned_sha")
        corpus_sha = m["module_sha256"]
        at_pin = cs.git(["show", f"{m['upstream_tests']['commit']}:{p}"], cwd=dest, timeout=600)
        up = (kept or {})
        ups_all = up.get("upstream_tests") or []
        ups_direct = up.get("upstream_tests_direct") or []
        test_path = m["upstream_tests"]["path"]
        if kept is None:
            test_kind = "unresolved (module failed a rule before rule 3)"
        else:
            test_kind = "direct" if test_path in ups_direct else ("indirect" if test_path in ups_all else "not found by rule 3")
        rec = {
            "id": f"stage0:{name}", "repo_url": item["html_url"], "path": p,
            "pinned_sha": m["upstream_tests"]["commit"],
            "pinned_ref": m["upstream_tests"].get("tag"),
            "rules_evaluated_at_sha": head,
            "module_sha256": corpus_sha,
            "module_matches_corpus_at_pin": at_pin.returncode == 0 and hashlib.sha256(at_pin.stdout).hexdigest() == corpus_sha,
            "module_matches_corpus_at_head": sha256_file(dest / p) == corpus_sha,
            "first_commit_date": fol["first_c"] if fol else None,
            "first_commit_sha": fol["first_sha"] if fol else None,
            "last_change_date": plain["last_c"] if plain else None,
            "last_change_sha": plain["last_sha"] if plain else None,
            "licence": m["licence"], "licence_github_spdx": gh_spdx, "licence_file": r.get("licence_file"),
            "licence_file_wording": r.get("licence_file_families"),
            "lines": cs.physical_lines(text), "licence_rule": licence_rule,
            "upstream_test": test_path, "upstream_test_kind": test_kind,
            "upstream_tests_all": ups_all, "upstream_tests_direct": ups_direct,
            "buckets": cs.buckets_for(cs.utc_date(fol["first_c"]), cs.utc_date(plain["last_c"])) if fol and plain else [],
            "sample_frame": None,
            "passes_a1b_rules": not reasons, "a1b_rule_failures": reasons,
            "stage0_name": name,
        }
        lic = r.get("licence_file") or []
        out.append((rec, dest, [lic] if isinstance(lic, str) else lic))
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True, help="A1b clone directory (corpus_select --workdir)")
    ap.add_argument("--stage0-workdir", required=True, help="new empty directory outside the project")
    ap.add_argument("--candidates", default=str(PROJECT / "candidates.json"))
    ap.add_argument("--out", default=str(PROJECT / "candidates_frozen.json"))
    a = ap.parse_args()
    W, S0 = Path(a.workdir), Path(a.stage0_workdir)
    S0.mkdir(parents=True, exist_ok=True)
    if any(S0.iterdir()):
        sys.exit("--stage0-workdir must be empty")
    src = json.loads(Path(a.candidates).read_text())
    assert src["meta"]["status"] == "complete" and src["meta"]["seed"] == cs.SEED
    repos = {r["url"]: r for r in src["repos"]}
    windows = list(cs.NEWER_WINDOWS)

    recs, removed = [], []
    for c in src["candidates"]:
        in_newer = [w for w in windows if w in c["buckets"]]
        older_with_test = "older" in c["buckets"] and bool(c["upstream_tests"])
        if not (in_newer or older_with_test):
            continue
        if cs.is_vendored(c["path"]):          # A1d: extended vendored-folder rule (rule 5)
            removed.append({"repo_url": c["repo_url"], "path": c["path"], "buckets": c["buckets"],
                            "removed_by": "rule5_vendored_path_a1d"})
            continue
        c = {**c, "upstream_tests": [t for t in c["upstream_tests"] if not cs.is_vendored(t)],
             "upstream_tests_direct": [t for t in c["upstream_tests_direct"] if not cs.is_vendored(t)]}
        owner, repo = owner_repo(c["repo_url"])
        dest = W / c["sample_frame"] / f"{owner}__{repo}"
        head = cs.git(["rev-parse", "HEAD"], cwd=dest).stdout.decode().strip()
        assert head == c["pinned_sha"], (dest, head)
        test, kind = pick_test(c["path"], c["upstream_tests_direct"], c["upstream_tests"])
        lic = c["licence_file"]
        rec = {
            "id": f"{owner}/{repo}:{c['path']}", "repo_url": c["repo_url"], "path": c["path"],
            "pinned_sha": c["pinned_sha"], "default_branch": c["default_branch"],
            "module_sha256": sha256_file(dest / c["path"]),
            "first_commit_date": c["first_commit_date"], "first_commit_sha": c["first_commit_sha"],
            "first_commit_date_path_only": c["first_commit_date_path_only"],
            "last_change_date": c["last_change_date"], "last_change_sha": c["last_change_sha"],
            "licence": c["licence"], "licence_file": lic, "lines": c["lines"],
            "upstream_test": test, "upstream_test_kind": kind,
            "upstream_tests_all": c["upstream_tests"], "upstream_tests_direct": c["upstream_tests_direct"],
            "buckets": c["buckets"], "sample_frame": c["sample_frame"],
            "repo_root_commit_date": c["repo_root_commit_date"], "norm_sha256": c["norm_sha256"],
        }
        recs.append((rec, dest, [lic] if isinstance(lic, str) else lic))

    hashes = {}
    for c in src["candidates"] + src["removed_candidates"]:
        hashes.setdefault(c["norm_sha256"], f"{c['repo_url']}:{c['path']}")
    s0 = stage0(json.loads((PROJECT / "corpus" / "metadata.json").read_text()), S0, hashes)

    frozen = []
    for rec, dest, lic in recs + s0:
        flags_for(rec, dest, lic)
        is_s0 = rec["id"].startswith("stage0:")
        rec["windows"] = {w: w in rec["buckets"] for w in windows}
        rec["primary_set"] = (not is_s0) and rec["windows"][PRIMARY_WINDOW]
        rec["baseline_set"] = is_s0 or ("older" in rec["buckets"] and bool(rec["upstream_test"]))
        rec["seed_set"] = is_s0
        frozen.append(rec)

    def tally(rs):
        return {"repos_with_candidate": len({r["repo_url"] for r in rs}), "candidates": len(rs),
                "test_direct": sum(r["upstream_test_kind"] == "direct" for r in rs),
                "test_indirect_only": sum(r["upstream_test_kind"] == "indirect" for r in rs),
                "test_none": sum(r["upstream_test_kind"] == "none" for r in rs),
                "ai_trace": sum(r["ai_trace"] for r in rs), "possible_copy": sum(r["possible_copy"] for r in rs),
                "baseline_human_certain": sum(r["baseline_human_certain"] for r in rs)}
    counts = {w: tally([r for r in frozen if r["windows"][w]]) for w in windows}
    base = [r for r in frozen if r["baseline_set"]]
    counts["baseline_set"] = tally(base)
    counts["baseline_set"]["stage0_passing_a1b_rules"] = sum(r.get("passes_a1b_rules", False) for r in base)
    counts["all"] = tally(frozen)
    counts["removed_a1d_vendored"] = {w: sum(w in x["buckets"] for x in removed) for w in windows}
    counts["removed_a1d_vendored"]["baseline_set"] = sum("older" in x["buckets"] for x in removed)
    counts["primary_no_ai_trace_direct_test"] = sum(
        r["primary_set"] and not r["ai_trace"] and r["upstream_test_kind"] == "direct" for r in frozen)

    doc = {
        "meta": {
            "stage": "A1d", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "candidates.json (A1b, seed 20261118, generated_at " + src["meta"]["generated_at"] + ")",
            "source_sha256": hashlib.sha256(Path(a.candidates).read_bytes()).hexdigest(),
            "primary_window": PRIMARY_WINDOW, "human_certain_max": HUMAN_CERTAIN_MAX.isoformat(),
            "note": "Later stages read this file and never rerun the search. Rules: DECISIONS.md (A1b, A1c).",
            "python": sys.version.split()[0],
        },
        "counts": counts,
        "candidates": sorted(frozen, key=lambda r: r["id"]),
        "removed_candidates": removed,
    }
    Path(a.out).write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main()
