"""Run a unittest.main()-style test file as __main__, unedited, and record
whether it failed before unittest took over (collection/import error).

usage: python script_wrapper.py <test_file> [unittest args...]
unittest itself catches every exception raised inside a test, so any exception
(other than SystemExit) escaping the module body happened at import/collection
time, e.g. `from <module> import ...` on a mutant that raises at import.

The same environment variables as suite_plugin.py apply (all optional, inert when unset):
SUITE_ORDER_SEED shuffles the flattened test list, SUITE_DESELECT drops test ids,
SUITE_OUTCOMES records each test's outcome. Ids are unittest ids (`__main__.Class.method`).
"""
import json
import os
import random
import runpy
import sys
import unittest

ORDER_SEED = os.environ.get("SUITE_ORDER_SEED")
DESELECT = os.environ.get("SUITE_DESELECT")
OUTCOMES = os.environ.get("SUITE_OUTCOMES")
_outcomes = {}


def _flatten(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _flatten(t)
        else:
            yield t


if ORDER_SEED is not None or DESELECT:
    _orig_run_tests = unittest.TestProgram.runTests

    def _run_tests(self):
        tests = list(_flatten(self.test))
        if DESELECT:
            with open(DESELECT) as f:
                drop = set(json.load(f))
            tests = [t for t in tests if t.id() not in drop]
        if ORDER_SEED is not None:
            random.Random(int(ORDER_SEED)).shuffle(tests)
        self.test = unittest.TestSuite(tests)
        return _orig_run_tests(self)

    unittest.TestProgram.runTests = _run_tests

if OUTCOMES:
    class _Recording(unittest.TextTestResult):
        def _set(self, test, outcome):
            if _outcomes.get(test.id()) != "failed":
                _outcomes[test.id()] = outcome

        def addSuccess(self, test):
            super().addSuccess(test); self._set(test, "passed")

        def addFailure(self, test, err):
            super().addFailure(test, err); self._set(test, "failed")

        def addError(self, test, err):
            super().addError(test, err); self._set(test, "failed")

        def addSkip(self, test, reason):
            super().addSkip(test, reason); self._set(test, "skipped")

        def addExpectedFailure(self, test, err):
            super().addExpectedFailure(test, err); self._set(test, "passed")

        def addUnexpectedSuccess(self, test):
            super().addUnexpectedSuccess(test); self._set(test, "failed")

    unittest.TextTestRunner.resultclass = _Recording


def _dump(collection_errors):
    if OUTCOMES:
        with open(OUTCOMES, "w") as f:
            json.dump({"tests": _outcomes, "collection_errors": collection_errors}, f)


path = sys.argv[1]
sys.argv = [path] + sys.argv[2:]
sys.path[0] = os.path.dirname(os.path.abspath(path))
try:
    runpy.run_path(path, run_name="__main__")
except SystemExit:
    _dump([])
    raise
except BaseException as e:  # noqa: B902 - classify, then fail
    _dump([path])
    with open(os.environ["KILLTYPE_OUT"], "w") as f:
        json.dump({"phase": "collect", "exc_type": type(e).__name__,
                   "kind": "collection_error"}, f)
    sys.exit(3)
_dump([])
