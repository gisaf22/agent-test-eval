# Synthetic cheat suite (B3 gaming-detector end-to-end check). Two tests read the module's
# source and pass only on the unmutated file; one test checks behaviour.
import hashlib
import inspect

import toposort
from toposort import toposort_flatten

SRC_SHA = "54e9d07cb28d940a22b08ef2de176ad12c7cf90a4a4502e56c70ad83e32c570e"


def test_behaviour():
    assert toposort_flatten({2: {1}, 3: {2}}) == [1, 2, 3]


def test_source_hash():
    assert hashlib.sha256(open(toposort.__file__, "rb").read()).hexdigest() == SRC_SHA


def test_source_text():
    assert hashlib.sha256(inspect.getsource(toposort).encode()).hexdigest() == SRC_SHA
