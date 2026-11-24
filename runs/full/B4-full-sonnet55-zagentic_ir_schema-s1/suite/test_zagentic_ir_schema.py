# tests/test_zagentic_ir_schema.py
import copy

import pytest

import zagentic_ir_schema as m


def make_view():
    return {
        "envelope": {k: None for k in m.ENVELOPE_KEYS}
        | {"schema": m.VIEW_IR_SCHEMA_VERSION},
        "selection": {k: None for k in m.SELECTION_KEYS},
        "rest": [],
        "expanded_set": [],
        "cards": {"a": {k: None for k in m.CARD_KEYS}},
        "presets": {},
    }


def test_valid_view():
    assert m.validate_view(make_view()) == []
    m.assert_frozen(make_view())


def test_version_constant():
    assert m.VIEW_IR_SCHEMA_VERSION == "zj-roadmap-view-ir/v1"


def test_frozen_set_sizes():
    assert len(m.TOP_LEVEL_KEYS) == 6
    assert len(m.ENVELOPE_KEYS) == 9
    assert len(m.SELECTION_KEYS) == 12
    assert len(m.CARD_KEYS) == 19


def test_top_level_missing_and_extra():
    v = make_view()
    del v["rest"]
    v["bogus"] = 1
    errs = m.validate_view(v)
    assert any(e.startswith("view:") and "'rest'" in e and "'bogus'" in e for e in errs)


def test_wrong_schema_version():
    v = make_view()
    v["envelope"]["schema"] = "other"
    errs = m.validate_view(v)
    assert len(errs) == 1
    assert "envelope.schema" in errs[0]


def test_missing_envelope_reports_errors():
    v = make_view()
    del v["envelope"]
    errs = m.validate_view(v)
    assert any(e.startswith("view:") for e in errs)
    assert any("envelope.schema" in e for e in errs)
    assert any(e.startswith("envelope:") for e in errs)


def test_envelope_extra_key():
    v = make_view()
    v["envelope"]["x"] = 1
    errs = m.validate_view(v)
    assert len(errs) == 1 and errs[0].startswith("envelope:") and "'x'" in errs[0]


def test_selection_missing_key():
    v = make_view()
    del v["selection"]["fp"]
    errs = m.validate_view(v)
    assert len(errs) == 1 and errs[0].startswith("selection:") and "'fp'" in errs[0]


def test_card_drift_dict():
    v = make_view()
    v["cards"]["a"]["new"] = 1
    del v["cards"]["a"]["doi"]
    errs = m.validate_view(v)
    assert len(errs) == 1 and errs[0].startswith("card[a]:")
    assert "'new'" in errs[0] and "'doi'" in errs[0]


def test_cards_as_list_uses_index():
    v = make_view()
    v["cards"] = [{k: None for k in m.CARD_KEYS}, {"id": 1}]
    errs = m.validate_view(v)
    assert len(errs) == 1 and errs[0].startswith("card[1]:")


def test_empty_cards_ok():
    v = make_view()
    v["cards"] = {}
    assert m.validate_view(v) == []


def test_multiple_cards_each_reported():
    v = make_view()
    v["cards"]["b"] = {}
    v["cards"]["c"] = {}
    errs = m.validate_view(v)
    assert len(errs) == 2


def test_assert_frozen_raises():
    v = make_view()
    v["extra"] = 1
    with pytest.raises(ValueError, match="view-ir schema drift"):
        m.assert_frozen(v)


def test_assert_frozen_truncates_to_three():
    v = make_view()
    v["envelope"]["schema"] = "bad"
    v["envelope"]["q"] = 1
    v["selection"]["q"] = 1
    v["extra"] = 1
    v["cards"]["a"]["q"] = 1
    with pytest.raises(ValueError) as ei:
        m.assert_frozen(v)
    assert str(ei.value).count(";") == 2


def test_does_not_mutate_input():
    v = make_view()
    snap = copy.deepcopy(v)
    m.validate_view(v)
    assert v == snap
