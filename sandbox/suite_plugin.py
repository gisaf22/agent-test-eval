"""pytest plugin (loaded with -p suite_plugin): test order, deselection, per-test outcomes.

Inert unless its environment variables are set, so scoring runs keep pytest's own order.
  SUITE_ORDER_SEED  integer: shuffle the collected items with random.Random(seed)
  SUITE_DESELECT    path to a JSON list of node ids to drop (tests found invalid)
  SUITE_OUTCOMES    path: write {"tests": {nodeid: "passed"|"failed"|"skipped"},
                    "collection_errors": [...]} at session end
"""
import json
import os
import random

import pytest

_outcomes = {}
_collect_errors = []


def pytest_collection_modifyitems(session, config, items):
    path = os.environ.get("SUITE_DESELECT")
    if path:
        with open(path) as f:
            drop = set(json.load(f))
        gone = [it for it in items if it.nodeid in drop]
        items[:] = [it for it in items if it.nodeid not in drop]
        if gone:
            config.hook.pytest_deselected(items=gone)
    seed = os.environ.get("SUITE_ORDER_SEED")
    if seed is not None:
        random.Random(int(seed)).shuffle(items)


def pytest_runtest_logreport(report):
    if not os.environ.get("SUITE_OUTCOMES"):
        return
    prev = _outcomes.get(report.nodeid)
    if report.failed:
        _outcomes[report.nodeid] = "failed"
    elif report.skipped and prev is None:
        _outcomes[report.nodeid] = "skipped"
    elif report.when == "call" and report.passed and prev is None:
        _outcomes[report.nodeid] = "passed"


def pytest_collectreport(report):
    if report.failed:
        _collect_errors.append(report.nodeid)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("SUITE_OUTCOMES")
    if path:
        with open(path, "w") as f:
            json.dump({"tests": _outcomes, "collection_errors": _collect_errors}, f)
