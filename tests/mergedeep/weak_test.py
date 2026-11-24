from mergedeep import merge


def test_merge_two_dicts():
    result = merge({}, {"a": 1}, {"b": 2})
    assert "a" in result


def test_merge_returns_dict():
    assert isinstance(merge({}, {"x": {"y": 1}}), dict)
