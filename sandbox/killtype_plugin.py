"""pytest plugin (loaded with -p killtype_plugin): records why the run failed.

The first failure is written to $KILLTYPE_OUT as {"phase", "exc_type", "kind"}:
  kind = "collection_error"  the test module could not be collected/imported
                             (e.g. the mutated module raises at import time)
         "assertion"         a test body raised AssertionError (incl. unittest
                             assert*) or pytest's Failed (pytest.raises
                             "DID NOT RAISE", pytest.fail)
         "test_exception"    any other exception during a test's setup, call
                             or teardown
A failing run with nothing recorded is classified "crash" by runner.py.
"""
import json
import os

import pytest

OUT = os.environ.get("KILLTYPE_OUT", "/tmp/killtype.json")
_done = False


def _record(d):
    global _done
    if not _done:
        _done = True
        with open(OUT, "w") as f:
            json.dump(d, f)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.failed and call.excinfo is not None:
        exc = call.excinfo.value
        is_assert = isinstance(exc, (AssertionError, pytest.fail.Exception))
        _record({"phase": rep.when, "exc_type": type(exc).__name__,
                 "kind": "assertion" if (is_assert and rep.when == "call") else "test_exception"})


def pytest_collectreport(report):
    if report.failed:
        exc_type = "CollectionError"
        try:
            exc_type = report.longrepr.reprcrash.message.split(":", 1)[0]
        except AttributeError:
            pass
        _record({"phase": "collect", "exc_type": exc_type, "kind": "collection_error"})
