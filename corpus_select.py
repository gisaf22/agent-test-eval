#!/usr/bin/env python3
"""Stage A1/A1b: count candidate corpus modules on GitHub with code, using a fixed seed.

The A1b rules (physical lines, upstream test that imports the module, dates that follow
renames, no vendored paths, dedup, cap of 2 per repo, no mutation-testing trace) and the
order they apply in are written out in DECISIONS.md.

There are no model API calls and nothing downloaded is ever imported or run.
Repos are partial-cloned (blob:none) into a fresh, empty directory outside the
project. Only the root licence files and the .py blobs are checked out, and
they are read as text and parsed with `ast`. Run it with the sandbox's
interpreter, in isolated mode:

    python3.12 -I corpus_select.py --workdir <new empty dir outside project>

Sampling frames (one per bucket, at most MAX_REPOS repos examined in each):
  older  repos created 2008-01-01..2025-06-30   (bucket: file's last change <= 2025-06-30)
  newer  repos created 2025-09-01..2026-11-17   (windows: file's first commit >= 2025-09-01,
                                                  >= 2026-02-01, >= 2026-07-01, nested)
Each draw picks a creation day uniformly at random (seeded) and queries
`language:Python created:<day>` on GitHub search. Forks are left out by
search's default. The draw then takes a random results page (search serves only
the first 1000 hits) and REPOS_PER_DRAW random repos from that page. Draws
continue until the frame has MAX_REPOS unique repos. The per-day total_count is
recorded so the sample can be reweighted later.

File-level rules run in evaluate_repo; the repo-trace, dedup and cap rules run in
post_process. The first rule a file fails is recorded so the funnel can be audited.
"""

import argparse
import ast
import hashlib
import io
import json
import math
import os
import random
import re
import subprocess
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
SEED = 20261118
MAX_REPOS = 300
REPOS_PER_DRAW = 10
MAX_DRAWS = 120
MIN_LINES, MAX_LINES = 50, 300
MAX_BLOB_BYTES = 200_000          # fetch optimisation only: a file this big in <=300 lines is not plausible source
CLONE_TIMEOUT = 600
WORKERS = 6

FRAMES = {
    "older": (date(2008, 1, 1), date(2025, 6, 30)),
    "newer": (date(2025, 9, 1), date(2026, 11, 17)),
}
OLDER_LAST_CHANGE_MAX = date(2025, 6, 30)
NEWER_WINDOWS = {                 # nested: first commit on or after
    "newer_since_2025-09-01": date(2025, 9, 1),
    "newer_since_2026-02-01": date(2026, 2, 1),
    "newer_since_2026-07-01": date(2026, 7, 1),
}

ALLOWED_SPDX = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0"}

# ---------------------------------------------------------------- static I/O rules
# Any reference to these modules (import or attribute) disqualifies the file.
BANNED_MODULES = {
    # network
    "socket", "socketserver", "ssl", "select", "selectors", "asyncio", "http", "urllib",
    "ftplib", "smtplib", "smtpd", "poplib", "imaplib", "nntplib", "telnetlib", "xmlrpc",
    "webbrowser", "wsgiref", "asynchat", "asyncore", "logging.handlers",
    # subprocess / process control
    "subprocess", "multiprocessing", "pty", "pipes", "concurrent.futures.process",
    # file system / file formats that open paths
    "shutil", "tempfile", "glob", "fileinput", "pathlib", "zipfile", "tarfile", "gzip",
    "bz2", "lzma", "zipimport", "mmap", "fcntl", "msvcrt", "winreg", "filecmp", "netrc",
    "mailbox", "linecache",
    # databases
    "sqlite3", "dbm", "shelve",
    # foreign code / dynamic import (cannot be checked statically)
    "ctypes", "importlib",
}
_OS_IO = {
    "system", "popen", "fork", "forkpty", "kill", "killpg", "open", "fdopen", "read", "write",
    "pipe", "remove", "unlink", "rename", "renames", "replace", "mkdir", "makedirs", "rmdir",
    "removedirs", "listdir", "scandir", "walk", "fwalk", "chdir", "chmod", "chown", "lchown",
    "link", "symlink", "readlink", "stat", "lstat", "truncate", "utime", "mkfifo", "mknod",
    "startfile", "sendfile", "access", "posix_spawn", "posix_spawnp",
}
_OS_PATH_IO = {
    "exists", "lexists", "isfile", "isdir", "islink", "ismount", "getsize", "getmtime",
    "getatime", "getctime", "samefile", "realpath",
}
BANNED_NAMES = (
    {f"os.{n}" for n in _OS_IO}
    | {f"os.path.{n}" for n in _OS_PATH_IO}
    | {"io.open", "io.FileIO", "io.open_code", "codecs.open", "logging.FileHandler",
       "tokenize.open"}
)
BANNED_PREFIXES = ("os.exec", "os.spawn", "os.wait")
BANNED_BUILTINS = {"open", "__import__", "exec", "eval", "compile", "breakpoint"}

STDLIB = set(sys.stdlib_module_names)


def _qualname(node, aliases):
    """Resolve a Name/Attribute chain to a dotted name via the module's import aliases."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    base = aliases.get(node.id)
    if base is None:
        return None
    return ".".join([base] + list(reversed(parts)))


def _banned(qual):
    if qual is None:
        return False
    if qual in BANNED_NAMES or qual.startswith(BANNED_PREFIXES):
        return True
    return any(qual == m or qual.startswith(m + ".") for m in BANNED_MODULES)


def check_source(tree):
    """Return None if the AST passes the import and I/O rules, else a reason string."""
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in STDLIB:
                    return f"non_stdlib_import:{a.name}"
                if _banned(a.name):
                    return f"io_module:{a.name}"
                if a.asname:
                    aliases[a.asname] = a.name
                else:
                    top = a.name.split(".")[0]
                    aliases[top] = top
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                return "relative_import"
            mod = node.module or ""
            if mod.split(".")[0] not in STDLIB:
                return f"non_stdlib_import:{mod}"
            if _banned(mod):
                return f"io_module:{mod}"
            for a in node.names:
                full = f"{mod}.{a.name}"
                if a.name == "*" or _banned(full):
                    return f"io_name:{full}"
                aliases[a.asname or a.name] = full
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in BANNED_BUILTINS and node.id not in aliases:
            return f"io_builtin:{node.id}"
        if isinstance(node, (ast.Attribute, ast.Name)):
            q = _qualname(node, aliases)
            if _banned(q):
                return f"io_name:{q}"
    return None


# ---------------------------------------------------------------- licence rules
_LICENCE_FILE = re.compile(r"^(licen[cs]e|copying)([._-][^/]*)?$", re.I)
_SPDX_HDR = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.+-]+)")


def licence_family(text):
    t = " ".join(text.lower().split())
    found = set()
    if "permission is hereby granted, free of charge" in t:
        found.add("MIT")
    if "apache license" in t and "version 2.0" in t:
        found.add("Apache-2.0")
    if "redistribution and use in source and binary forms" in t:
        # A2: "the name of the author may not be used to endorse ..." is the BSD-3-Clause
        # non-endorsement clause in another wording (heapdict's LICENSE uses it)
        found.add("BSD-3-Clause" if ("neither the name" in t or "names of its contributors" in t
                                     or "the name of the author may not be used to endorse or promote "
                                        "products derived from this software" in t)
                  else "BSD-2-Clause")
    return found


def file_licence_conflict(text, spdx):
    for m in _SPDX_HDR.finditer(text):
        if m.group(1) != spdx:
            return f"file_spdx:{m.group(1)}"
    low = text.lower()
    if "gnu general public license" in low or "gnu lesser general public" in low or "gnu affero" in low:
        return "file_mentions_gpl"
    return None


# ---------------------------------------------------------------- GitHub search
class RateLimited(Exception):
    pass


def gh_search(q, page):
    for attempt in range(4):
        r = subprocess.run(["gh", "api", "-X", "GET", "search/repositories",
                            "-f", f"q={q}", "-f", "per_page=100", "-f", f"page={page}"],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            time.sleep(2.2)        # stay under 30 search requests / minute
            return json.loads(r.stdout)
        err = r.stderr[:400]       # gh puts the HTTP status on stderr; stdout may hold a body
        last_err = err
        if "rate limit" in err.lower() or "HTTP 403" in err or "HTTP 429" in err:
            time.sleep(60 * 2 ** attempt)
        else:                      # transient (5xx, timeout, connection reset): back off and retry
            time.sleep(15 * (attempt + 1))
    if "rate limit" in last_err.lower() or "HTTP 403" in last_err or "HTTP 429" in last_err:
        raise RateLimited(f"search still rate limited after retries: q={q!r} page={page}")
    raise RuntimeError(f"search failed after retries: q={q!r} page={page} stderr={last_err!r}")


def draw_sample(frame, rng, log):
    lo, hi = FRAMES[frame]
    span = (hi - lo).days
    seen, picks, draws = set(), [], []
    while len(picks) < MAX_REPOS and len(draws) < MAX_DRAWS:
        day = lo + timedelta(days=rng.randrange(span + 1))
        page_choice = rng.random()
        sub_seed = rng.randrange(2 ** 32)
        q = f"language:Python created:{day.isoformat()}"
        first = gh_search(q, 1)
        total = first["total_count"]
        n_pages = max(1, min(10, math.ceil(min(total, 1000) / 100)))
        page = 1 + int(page_choice * n_pages)
        res = first if page == 1 else gh_search(q, page)
        items = sorted(res.get("items", []), key=lambda it: it["full_name"].lower())
        items = [it for it in items if it["full_name"].lower() not in seen]
        take = random.Random(sub_seed).sample(items, min(REPOS_PER_DRAW, len(items), MAX_REPOS - len(picks)))
        for it in take:
            seen.add(it["full_name"].lower())
            picks.append(it)
        draws.append({"day": day.isoformat(), "total_count": total, "page": page,
                      "page_items": len(res.get("items", [])), "taken": len(take)})
        log(f"[{frame}] draw {len(draws)} day={day} total={total} page={page} -> {len(picks)} repos")
    return picks, draws


# ---------------------------------------------------------------- per-repo evaluation
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1",
           "GIT_LITERAL_PATHSPECS": "1", "GIT_CONFIG_NOSYSTEM": "1"}
GIT_SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.symlinks=false",
            "-c", "core.fsmonitor=false", "-c", "protocol.file.allow=never",
            "-c", "submodule.recurse=false",
            "-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=60"]   # abort stalled transfers


def git(args, cwd=None, inp=None, timeout=300):
    """Run git in its own process group; on timeout kill the whole group.

    subprocess.run's own timeout kills only the direct child, then waits for the pipes,
    which lazily spawned `git fetch` grandchildren keep open, so a stalled fetch hung forever.
    """
    p = subprocess.Popen(["git", *GIT_SAFE, *args], cwd=cwd, env=GIT_ENV, start_new_session=True,
                         stdin=subprocess.PIPE if inp is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = p.communicate(input=inp, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, 9)
        except ProcessLookupError:
            pass
        p.communicate()
        raise
    return subprocess.CompletedProcess(p.args, p.returncode, out, err)


VENDORED_DIRS = {"site-packages", "_vendor", "vendor", "third_party",
                 # A1d: added after the A1c count found a node_modules copy
                 "node_modules", "bower_components", ".venv", "venv", "dist-packages"}
TRACE_TERMS = ("mutmut", "cosmic-ray", "cosmic_ray", "mutpy", "mutatest", "mutation testing")
TRACE_MAX_BYTES = 1_000_000
CAP_PER_REPO = 2


def is_test_path(path):
    parts = path.split("/")
    base = parts[-1]
    if any(p.lower() in ("test", "tests", "testing") for p in parts[:-1]):
        return True
    return bool(re.match(r"^(test_.*|.*_test|conftest|tests?)\.py$", base, re.I))


def is_vendored(path):
    return any(p.lower() in VENDORED_DIRS for p in path.split("/")[:-1])


def is_trace_file(path):
    parts = path.lower().split("/")
    base = parts[-1]
    if base in {"pyproject.toml", "setup.cfg", "tox.ini", "mutmut_config.py", ".gitlab-ci.yml",
                ".travis.yml", "azure-pipelines.yml", "appveyor.yml", ".appveyor.yml", "jenkinsfile"}:
        return True
    if base.startswith(("requirements", "readme", "contributing")):
        return True
    if any(p.startswith("requirements") for p in parts[:-1]):
        return True
    if any(k in base for k in ("cosmic-ray", "cosmic_ray", "cosmicray")):
        return True
    if len(parts) >= 3 and parts[-3] == ".github" and parts[-2] == "workflows" and base.endswith((".yml", ".yaml")):
        return True
    return path.lower().endswith(".circleci/config.yml")


def physical_lines(text):
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    return t.count("\n") + (1 if t and not t.endswith("\n") else 0)


def module_suffixes(path):
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return {".".join(parts[i:]) for i in range(len(parts))}


def imported_names(tree, test_path):
    pkg = test_path.split("/")[:-1]
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level - 1 > len(pkg):
                    continue
                base = pkg[:len(pkg) - (node.level - 1)]
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            if mod:
                names.add(mod)
            for a in node.names:
                if a.name != "*":
                    names.add(f"{mod}.{a.name}" if mod else a.name)
    return names


def utc_date(iso):
    return datetime.fromisoformat(iso).astimezone(timezone.utc).date()


def buckets_for(first_d, last_d):
    b = ["older"] if last_d <= OLDER_LAST_CHANGE_MAX else []
    return b + [w for w, start in NEWER_WINDOWS.items() if first_d >= start]


def log_dates(dest, p, follow):
    args = ["log", "--format=%H %cI %aI"] + (["--follow"] if follow else []) + ["--", p]
    r = git(args, cwd=dest)
    lines = [ln for ln in r.stdout.decode().split("\n") if ln.strip()] if r.returncode == 0 else []
    if not lines:
        return None
    last_sha, last_c, _ = lines[0].split()
    first_sha, first_c, first_a = lines[-1].split()
    return {"first_sha": first_sha, "first_c": first_c, "first_a": first_a, "last_sha": last_sha, "last_c": last_c}


def evaluate_repo(item, frame, workdir):
    name = item["full_name"]
    out = {"repo": name, "url": item["html_url"], "frame": frame,
           "created_at": item.get("created_at"), "pushed_at": item.get("pushed_at"),
           "size_kb": item.get("size"), "fork": item.get("fork"), "archived": item.get("archived"),
           "spdx": (item.get("license") or {}).get("spdx_id"), "files": {}, "candidates": [],
           "line_rule_delta": {"in_by_splitlines_out_by_physical": 0, "out_by_splitlines_in_by_physical": 0},
           "date_rule_losses": []}
    if item.get("fork"):
        out["outcome"] = "fork"; return out
    if item.get("archived"):
        out["outcome"] = "archived"; return out
    if out["spdx"] not in ALLOWED_SPDX:
        out["outcome"] = "licence_not_allowed"; return out

    dest = workdir / frame / name.replace("/", "__")
    r = git(["clone", "-q", "--filter=blob:none", "--no-checkout", "--single-branch",
             f"https://github.com/{name}.git", str(dest)], timeout=CLONE_TIMEOUT)
    if r.returncode != 0:
        out["outcome"] = "clone_failed"; out["error"] = r.stderr.decode(errors="replace")[-300:]
        return out
    # no -l: in a blob:none clone, printing sizes makes git fetch every blob one by one
    r = git(["ls-tree", "-r", "-z", "HEAD"], cwd=dest)
    if r.returncode != 0:
        out["outcome"] = "empty_repo"; return out
    out["pinned_sha"] = git(["rev-parse", "HEAD"], cwd=dest).stdout.decode().strip()
    roots = git(["log", "--max-parents=0", "--format=%cI", "HEAD"], cwd=dest).stdout.decode().split()
    out["root_commit_date"] = min(roots, key=lambda s: datetime.fromisoformat(s).astimezone(timezone.utc)) if roots else None
    entries = []
    for rec in r.stdout.split(b"\0"):
        if not rec:
            continue
        meta, path = rec.split(b"\t", 1)
        mode, typ, oid = meta.split()
        entries.append((mode.decode(), typ.decode(), oid.decode(), path.decode("utf-8", "replace")))
    blobs = [e for e in entries if e[1] == "blob" and e[0] in ("100644", "100755")]
    paths = [e[3] for e in entries]
    out["has_tests"] = any(is_test_path(p) for p in paths if p.endswith(".py")) or \
        any(seg.lower() in ("test", "tests", "testing") for p in paths for seg in p.split("/")[:-1])
    lic_files = [e[3] for e in blobs if "/" not in e[3] and _LICENCE_FILE.match(e[3])]
    py_files = [e[3] for e in blobs if e[3].endswith(".py")]
    test_files = [p for p in py_files if is_test_path(p) and not is_vendored(p)]
    trace_files = [e[3] for e in blobs if is_trace_file(e[3])]
    if not lic_files:
        out["outcome"] = "licence_file_missing"; return out
    want = list(dict.fromkeys(lic_files + [p for p in py_files if not is_test_path(p)] + test_files + trace_files))
    r = git(["checkout", "-q", "HEAD", "--pathspec-from-file=-", "--pathspec-file-nul"], cwd=dest,
            inp=b"\0".join(p.encode() for p in want), timeout=CLONE_TIMEOUT)
    if r.returncode != 0:
        out["outcome"] = "checkout_failed"; out["error"] = r.stderr.decode(errors="replace")[-300:]
        return out
    # size caps, applied to the checked-out files (same thresholds as before)
    def _size(p):
        fp = dest / p
        return fp.lstat().st_size if fp.exists() and not fp.is_symlink() else -1
    py_files = [p for p in py_files if 0 <= _size(p) <= MAX_BLOB_BYTES]
    test_files = [p for p in test_files if 0 <= _size(p) <= MAX_BLOB_BYTES]
    trace_files = [p for p in trace_files if 0 <= _size(p) <= TRACE_MAX_BYTES]

    def read_text(p):
        fp = dest / p
        if fp.is_symlink() or not fp.is_file():
            return None
        return fp.read_bytes()

    fams = set()
    for lf in lic_files:
        raw = read_text(lf)
        if raw is not None:
            fams |= licence_family(raw.decode("utf-8", errors="replace"))
    out["licence_file_families"] = sorted(fams)
    if out["spdx"] not in fams:
        out["outcome"] = "licence_mismatch"; return out
    out["licence_file"] = lic_files[0] if len(lic_files) == 1 else lic_files

    # rule 8: committed mutation-testing trace (applied in post-processing so removals can be counted)
    hits = []
    for tf in trace_files:
        raw = read_text(tf)
        if raw is None:
            continue
        low = raw.decode("utf-8", errors="replace").lower()
        hits += [{"file": tf, "term": t} for t in TRACE_TERMS if t in low]
    out["mutation_trace"] = hits

    # rule 3 inputs: what each upstream test file imports
    test_imports = {}
    for tp in test_files:
        raw = read_text(tp)
        if raw is None:
            continue
        try:
            test_imports[tp] = imported_names(ast.parse(raw.decode("utf-8-sig")), tp)
        except Exception:
            continue
    # Resolve imported names to repo files roughly as Python would: sys.path roots are the repo
    # root, src/ and the importing file's directory; importing a.b also runs a/__init__.py.
    # Fallback: a unique dotted-suffix match (single-word names only when unambiguous).
    targets = {p for p in py_files if not is_vendored(p)}
    by_suffix = {}
    for p in targets:
        if not is_test_path(p):
            for s_ in module_suffixes(p):
                by_suffix.setdefault(s_, set()).add(p)

    def resolve(name, importer):
        found = set()
        parts = name.split(".")
        here = importer.rsplit("/", 1)[0] + "/" if "/" in importer else ""
        for root in ("", "src/", here):
            for k in range(1, len(parts) + 1):        # a, a.b, a.b.c: parents' __init__ run too
                stem = root + "/".join(parts[:k])
                for cand in (stem + ".py", stem + "/__init__.py"):
                    if cand in targets:
                        found.add(cand)
        if not found:
            hits = by_suffix.get(name, set())
            if "." in name or len(hits) == 1:
                found |= hits
        return found

    init_imports = {}
    for p in targets:
        if p.endswith("__init__.py") and not is_test_path(p):
            raw = read_text(p)
            if raw is None:
                continue
            try:
                init_imports[p] = imported_names(ast.parse(raw.decode("utf-8-sig")), p)
            except Exception:
                continue

    test_reach = {}                                    # test path -> (direct files, all reached files)
    for tp, names in test_imports.items():
        direct = set()
        for n in names:
            direct |= resolve(n, tp)
        reached, frontier = set(direct), [f for f in direct if f in init_imports]
        for _ in range(3):                             # follow package __init__ re-exports, 3 hops
            nxt = []
            for f in frontier:
                for n in init_imports[f]:
                    for g in resolve(n, f) - reached:
                        reached.add(g)
                        if g in init_imports:
                            nxt.append(g)
            frontier = nxt
        test_reach[tp] = (direct, reached)

    def upstream_tests_for(p):
        found = sorted(tp for tp, (_, reached) in test_reach.items() if p in reached)
        direct = sorted(tp for tp, (d, _) in test_reach.items() if p in d)
        return found, direct

    reasons = {}
    def bump(k):
        reasons[k] = reasons.get(k, 0) + 1
    out["py_files"] = len(py_files)
    for p in py_files:
        if is_test_path(p):
            bump("test_file"); continue
        raw = read_text(p)
        if raw is None:
            bump("not_regular_file"); continue
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            bump("not_utf8"); continue
        n = physical_lines(text)
        n_split = len(text.splitlines())
        in_phys, in_split = MIN_LINES <= n <= MAX_LINES, MIN_LINES <= n_split <= MAX_LINES
        if in_split and not in_phys:
            out["line_rule_delta"]["in_by_splitlines_out_by_physical"] += 1
        if in_phys and not in_split:
            out["line_rule_delta"]["out_by_splitlines_in_by_physical"] += 1
        if not in_phys:
            bump("line_count"); continue
        try:
            tree = ast.parse(text, filename=p)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            bump("unparseable"); continue
        why = check_source(tree)
        if why:
            bump(why.split(":")[0]); continue
        why = file_licence_conflict(text, out["spdx"])
        if why:
            bump("file_licence_conflict"); continue
        if is_vendored(p):
            bump("vendored_path"); continue
        plain = log_dates(dest, p, follow=False)
        if plain is None:
            bump("no_history"); continue
        try:
            fol = log_dates(dest, p, follow=True)
        except subprocess.TimeoutExpired:
            bump("follow_timeout"); continue
        if fol is None:
            bump("no_history"); continue
        b_plain = buckets_for(utc_date(plain["first_c"]), utc_date(plain["last_c"]))
        b_fol = buckets_for(utc_date(fol["first_c"]), utc_date(plain["last_c"]))
        lost4 = [b for b in b_plain if b not in b_fol]
        if lost4:
            out["date_rule_losses"].append({"path": p, "lost": lost4, "why": "rule4"})
        if not b_fol:
            bump("date_outside_buckets_after_follow" if b_plain else "date_outside_buckets"); continue
        ups, ups_direct = upstream_tests_for(p)
        if "older" in b_fol and not ups:
            out["date_rule_losses"].append({"path": p, "lost": ["older"], "why": "rule3"})
            b_fol = [b for b in b_fol if b != "older"]
            if not b_fol:
                bump("older_no_upstream_test"); continue
        bump("candidate")
        out["candidates"].append({
            "repo_url": item["html_url"], "path": p, "licence": out["spdx"],
            "licence_file": out["licence_file"], "lines": n,
            "first_commit_date": fol["first_c"], "first_commit_sha": fol["first_sha"],
            "first_author_date": fol["first_a"],
            "first_commit_date_path_only": plain["first_c"],
            "last_change_date": plain["last_c"], "last_change_sha": plain["last_sha"],
            "pinned_sha": out["pinned_sha"], "default_branch": item.get("default_branch"),
            "repo_root_commit_date": out["root_commit_date"],
            "upstream_tests": ups, "upstream_tests_direct": ups_direct, "repo_has_tests": out["has_tests"],
            "buckets": b_fol, "buckets_path_only": b_plain, "sample_frame": frame,
            "norm_sha256": sha256_hex(" ".join(text.split())),
        })
    out["files"] = reasons
    out["outcome"] = "has_candidates" if out["candidates"] else "no_candidates"
    return out


def sha256_hex(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- post-processing: rules 8, 6, 7
def _utc(s):
    return datetime.fromisoformat(s).astimezone(timezone.utc) if s else datetime.max.replace(tzinfo=timezone.utc)


def post_process(repos):
    """Apply repo-trace (8), dedup (6) and cap (7) in that order. Returns (kept, removed, stats)."""
    removed = []
    stats = {"rule8_repos_with_trace": sum(1 for r in repos if r.get("mutation_trace")),
             "rule8_repos_removed": 0}
    pool = []
    for r in repos:
        if r.get("mutation_trace") and r["candidates"]:
            stats["rule8_repos_removed"] += 1
            removed += [{**c, "removed_by": "rule8_mutation_trace"} for c in r["candidates"]]
        else:
            pool += r["candidates"]
    groups = {}
    for c in pool:
        groups.setdefault(c["norm_sha256"], []).append(c)
    deduped = []
    for h, cs in groups.items():
        cs.sort(key=lambda c: (_utc(c["repo_root_commit_date"]), _utc(c["first_commit_date"]),
                               c["repo_url"], c["path"]))
        deduped.append(cs[0])
        removed += [{**c, "removed_by": "rule6_duplicate", "duplicate_of": f"{cs[0]['repo_url']}:{cs[0]['path']}"}
                    for c in cs[1:]]
    by_repo = {}
    for c in deduped:
        by_repo.setdefault(c["repo_url"], []).append(c)
    kept = []
    for url in sorted(by_repo):
        cs = sorted(by_repo[url], key=lambda c: c["path"])
        if len(cs) > CAP_PER_REPO:
            chosen = set(random.Random(f"{SEED}:{url}").sample([c["path"] for c in cs], CAP_PER_REPO))
        else:
            chosen = {c["path"] for c in cs}
        for c in cs:
            (kept if c["path"] in chosen else removed).append(
                c if c["path"] in chosen else {**c, "removed_by": "rule7_cap"})
    return kept, removed, stats


# ---------------------------------------------------------------- report
def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


BUCKET_FRAME = {"older": "older", **{w: "newer" for w in NEWER_WINDOWS}}


def counts_table(repos, kept, removed):
    rows = []
    for b, frame in BUCKET_FRAME.items():
        fr = [r for r in repos if r["frame"] == frame]
        n = len(fr)
        mine = lambda cs: [c for c in cs if c["sample_frame"] == frame and b in c["buckets"]]
        k = mine(kept)
        pre = [c for r in fr for c in r["candidates"] if b in c["buckets"]]
        hit_repos = {c["repo_url"] for c in k}
        lo, hi = wilson(len(hit_repos), n)
        rm = {}
        for c in mine(removed):
            rm[c["removed_by"]] = rm.get(c["removed_by"], 0) + 1
        # file-level rules that act after dates, attributed to the bucket the file would otherwise be in
        r4 = 0; r3 = 0
        for r in fr:
            for c in r.get("date_rule_losses", []):
                if b in c["lost"] and c["why"] == "rule4":
                    r4 += 1
                if b in c["lost"] and c["why"] == "rule3":
                    r3 += 1
        rows.append({"bucket": b, "sample_frame": frame, "repos_examined": n,
                     "repos_with_candidate": len(hit_repos), "repo_rate": len(hit_repos) / n if n else 0.0,
                     "repo_rate_ci95": [lo, hi],
                     "candidates_before_repo_rules": len(pre), "candidates_after_cap": len(k),
                     "candidates_with_upstream_test": sum(1 for c in k if c["upstream_tests"]),
                     "removed_rule4_follow_renames": r4, "removed_rule3_no_upstream_test": r3,
                     "removed_rule8_mutation_trace": rm.get("rule8_mutation_trace", 0),
                     "removed_rule6_duplicate": rm.get("rule6_duplicate", 0),
                     "removed_rule7_cap": rm.get("rule7_cap", 0)})
    return rows


def funnel(repos):
    out = {}
    for frame in FRAMES:
        fr = [r for r in repos if r["frame"] == frame]
        oc, fl, ld = {}, {}, {}
        for r in fr:
            oc[r["outcome"]] = oc.get(r["outcome"], 0) + 1
            for k, v in r["files"].items():
                fl[k] = fl.get(k, 0) + v
            for k, v in r.get("line_rule_delta", {}).items():
                ld[k] = ld.get(k, 0) + v
        out[frame] = {"repo_outcomes": dict(sorted(oc.items())), "file_reasons": dict(sorted(fl.items())),
                      "line_rule_delta": ld}
    return out


def render_md(meta, rows, fun, stats, cross, overlap):
    L = ["# Stage A1b candidate counts", "",
         f"Generated {meta['generated_at']} by `corpus_select.py` (seed {meta['seed']}, Python {meta['python']}).",
         "**Estimates from a seeded sample, not totals.** Each frame examined at most "
         f"{MAX_REPOS} GitHub repos. Rules and their order are in DECISIONS.md (Stage A1b).", "",
         "| bucket | repos examined | repos with ≥1 candidate | repo rate (95% CI) | candidates after cap "
         "| with upstream test found |",
         "|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['bucket']} | {r['repos_examined']} | {r['repos_with_candidate']} | "
                 f"{r['repo_rate']:.1%} ({r['repo_rate_ci95'][0]:.1%}–{r['repo_rate_ci95'][1]:.1%}) | "
                 f"{r['candidates_after_cap']} | {r['candidates_with_upstream_test']} |")
    L += ["", "## Removed by each rule (after dates; per bucket)", "",
          "| bucket | rule 4 follow renames | rule 3 no upstream test | rule 8 mutation trace | rule 6 duplicate | rule 7 cap |",
          "|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['bucket']} | {r['removed_rule4_follow_renames']} | {r['removed_rule3_no_upstream_test']} | "
                 f"{r['removed_rule8_mutation_trace']} | {r['removed_rule6_duplicate']} | {r['removed_rule7_cap']} |")
    L += ["", f"Rule 8: {stats['rule8_repos_with_trace']} cloned repos have a committed mutation-testing trace; "
          f"{stats['rule8_repos_removed']} of them had candidates and were removed.", "",
          "Newer windows are nested. Rule 3 applies only to older; for newer, \"with upstream test found\" is recorded, not required.",
          f"Cross-frame finds (counted in no row above): {cross}",
          f"Sample overlap with Stage A1 (same seed, search re-queried): {overlap}", "",
          "## File-level funnel (first failing rule, per sample frame)", ""]
    for frame, f in fun.items():
        L.append(f"**{frame}** repo outcomes: " + ", ".join(f"{k} {v}" for k, v in f["repo_outcomes"].items()))
        L.append("")
        L.append(f"**{frame}** files: " + ", ".join(f"{k} {v}" for k, v in f["file_reasons"].items()))
        L.append("")
        L.append(f"**{frame}** rule 1 effect vs A1's splitlines count: {f['line_rule_delta']}")
        L.append("")
    return "\n".join(L) + "\n"


def main():
    global MAX_REPOS
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True, help="new empty directory outside the project for clones")
    ap.add_argument("--out", default=str(PROJECT / "candidates.json"))
    ap.add_argument("--counts", default=str(PROJECT / "candidate_counts.md"))
    ap.add_argument("--previous", default=None, help="earlier candidates.json, for sample-overlap reporting only")
    ap.add_argument("--max-repos", type=int, default=MAX_REPOS, help="smoke tests only")
    a = ap.parse_args()
    MAX_REPOS = a.max_repos
    warnings.simplefilter("ignore")
    workdir = Path(a.workdir).resolve()
    if PROJECT in workdir.parents or workdir == PROJECT:
        sys.exit("workdir must be outside the project")
    if workdir.exists() and any(workdir.iterdir()):
        sys.exit("workdir must be new or empty")
    workdir.mkdir(parents=True, exist_ok=True)
    logf = open(workdir.parent / (workdir.name + ".log"), "a")

    def log(msg):
        line = f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        logf.write(line + "\n"); logf.flush()

    rng = random.Random(SEED)
    meta = {"seed": SEED, "python": sys.version.split()[0], "max_repos_per_frame": MAX_REPOS,
            "repos_per_draw": REPOS_PER_DRAW, "frames": {k: [str(v[0]), str(v[1])] for k, v in FRAMES.items()},
            "search": {"endpoint": "search/repositories", "q": "language:Python created:<YYYY-MM-DD>",
                       "sort": "default (best match; no sort/order parameter)", "per_page": 100, "max_page": 10},
            "older_last_change_max": str(OLDER_LAST_CHANGE_MAX),
            "newer_windows": {k: str(v) for k, v in NEWER_WINDOWS.items()},
            "allowed_spdx": sorted(ALLOWED_SPDX), "lines": [MIN_LINES, MAX_LINES], "line_count": "physical",
            "banned_modules": sorted(BANNED_MODULES), "banned_names": sorted(BANNED_NAMES),
            "banned_prefixes": list(BANNED_PREFIXES), "banned_builtins": sorted(BANNED_BUILTINS),
            "vendored_dirs": sorted(VENDORED_DIRS), "trace_terms": list(TRACE_TERMS),
            "cap_per_repo": CAP_PER_REPO,
            "date_source": "committer date (UTC); first commit via git log --follow, last change path-only, default branch"}
    status = "complete"
    samples, draws = {}, {}
    try:
        for frame in FRAMES:                       # fixed order so the RNG stream is reproducible
            samples[frame], draws[frame] = draw_sample(frame, rng, log)
    except RateLimited as e:
        status = f"stopped: {e}"
        log(status)

    repos = []
    jobs = [(it, fr) for fr in samples for it in samples[fr]]
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(evaluate_repo, it, fr, workdir) for it, fr in jobs]
        for i, ((it, fr), f) in enumerate(zip(jobs, futs), 1):
            try:
                r = f.result()
            except Exception as e:             # one bad repo must not stop the count
                r = {"repo": it["full_name"], "url": it["html_url"], "frame": fr, "outcome": "error",
                     "error": repr(e)[:300], "files": {}, "candidates": []}
            repos.append(r)
            log(f"[{fr}] {i}/{len(jobs)} {r['repo']}: {r['outcome']} ({len(r['candidates'])} cand)")

    kept, removed, stats = post_process(repos)
    rows = counts_table(repos, kept, removed)
    fun = funnel(repos)
    own = {"older": {"older"}, "newer": set(NEWER_WINDOWS)}
    cross = {}
    for c in kept:
        for b in c["buckets"]:
            if b not in own[c["sample_frame"]]:
                key = f"{c['sample_frame']}-frame→{b}"
                cross[key] = cross.get(key, 0) + 1
    overlap = "not computed"
    if a.previous:
        prev = json.loads(Path(a.previous).read_text())
        for fr in FRAMES:
            p = {r["repo"].lower() for r in prev["repos"] if r["frame"] == fr}
            c = {r["repo"].lower() for r in repos if r["frame"] == fr}
            overlap = (overlap if isinstance(overlap, dict) else {})
            overlap[fr] = f"{len(p & c)}/{len(c)}"
    meta["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta["status"] = status
    doc = {"meta": meta, "counts": rows, "funnel": fun, "rule8": stats, "cross_frame": cross,
           "sample_overlap_with_previous": overlap, "draws": draws,
           "repos": [{k: v for k, v in r.items() if k != "candidates"} for r in repos],
           "candidates": kept, "removed_candidates": removed}
    Path(a.out).write_text(json.dumps(doc, indent=1) + "\n")
    Path(a.counts).write_text(render_md(meta, rows, fun, stats, cross or "none", overlap))
    log(f"status={status} wrote {a.out} and {a.counts}")


if __name__ == "__main__":
    main()
