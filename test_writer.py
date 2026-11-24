"""Isolation checks for writer.py: no request the writer sends may contain mutants, scores,
reference suites (null/weak/strong) or upstream tests.

Two parts:
  * a synthetic loop with a fake model client and a fake sandbox (no API calls, no Docker),
    which also checks that the feedback sandbox receives only the module and the writer's files;
  * every saved transcript under runs/*/*/transcript.jsonl (the real B1 runs), if any.

Run: .venv/bin/python -m unittest test_writer -v
"""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import writer

ROOT = Path(__file__).resolve().parent
MODULES = ["toposort", "heapdict", "mergedeep", "addict", "angelbot_context_acl"]
# Words that would only reach the writer through a leak. A word is allowed when it also
# occurs in something the writer may see anyway: the module source or its own replies.
FORBIDDEN_WORDS = ["mutant", "mutation", "mutmut", "cosmic", "survived", "killed", "score",
                   "strong_test", "weak_test", "null_test", "upstream", "results.jsonl",
                   "results_mutants", "mutants.json", "kill_kind", "trivially"]


def reference_lines(module):
    """Distinctive lines of every reference and upstream test file for the module."""
    out = set()
    upstream_txt = ROOT / "corpus" / module / "upstream_test.txt"   # B2c: new modules' upstream tests
    for p in sorted((ROOT / "tests" / module).glob("*.py")) + ([upstream_txt] if upstream_txt.exists() else []):
        for line in p.read_text().splitlines():
            line = line.strip()
            if len(line) >= 20:
                out.add(line)
    return out


def payload_leaks(payload, module):
    """Problems found in one logged request payload (empty list = clean)."""
    problems = []
    if payload.get("system"):
        problems.append("payload has a system prompt")
    if any(k in payload for k in ("temperature", "top_p", "top_k")):
        problems.append("payload sets a sampling parameter")
    src = (ROOT / "corpus" / module / f"{module}.py").read_text()
    own, shown = [], []
    for m in payload["messages"]:
        content = m["content"]
        texts = [content] if isinstance(content, str) else [b.get("text", "") for b in content]
        (own if m["role"] == "assistant" else shown).extend(texts)
    allowed = (src + "\n" + "\n".join(own)).lower()
    shown_text = "\n".join(shown)
    low = shown_text.lower()
    for w in FORBIDDEN_WORDS:
        if w in low and w not in allowed:
            problems.append(f"forbidden word {w!r}")
    allowed_lines = {l.strip() for l in (src + "\n" + "\n".join(own)).splitlines()}
    for line in reference_lines(module):
        if line in shown_text and line not in allowed_lines:
            problems.append(f"reference-suite line: {line[:60]!r}")
    if re.search(r"\b0\.\d{4}\b", shown_text) and not re.search(r"\b0\.\d{4}\b", src + "".join(own)):
        problems.append("score-like number")
    return problems


# ---------------------------------------------------------------- fakes
GOOD_REPLY = """```python
# tests/test_{m}.py
import {m}


def test_imports():
    assert {m} is not None
```"""


class FakeMessage:
    def __init__(self, text):
        self._text = text
        self.stop_reason = "end_turn"
        self.usage = SimpleNamespace(input_tokens=1000, output_tokens=500,
                                     cache_creation_input_tokens=0, cache_read_input_tokens=0)
        self._request_id = "req_fake"

    def to_dict(self):
        return {"id": "msg_fake", "type": "message", "role": "assistant", "stop_reason": self.stop_reason,
                "content": [{"type": "thinking", "thinking": "", "signature": "sig"},
                            {"type": "text", "text": self._text}]}


class FakeClient:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.messages = self

    def stream(self, **request):
        self.requests.append(json.loads(json.dumps(request)))
        msg = FakeMessage(self.replies.pop(0))

        class Ctx:
            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

            def get_final_message(s):
                return msg
        return Ctx()


class FakeSandbox:
    puts = []

    def __init__(self, module):
        self.name = f"ate-{module}-fake"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def put(self, files):
        FakeSandbox.puts.append(sorted(files))


def fake_run(cmd, **kw):
    if "report" in cmd:
        return subprocess.CompletedProcess(cmd, 0, "Name  Stmts  Miss Branch BrPart  Cover\nsrc/m.py 10 2 4 1 75%\n", "")
    return subprocess.CompletedProcess(cmd, 1, "F.\nFAILED tests/test_x.py::test_a - assert 1 == 2\n1 failed, 1 passed\n", "")


class SyntheticLoop(unittest.TestCase):
    def test_payloads_clean_and_sandbox_holds_only_module_and_writer_files(self):
        for m in MODULES:
            with self.subTest(module=m), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(writer, "RUNS", Path(tmp)), \
                    mock.patch.object(writer.run_eval, "Sandbox", FakeSandbox), \
                    mock.patch.object(writer.subprocess, "run", fake_run):
                FakeSandbox.puts = []
                client = FakeClient([GOOD_REPLY.format(m=m), "no code here", GOOD_REPLY.format(m=m)])
                meta = writer.write_suite(m, "claude-haiku-5-5", "low", "s0", "synthetic", "dry_run", client,
                                          log=lambda *a: None)
                self.assertEqual(meta["iterations"], 2)          # 2nd reply has no files -> stop
                self.assertEqual(meta["stop"], "no_files_in_revision")
                self.assertEqual(len(client.requests), 2)
                for req in client.requests:
                    self.assertEqual(payload_leaks(req, m), [])
                    self.assertEqual(req["output_config"], {"effort": "low"})
                for keys in FakeSandbox.puts:
                    self.assertEqual(keys, sorted([f"src/{m}.py", f"tests/test_{m}.py"]))
                logged = [json.loads(l)["payload"] for l in
                          (Path(tmp) / "dry_run" / "synthetic" / "transcript.jsonl").read_text().splitlines()
                          if json.loads(l)["event"] == "request"]
                self.assertEqual(logged, client.requests)

    def test_max_tokens_reply_fails_run_without_parsing(self):
        m = "toposort"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(writer, "RUNS", Path(tmp)), \
                mock.patch.object(writer.run_eval, "Sandbox", FakeSandbox), \
                mock.patch.object(writer.subprocess, "run", fake_run), \
                mock.patch.object(writer, "extract_files", side_effect=AssertionError("parsed")):
            FakeSandbox.puts = []
            client = FakeClient([GOOD_REPLY.format(m=m)])
            orig = FakeMessage.__init__

            def truncated(self, text):
                orig(self, text)
                self.stop_reason = "max_tokens"
            with mock.patch.object(FakeMessage, "__init__", truncated):
                meta = writer.write_suite(m, "claude-haiku-5-5", "low", "s0", "trunc", "dry_run", client,
                                          log=lambda *a: None)
            self.assertEqual((meta["stop"], meta["suite_files"], meta["stop_reasons"]),
                             ("failed_truncated", [], ["max_tokens"]))
            self.assertEqual(FakeSandbox.puts, [])
            self.assertEqual(len(client.requests), 1)
            self.assertEqual(client.requests[0]["max_tokens"], 32000)

    def test_spend_caps_are_per_tag(self):
        # B3 adds the full-run guard (DESIGN.md section 10); the existing caps are unchanged.
        self.assertEqual(writer.SPEND_CAPS, {"dry_run": 2.00, "pilot": 2.50, "full": 8.00})
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(writer, "RUNS", Path(tmp)):
            (Path(tmp) / "pilot").mkdir()
            (Path(tmp) / "pilot" / "ledger.jsonl").write_text(json.dumps({"estimated_cost": 2.49}) + "\n")
            self.assertEqual(writer.cumulative_spend("dry_run"), 0.0)   # separate ledgers
            client = FakeClient([GOOD_REPLY.format(m="toposort")])
            with self.assertRaises(writer.SpendCapError):            # worst case of the next call passes 2.50
                writer.write_suite("toposort", "claude-sonnet-5-5", "low", "s0", "guard", "pilot", client,
                                   log=lambda *a: None)
            self.assertEqual(client.requests, [])
            with self.assertRaises(SystemExit):
                writer.write_suite("toposort", "claude-sonnet-5-5", "low", "s0", "x", "other", client)

    def test_failed_writer_run_gets_an_unscored_row(self):
        """B2c: failed runs are recorded as rows with null scores, never scored or dropped."""
        meta = {"run_id": "f", "tag": "pilot", "module": "toposort", "model_id": "claude-sonnet-5-5",
                "effort": "low", "prompt_hash": "h", "tokens_in": 10, "tokens_out": 32000,
                "estimated_cost": 0.32, "seed": "s1", "iterations": 1, "stop": "failed_truncated",
                "wall_seconds": 1.0, "parse_failures": [], "api_error": None,
                "stop_reasons": ["max_tokens"], "suite_files": []}
        row = writer.run_eval.failed_writer_row(meta)
        self.assertEqual((row["arm_status"], row["valid"], row["mutation_score"], row["kept_fraction"],
                          row["writer_stop"], row["tag"]),
                         ("writer_failed", False, None, None, "failed_truncated", "pilot"))
        self.assertIn("failed_truncated", writer.run_eval.WRITER_FAILED_STOPS)

    def test_detector_catches_leaks(self):
        """The check itself must fire on planted leaks."""
        m = "toposort"
        src_lines = {l.strip() for l in (ROOT / "corpus" / m / f"{m}.py").read_text().splitlines()}
        line = next(l for l in sorted(reference_lines(m)) if l not in src_lines)
        for planted in ["mutation score 0.8667", "see strong_test.py", line]:
            payload = {"messages": [{"role": "user", "content": "hello\n" + planted}]}
            self.assertNotEqual(payload_leaks(payload, m), [], planted)


TICKS = "`" * 3


class Extraction(unittest.TestCase):
    """B3: fenced-code extraction and the ast check."""

    def test_backticks_inside_test_strings(self):
        body = (f'# tests/test_m.py\nimport m\n\n\ndef test_inline():\n    assert m.f("{TICKS}py\\nx\\n{TICKS}") == 1\n\n\n'
                f'DOC = """\n{TICKS}\nnot a fence\n{TICKS}\n"""\n\n\ndef test_doc():\n    assert DOC')
        reply = f"Here are the tests.\n\n{TICKS}python\n{body}\n{TICKS}\n\nDone."
        files, problems = writer.extract_files(reply)
        self.assertEqual(problems, [])
        self.assertEqual(files, {"tests/test_m.py": body + "\n"})

    def test_two_blocks_and_a_skipped_text_block(self):
        a, b = "# tests/test_a.py\nx = 1", "# tests/conftest.py\ny = 2"
        reply = f"{TICKS}python\n{a}\n{TICKS}\n\n{TICKS}text\noutput\n{TICKS}\n\n{TICKS}py\n{b}\n{TICKS}\n"
        files, problems = writer.extract_files(reply)
        self.assertEqual((files, problems), ({"tests/test_a.py": a + "\n", "tests/conftest.py": b + "\n"}, []))

    def test_unterminated_block_is_reported_and_not_extracted(self):
        files, problems = writer.extract_files(f"{TICKS}python\n# tests/test_a.py\nx = 1\n")
        self.assertEqual((files, problems), ({}, ["unterminated code block"]))

    def test_unparsable_file_is_detected(self):
        self.assertEqual(writer.unparsable({"tests/test_a.py": "def f(:\n", "tests/test_b.py": "x = 1\n"}),
                         ["tests/test_a.py"])

    def test_final_suite_that_does_not_parse_is_extraction_failed_and_unscored(self):
        m = "toposort"
        broken = f"{TICKS}python\n# tests/test_{m}.py\nimport {m}\n\ndef test_x(:\n    pass\n{TICKS}"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(writer, "RUNS", Path(tmp)), \
                mock.patch.object(writer.run_eval, "Sandbox", FakeSandbox), \
                mock.patch.object(writer.subprocess, "run", fake_run):
            client = FakeClient([broken, "DONE"])
            meta = writer.write_suite(m, "claude-haiku-5-5", "low", "s0", "bad", "dry_run", client,
                                      log=lambda *a: None)
        self.assertEqual(meta["stop"], "extraction_failed")
        self.assertEqual(meta["unparsable_files"], [f"tests/test_{m}.py"])
        self.assertEqual(meta["unparsable_by_iteration"], {1: [f"tests/test_{m}.py"]})
        self.assertIn("extraction_failed", writer.run_eval.WRITER_FAILED_STOPS)
        row = writer.run_eval.failed_writer_row({**meta, "tag": "dry_run"})
        self.assertEqual((row["arm_status"], row["mutation_score"], row["kept_fraction"]),
                         ("extraction_failed", None, None))

    def test_saved_transcripts_extract_the_files_on_disk(self):
        """Every saved reply still extracts exactly the files its iteration directory holds."""
        n = 0
        for p in sorted(ROOT.glob("runs/*/*/transcript.jsonl")):
            for line in p.read_text().splitlines():
                ev = json.loads(line)
                if ev["event"] != "response":
                    continue
                files, problems = writer.extract_files(writer.text_of(ev["reply"]["content"]))
                it_dir = p.parent / f"iter_{ev['iteration']}"
                on_disk = ({q.relative_to(it_dir).as_posix(): q.read_text() for q in it_dir.rglob("*.py")}
                           if it_dir.exists() else {})
                with self.subTest(run=p.parent.name, iteration=ev["iteration"]):
                    self.assertEqual(files, on_disk)
                    self.assertEqual(problems, [])
                    self.assertEqual(writer.unparsable(files), [])
                n += bool(files)
        if not n:
            self.skipTest("no saved transcripts")


SSE = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in [
    ("message_start", {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5", "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1200, "output_tokens": 1}}}),
    ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0,
                             "delta": {"type": "text_delta", "text": GOOD_REPLY.format(m="toposort")}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                       "usage": {"output_tokens": 40}}),
    ("message_stop", {"type": "message_stop"})])


class ApiLogging(unittest.TestCase):
    """B3: request ids, response model, full usage, retries and rate-limit events, through the real
    SDK against an httpx2.MockTransport (no network, no API call)."""

    def test_retry_and_rate_limit_are_logged(self):
        import httpx2
        seen = []

        def handler(request):
            seen.append(request)
            if len(seen) == 1:
                return httpx2.Response(429, headers={"request-id": "req_429", "retry-after": "0",
                                                     "x-should-retry": "true"},
                                       json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}})
            return httpx2.Response(200, headers={"request-id": "req_ok", "content-type": "text/event-stream"},
                                   content=SSE.encode())
        log = writer.HttpLog()
        client = writer.make_client("sk-test-not-a-key", log, transport=httpx2.MockTransport(handler))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(writer, "RUNS", Path(tmp)), \
                mock.patch.object(writer.run_eval, "Sandbox", FakeSandbox), \
                mock.patch.object(writer.subprocess, "run", fake_run), \
                mock.patch.object(writer, "MAX_ITERATIONS", 1):
            meta = writer.write_suite("toposort", "claude-sonnet-5-5", "low", "s0", "api", "dry_run", client,
                                      log=lambda *a: None, http_log=log)
            ledger = [json.loads(l) for l in (Path(tmp) / "dry_run" / "ledger.jsonl").read_text().splitlines()]
        self.assertEqual(len(seen), 2)
        self.assertEqual(meta["request_ids"], ["req_ok"])
        self.assertEqual(meta["response_model"], "claude-sonnet-5-5")
        self.assertEqual(meta["retry_count"], 1)
        self.assertEqual([(e["status"], e["request-id"]) for e in meta["api_events"]], [(429, "req_429")])
        self.assertEqual(meta["usage_full"][0]["input_tokens"], 1200)
        self.assertEqual(meta["peak_input_tokens_per_call"], 1200)
        self.assertEqual((meta["iterations_used"], meta["first_iteration_pass"]), (1, False))   # fake_run exits 1
        self.assertEqual((ledger[0]["request_id"], ledger[0]["retry_count"]), ("req_ok", 1))
        self.assertTrue(meta["run_started_at"])

    def test_fake_client_marks_retry_count_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(writer, "RUNS", Path(tmp)), \
                mock.patch.object(writer.run_eval, "Sandbox", FakeSandbox), \
                mock.patch.object(writer.subprocess, "run", fake_run):
            meta = writer.write_suite("toposort", "claude-haiku-5-5", "low", "s0", "f", "dry_run",
                                      FakeClient([GOOD_REPLY.format(m="toposort"), "DONE"]), log=lambda *a: None)
        self.assertIsNone(meta["retry_count"])
        self.assertEqual(meta["api_events"], [])


class SavedTranscripts(unittest.TestCase):
    def test_every_logged_payload_is_clean(self):
        paths = sorted(ROOT.glob("runs/*/*/transcript.jsonl"))
        if not paths:
            self.skipTest("no saved transcripts")
        for p in paths:
            meta = json.loads((p.parent / "meta.json").read_text()) if (p.parent / "meta.json").exists() else None
            module = meta["module"] if meta else None
            for line in p.read_text().splitlines():
                ev = json.loads(line)
                if ev["event"] != "request":
                    continue
                with self.subTest(run=p.parent.name, iteration=ev["iteration"]):
                    self.assertIsNotNone(module)
                    self.assertEqual(payload_leaks(ev["payload"], module), [])


if __name__ == "__main__":
    unittest.main()
