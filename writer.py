#!/usr/bin/env python3
"""Test writer (Stage B1): asks a Claude model to write a pytest suite for one corpus module.

The writer sees only: the DESIGN.md section 11 prompt, the module source, its own tests,
and their pytest results and coverage on the ORIGINAL module (run in a fresh offline
sandbox per iteration). It never sees mutants, scores, reference suites, upstream tests
or the scorer.

Loop: call the model -> extract test files from fenced blocks -> run them with coverage in
the sandbox -> send results back. Up to MAX_ITERATIONS model calls; stops early when the
writer replies DONE (no code blocks), on a refusal, or when a cap would be passed.

Caps: MAX_TOKENS_PER_CALL per call, RUN_TOKEN_CAP (input + output) per run, RUN_WALL_CAP_S
per run, and a hard spend cap per run tag (SPEND_CAPS) summed over that tag's runs/<tag>/ledger.jsonl.

The API key is read only from AGENT_EVAL_API_KEY, removed from this process's environment
before any subprocess starts, and never written anywhere. Requests are sent with default
temperature (no sampling parameters).

Output: runs/<tag>/<run_id>/ with transcript.jsonl (every request payload and reply),
iter_<n>/ (each iteration's files), suite/ (the final suite, scored by run_eval.py) and
meta.json. Usage: .venv/bin/python writer.py --module toposort --model claude-haiku-5-5
--effort low --seed s1 --run-id <id>
"""
import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import run_eval

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
KEY_ENV = "AGENT_EVAL_API_KEY"

MAX_ITERATIONS = 3
MAX_TOKENS_PER_CALL = 32000   # B2a: was 16000 (B1 Haiku used 14,684 on one call)
RUN_TOKEN_CAP = 120_000          # input + output, summed over a run's calls
RUN_WALL_CAP_S = 15 * 60
SPEND_CAPS = {"dry_run": 2.00,   # all calls under a tag together; each tag has its own ledger
              "pilot": 2.50,
              "full": 8.00}      # B3: the pre-registered full run (DESIGN.md section 10)
FEEDBACK_OUTPUT_CHARS = 8000     # tail of pytest output sent back
SANDBOX_TEST_TIMEOUT_S = 120

# USD per million tokens, verified 2026-11-19 against platform.claude.com/docs/en/about-claude/pricing
# (see DECISIONS.md, Stage B1). Haiku 5.5 has a higher tier for prompts over 100,000 tokens.
PRICES = {
    "claude-haiku-5-5": {"tiers": [(100_000, 0.10, 0.50), (None, 0.50, 2.50)]},
    "claude-sonnet-5-5": {"tiers": [(None, 2.00, 10.00)]},
}
CACHE_WRITE_X, CACHE_READ_X = 1.25, 0.10   # conservative (Sonnet 5.5 reads are 0.05x)

FEEDBACK_TEMPLATE = """Your test files were run with pytest on the original, unchanged module.

pytest exit code: {exit_code}
pytest output{truncated}:
```text
{output}
```

Coverage of {module}.py (coverage.py, line and branch):
```text
{coverage}
```

If you want to change the suite, reply with the complete revised test files in the same format (one fenced code block per file, first line a comment giving its path). If you are finished, reply with DONE and no code blocks."""

PARSE_ERROR_TEMPLATE = """No test file could be extracted from your reply: {problem}

Output only the test files, one fenced code block per file, first line a comment giving its path (tests/test_{module}.py)."""

OPEN_FENCE = re.compile(r"^ {0,3}```[ \t]*([^`\s]*)[ \t]*$")   # opening fence line, with its info string
CLOSE_FENCE = re.compile(r"^ {0,3}```[ \t]*$")                  # closing fence line: backticks alone
PY_INFO = {"", "python", "py", "python3"}
PATH_COMMENT = re.compile(r"^#\s*(?:path:\s*|file:\s*)?(\S+)\s*$", re.I)
ALLOWED_PATH = re.compile(r"^tests/(test_[A-Za-z0-9_]+\.py|[A-Za-z0-9_]+_test\.py|conftest\.py)$")


# ---------------------------------------------------------------- prompt
def design_prompt():
    """The section 11 draft prompt, read from DESIGN.md so the two cannot drift apart."""
    text = (ROOT / "DESIGN.md").read_text()
    sec = text.split("## 11.", 1)[1].split("\n## ", 1)[0]
    m = re.search(r"```\n(.*?)\n```", sec, re.S)
    if not m:
        raise SystemExit("DESIGN.md section 11 has no fenced prompt")
    return " ".join(m.group(1).split())   # the block is hard-wrapped; send it as one paragraph


def prompt_hash():
    return hashlib.sha256(json.dumps([design_prompt(), FEEDBACK_TEMPLATE, PARSE_ERROR_TEMPLATE]).encode()).hexdigest()


def initial_message(module, src):
    return (design_prompt().replace("<module_name>", module)
            + f"\n\nModule source ({module}.py):\n```python\n{src}\n```")


def feedback_message(module, result):
    out = result["output"]
    truncated = ""
    if len(out) > FEEDBACK_OUTPUT_CHARS:
        out, truncated = out[-FEEDBACK_OUTPUT_CHARS:], f" (last {FEEDBACK_OUTPUT_CHARS} characters)"
    return FEEDBACK_TEMPLATE.format(exit_code=result["exit_code"], truncated=truncated, output=out.rstrip(),
                                    module=module, coverage=result["coverage"].rstrip() or "(no coverage data)")


# ---------------------------------------------------------------- parsing
def _parses(src):
    try:
        ast.parse(src)
        return True
    except (SyntaxError, ValueError):
        return False


def fenced_blocks(reply_text):
    """Python fenced blocks of a reply, scanned line by line, plus a list of problems.

    B3: a block opens on a line that is ``` plus an optional info string (python, py,
    python3 or none) and closes on a line that is ``` alone. Lines inside a Python block can
    themselves be ``` (a test string holding a markdown fence), so the closing line is the
    first candidate at which the block parses with ast; if no candidate parses, the first one
    is used (the ast check after extraction then reports the file). Backticks that are not at
    the start of a line (e.g. inside a one-line string) never open or close a block. A block
    without any closing line is reported as unterminated and not extracted. Blocks with
    another info string (```text) are skipped."""
    lines = reply_text.split("\n")
    blocks, problems, i = [], [], 0
    while i < len(lines):
        m = OPEN_FENCE.match(lines[i])
        if not m:
            i += 1
            continue
        closes = [j for j in range(i + 1, len(lines)) if CLOSE_FENCE.match(lines[j])]
        if not closes:
            problems.append("unterminated code block")
            break
        if m.group(1).lower() not in PY_INFO:
            i = closes[0] + 1
            continue
        end = next((j for j in closes if _parses("\n".join(lines[i + 1:j]))), closes[0])
        blocks.append("\n".join(lines[i + 1:end]))
        i = end + 1
    return blocks, problems


def unparsable(files):
    """Paths of extracted files that ast.parse rejects (B3: such a final suite is not scored)."""
    return sorted(p for p, s in files.items() if not _parses(s))


def extract_files(reply_text):
    """{relative path under tests/: source}, plus a list of problems (fenced_blocks)."""
    files = {}
    found, problems = fenced_blocks(reply_text)
    for block in found:
        first, _, body = block.partition("\n")
        m = PATH_COMMENT.match(first.strip())
        if not m:
            problems.append(f"block without a path comment: {first[:60]!r}")
            continue
        path = m.group(1).lstrip("./")
        if not ALLOWED_PATH.match(path):
            problems.append(f"path not allowed: {path!r}")
            continue
        if path in files:
            problems.append(f"duplicate path: {path!r}")
        files[path] = block + "\n"
    return files, problems


# ---------------------------------------------------------------- sandbox feedback
def run_in_sandbox(module, src_path, files):
    """Run the writer's files with coverage on the original module in a fresh offline
    container that holds only the module and those files."""
    inc = f"/work/src/{module}.py"
    env = ["env", "-i", "PATH=/usr/local/bin:/usr/bin:/bin", "HOME=/tmp", "PYTHONPATH=/work/src",
           "PYTHONDONTWRITEBYTECODE=1", "PYTHONHASHSEED=0", "LANG=C.UTF-8"]
    with run_eval.Sandbox(module) as sb:
        sb.put({f"src/{module}.py": src_path, **{p: s.encode() for p, s in files.items()}})
        run = subprocess.run(
            ["docker", "exec", "-w", "/work", sb.name, *env, "timeout", "-s", "KILL", str(SANDBOX_TEST_TIMEOUT_S),
             "python", "-m", "coverage", "run", "--branch", "--data-file=/tmp/cov", f"--include={inc}",
             "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
            capture_output=True, text=True, timeout=SANDBOX_TEST_TIMEOUT_S + 30)
        rep = subprocess.run(["docker", "exec", "-w", "/work", sb.name, *env, "python", "-m", "coverage",
                              "report", "-m", "--data-file=/tmp/cov", f"--include={inc}"],
                             capture_output=True, text=True, timeout=60)
    exit_code = run.returncode if run.returncode != 137 else f"timeout after {SANDBOX_TEST_TIMEOUT_S} s"
    return {"exit_code": exit_code, "output": run.stdout + run.stderr,
            "coverage": rep.stdout if rep.returncode == 0 else rep.stdout + rep.stderr}


# ---------------------------------------------------------------- cost and spend guard
def cost_usd(model, usage):
    prompt = usage["input_tokens"] + usage["cache_creation_input_tokens"] + usage["cache_read_input_tokens"]
    for limit, pin, pout in PRICES[model]["tiers"]:
        if limit is None or prompt <= limit:
            break
    return (usage["input_tokens"] * pin + usage["cache_creation_input_tokens"] * pin * CACHE_WRITE_X
            + usage["cache_read_input_tokens"] * pin * CACHE_READ_X + usage["output_tokens"] * pout) / 1e6


def ledger_path(tag):
    return RUNS / tag / "ledger.jsonl"


def cumulative_spend(tag):
    p = ledger_path(tag)
    return sum(json.loads(l)["estimated_cost"] for l in p.read_text().splitlines() if l.strip()) if p.exists() else 0.0


class SpendCapError(RuntimeError):
    pass


def usage_dict(u):
    return {"input_tokens": u.input_tokens or 0, "output_tokens": u.output_tokens or 0,
            "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
            "cache_read_input_tokens": u.cache_read_input_tokens or 0}


# ---------------------------------------------------------------- model call
class HttpLog:
    """B3: every HTTP attempt the SDK makes (its own retries included), recorded through httpx
    event hooks. The retry policy itself is unchanged (SDK default, max_retries=2). Only the
    status, the request-id and the retry headers are kept; no request headers (they hold the key)."""
    RESPONSE_HEADERS = ("request-id", "retry-after", "retry-after-ms", "x-should-retry")

    def __init__(self):
        self.attempts = []

    def on_request(self, request):
        self.attempts.append({"time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                              "path": request.url.path, "status": None})

    def on_response(self, response):
        if self.attempts:
            self.attempts[-1].update(status=response.status_code,
                                     **{h: response.headers.get(h) for h in self.RESPONSE_HEADERS})

    def take(self):
        out, self.attempts = self.attempts, []
        return out


def make_client(api_key, http_log=None, transport=None):
    """`transport` is for tests only (an httpx2.MockTransport); the real run passes none."""
    import anthropic
    kw = {}
    if http_log is not None:
        hc = {"transport": transport} if transport is not None else {}
        kw["http_client"] = anthropic.DefaultHttpxClient(
            event_hooks={"request": [http_log.on_request], "response": [http_log.on_response]}, **hc)
    return anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=600.0, **kw)


def call_model(client, request):
    """Streaming call; returns (final Message, request id from the response headers or None).
    `request` is logged verbatim."""
    with client.messages.stream(**request) as stream:
        msg = stream.get_final_message()
        try:
            rid = stream.request_id
        except AttributeError:   # fakes in test_writer have no HTTP response
            rid = None
        return msg, rid


def call_record(http_log):
    """Attempts, retries and non-2xx events of the call just made; None where nothing was logged."""
    if http_log is None:
        return {"attempts": None, "retry_count": None, "http_events": None}
    att = http_log.take()
    return {"attempts": len(att), "retry_count": max(0, len(att) - 1),
            "http_events": [a for a in att if a["status"] is None or a["status"] >= 400]}


def usage_full(u):
    """The usage object as returned by the API, unmodified."""
    return u.to_dict() if hasattr(u, "to_dict") else dict(vars(u))


def replay_content(content):
    """The assistant turn as sent back: blocks passed back unchanged, minus response-only fields."""
    keep = {"text": ("type", "text"), "thinking": ("type", "thinking", "signature"),
            "redacted_thinking": ("type", "data")}
    return [{k: b[k] for k in keep[b["type"]] if k in b} for b in content if b.get("type") in keep]


def text_of(content):
    return "".join(b["text"] for b in content if b.get("type") == "text")


# ---------------------------------------------------------------- main loop
def write_suite(module, model, effort, seed, run_id, tag, client, log=print, http_log=None):
    t0 = time.monotonic()
    run_started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if tag not in SPEND_CAPS:
        raise SystemExit(f"unknown tag {tag!r}; tags with a spend cap: {sorted(SPEND_CAPS)}")
    out_dir = RUNS / tag / run_id
    if out_dir.exists():
        raise SystemExit(f"{out_dir} exists; run ids must be new")
    out_dir.mkdir(parents=True)
    meta_entry = run_eval.module_meta(module)   # any usable corpus module (corpus_final.json)
    src_path = meta_entry["module_path"]
    src = src_path.read_text()
    if run_eval.sha256(src_path.read_bytes()) != meta_entry["module_sha256"]:
        raise SystemExit(f"{module}: module_sha256 mismatch")

    transcript = (out_dir / "transcript.jsonl").open("a")

    def log_event(ev):
        transcript.write(json.dumps(ev) + "\n")
        transcript.flush()

    messages = [{"role": "user", "content": initial_message(module, src)}]
    suite, iterations, tokens_in, tokens_out, run_cost = {}, 0, 0, 0, 0.0
    stop, parse_failures, api_error, stop_reasons = None, [], None, []
    calls = []                       # B3: per-call model, request id, full usage, attempts
    sandbox_exits = {}               # iteration -> pytest exit code on the original module
    unparsable_by_iteration = {}     # iteration -> extracted files that ast.parse rejects
    while iterations < MAX_ITERATIONS:
        if time.monotonic() - t0 > RUN_WALL_CAP_S:
            stop = "wall_cap"
            break
        request = {"model": model, "max_tokens": MAX_TOKENS_PER_CALL,
                   "output_config": {"effort": effort}, "messages": messages}
        est_in = len(json.dumps(messages)) // 3 + 1   # rough overestimate of input tokens
        if tokens_in + tokens_out + est_in + MAX_TOKENS_PER_CALL > RUN_TOKEN_CAP:
            stop = "token_cap"
            break
        worst = cost_usd(model, {"input_tokens": est_in, "output_tokens": MAX_TOKENS_PER_CALL,
                                 "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0})
        spent = cumulative_spend(tag)
        if spent + worst > SPEND_CAPS[tag]:
            log_event({"event": "spend_guard", "cumulative": spent, "worst_case_next": worst})
            raise SpendCapError(f"next call could take {tag} spend from ${spent:.4f} past ${SPEND_CAPS[tag]:.2f}")
        iterations += 1
        log_event({"event": "request", "iteration": iterations, "payload": request,
                   "time": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        tc = time.monotonic()
        try:
            msg, request_id = call_model(client, request)
        except Exception as e:   # record the API's own message (it never contains the key)
            api_error = {"type": type(e).__name__, "status": getattr(e, "status_code", None),
                         "message": str(getattr(e, "message", e))[:1000]}
            rec = call_record(http_log)
            calls.append({"iteration": iterations, "response_model": None, "request_id": None,
                          "usage": None, "api_error": api_error, **rec})
            log_event({"event": "api_error", "iteration": iterations, **api_error, **rec})
            stop = "api_error"
            break
        request_id = request_id or getattr(msg, "_request_id", None)
        rec = call_record(http_log)
        reply = msg.to_dict()
        usage = usage_dict(msg.usage)
        calls.append({"iteration": iterations, "response_model": getattr(msg, "model", None),
                      "request_id": request_id, "usage": usage_full(msg.usage), "api_error": None, **rec})
        c = cost_usd(model, usage)
        tokens_in += usage["input_tokens"] + usage["cache_creation_input_tokens"] + usage["cache_read_input_tokens"]
        tokens_out += usage["output_tokens"]
        run_cost += c
        ledger_path(tag).parent.mkdir(parents=True, exist_ok=True)
        with ledger_path(tag).open("a") as f:
            f.write(json.dumps({"run_id": run_id, "iteration": iterations, "model_id": model,
                                "request_id": request_id, "response_model": calls[-1]["response_model"],
                                "retry_count": rec["retry_count"], "stop_reason": msg.stop_reason,
                                **usage, "estimated_cost": round(c, 6)}) + "\n")
        stop_reasons.append(msg.stop_reason)
        log_event({"event": "response", "iteration": iterations, "stop_reason": msg.stop_reason,
                   "reply": reply, "usage": usage, "usage_full": calls[-1]["usage"],
                   "response_model": calls[-1]["response_model"], **rec,
                   "estimated_cost": round(c, 6), "seconds": round(time.monotonic() - tc, 2),
                   "request_id": request_id})
        if cumulative_spend(tag) > SPEND_CAPS[tag]:
            raise SpendCapError(f"{tag} spend passed ${SPEND_CAPS[tag]:.2f}")
        messages = messages + [{"role": "assistant", "content": replay_content(reply["content"])}]
        if msg.stop_reason == "refusal":
            stop = "refusal"
            break
        if msg.stop_reason == "max_tokens":   # B2a: a truncated reply fails the run; it is not parsed
            stop, suite = "failed_truncated", {}
            break
        text = text_of(reply["content"])
        files, problems = extract_files(text)
        if problems:
            parse_failures.append({"iteration": iterations, "problems": problems})
        if not files:
            if suite and text.strip().upper().startswith("DONE"):
                stop = "writer_done"
                break
            if suite:
                stop = "no_files_in_revision"
                break
            if iterations >= MAX_ITERATIONS:
                break
            messages = messages + [{"role": "user", "content": PARSE_ERROR_TEMPLATE.format(
                problem="; ".join(problems) or "no fenced code blocks", module=module)}]
            continue
        suite = files
        bad = unparsable(files)
        if bad:   # recorded; the files still go to the sandbox, so the writer sees pytest's own error
            unparsable_by_iteration[iterations] = bad
        it_dir = out_dir / f"iter_{iterations}"
        for p, s in files.items():
            (it_dir / p).parent.mkdir(parents=True, exist_ok=True)
            (it_dir / p).write_text(s)
        result = run_in_sandbox(module, src_path, files)
        sandbox_exits[iterations] = result["exit_code"]
        log_event({"event": "sandbox", "iteration": iterations, **result})
        log(f"  iter {iterations}: {len(files)} file(s), pytest exit {result['exit_code']}, "
            f"{usage['input_tokens']} in / {usage['output_tokens']} out, ${c:.4f}")
        if iterations < MAX_ITERATIONS:
            messages = messages + [{"role": "user", "content": feedback_message(module, result)}]
    stop = stop or "max_iterations"
    final_unparsable = unparsable(suite)
    if final_unparsable and stop not in ("api_error", "wall_cap", "failed_truncated", "refusal"):
        stop = "extraction_failed"   # B3: visible as its own status; never scored, never repaired
    transcript.close()

    suite_dir = out_dir / "suite"
    suite_dir.mkdir()
    for p, s in suite.items():
        (suite_dir / Path(p).name).write_text(s)   # suites are flat directories
    meta = {"run_id": run_id, "tag": tag, "module": module, "model_id": model, "effort": effort,
            "seed": seed, "prompt_hash": prompt_hash(), "iterations": iterations, "stop": stop, "stop_reasons": stop_reasons,
            "tokens_in": tokens_in, "tokens_out": tokens_out, "estimated_cost": round(run_cost, 6),
            "wall_seconds": round(time.monotonic() - t0, 2), "parse_failures": parse_failures,
            "api_error": api_error, "suite_dir": (suite_dir.relative_to(ROOT) if suite_dir.is_relative_to(ROOT) else suite_dir).as_posix(),
            "suite_files": sorted(Path(p).name for p in suite),
            # B3 fields
            "run_started_at": run_started_at,
            "iterations_used": iterations,
            "suite_iterations": len(sandbox_exits),
            "first_iteration_pass": sandbox_exits.get(1) == 0,
            "unparsable_files": final_unparsable,
            "unparsable_by_iteration": unparsable_by_iteration,
            "response_models": [c["response_model"] for c in calls],
            "response_model": (calls[0]["response_model"] if calls and len({c["response_model"] for c in calls}) == 1
                               else [c["response_model"] for c in calls] or None),
            "request_ids": [c["request_id"] for c in calls],
            "usage_full": [c["usage"] for c in calls],
            "peak_input_tokens_per_call": max((c["usage"]["input_tokens"] + (c["usage"].get("cache_creation_input_tokens") or 0)
                                               + (c["usage"].get("cache_read_input_tokens") or 0)
                                               for c in calls if c["usage"]), default=None),
            "retry_count": (None if any(c["retry_count"] is None for c in calls)
                            else sum(c["retry_count"] for c in calls)),
            "api_events": [{"iteration": c["iteration"], **e} for c in calls for e in (c["http_events"] or [])]
                          + [{"iteration": c["iteration"], "api_error": c["api_error"]} for c in calls if c["api_error"]],
            "caps": {"max_iterations": MAX_ITERATIONS, "max_tokens_per_call": MAX_TOKENS_PER_CALL,
                     "run_token_cap": RUN_TOKEN_CAP, "run_wall_cap_s": RUN_WALL_CAP_S,
                     "spend_cap_usd": SPEND_CAPS[tag]},
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", required=True)
    ap.add_argument("--model", required=True, choices=sorted(PRICES))
    ap.add_argument("--effort", required=True, choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--seed", required=True, help="replicate label, e.g. s1 (the API has no seed)")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--tag", default="dry_run", choices=sorted(SPEND_CAPS))
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", a.run_id):
        raise SystemExit("run id: letters, digits, _ . - only")
    if a.tag == "full" and not run_eval.prereg_commit():   # B3: the full run needs the frozen design
        raise SystemExit(f"tag full needs the {run_eval.PREREG_TAG} git tag")
    api_key = os.environ.pop(KEY_ENV, None)   # removed before any subprocess (docker) starts
    os.environ.pop("ANTHROPIC_API_KEY", None)
    if not api_key:
        raise SystemExit(f"{KEY_ENV} is not set")
    run_eval.build_and_verify_image()
    http_log = HttpLog()
    client = make_client(api_key, http_log)
    del api_key
    print(f"{a.run_id}: {a.module} {a.model} effort={a.effort} seed={a.seed}")
    try:
        meta = write_suite(a.module, a.model, a.effort, a.seed, a.run_id, a.tag, client, http_log=http_log)
    except SpendCapError as e:
        print(f"STOP: spend guard: {e}. cumulative {a.tag} spend ${cumulative_spend(a.tag):.4f}")
        return 2
    print(f"  stop={meta['stop']} iterations={meta['iterations']} tokens {meta['tokens_in']} in / "
          f"{meta['tokens_out']} out, run cost ${meta['estimated_cost']:.4f}, wall {meta['wall_seconds']:.0f}s, "
          f"parse problems={len(meta['parse_failures'])}, api_error={meta['api_error']}")
    print(f"  cumulative {a.tag} spend: ${cumulative_spend(a.tag):.4f} (cap ${SPEND_CAPS[a.tag]:.2f})")
    return 0 if meta["stop"] not in ("api_error", "wall_cap", "failed_truncated", "extraction_failed") \
        and meta["suite_files"] else 1


if __name__ == "__main__":
    sys.exit(main())
