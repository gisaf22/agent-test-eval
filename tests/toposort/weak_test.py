from toposort import toposort, toposort_flatten


def test_simple_order():
    result = list(toposort({2: {1}, 3: {2}}))
    assert len(result) > 0


def test_flatten_returns_list():
    assert isinstance(toposort_flatten({2: {1}}), list)
