# tests/test_zagentic_ir_schema.py
import copy
import pytest

import zagentic_ir_schema as m


def make_view():
    return {
        "envelope": {k: None for k in m.ENVELOPE_KEYS} | {"schema": m.VIEW_IR_SCHEMA_VERSION},
        "selection": {k: None for k in m.SELECTION_KEYS},
        "rest": {},
        "expanded_set": [],
        "cards": {"a": {k: None for k in m.CARD_KEYS}},
        "presets": {},
    }


def test_version_constant():
    assert m.VIEW_IR_SCHEMA_VERSION == "zj-roadmap-view-ir/v1"


def test_frozen_set_sizes():
    assert len(m.TOP_LEVEL_KEYS) == 6
    assert len(m.ENVELOPE_KEYS) == 9
    assert len(m.SELECTION_KEYS) == 12
    assert len(m.CARD_KEYS) == 19


def test_valid_view():
    assert m.validate_view(make_view()) == []
    m.assert_frozen(make_view())


def test_empty_cards_ok():
    v = make_view()
    v["cards"] = {}
    assert m.validate_view(v) == []


def test_cards_as_list():
    v = make_view()
    v["cards"] = [{k: 1 for k in m.CARD_KEYS}]
    assert m.validate_view(v) == []
    v["cards"][0]["bogus"] = 1
    errs = m.validate_view(v)
    assert len(errs) == 1 and "card[0]" in errs[0]


def test_top_level_missing_and_extra():
    v = make_view()
    del v["presets"]
    v["zzz"] = 1
    errs = m.validate_view(v)
    assert len(errs) == 1
    assert "missing=['presets']" in errs[0]
    assert "extra=['zzz']" in errs[0]
    assert errs[0].startswith("view:")


def test_wrong_schema_version():
    v = make_view()
    v["envelope"]["schema"] = "other"
    errs = m.validate_view(v)
    assert len(errs) == 1
    assert "envelope.schema must be" in errs[0]
    assert m.VIEW_IR_SCHEMA_VERSION in errs[0]


def test_envelope_key_drift():
    v = make_view()
    v["envelope"]["new"] = 1
    del v["envelope"]["focus"]
    errs = m.validate_view(v)
    assert len(errs) == 1
    assert errs[0].startswith("envelope:")
    assert "focus" in errs[0] and "new" in errs[0]


def test_selection_key_drift():
    v = make_view()
    del v["selection"]["fp"]
    errs = m.validate_view(v)
    assert errs == ["selection: missing=['fp'] extra=[]"]


def test_card_drift_reports_id():
    v = make_view()
    v["cards"]["b"] = {k: 0 for k in m.CARD_KEYS}
    v["cards"]["b"]["x"] = 1
    del v["cards"]["b"]["doi"]
    errs = m.validate_view(v)
    assert errs == ["card[b]: missing=['doi'] extra=['x']"]


def test_missing_envelope_and_selection():
    v = make_view()
    del v["envelope"]
    del v["selection"]
    errs = m.validate_view(v)
    assert any(e.startswith("view:") for e in errs)
    assert any("envelope.schema" in e for e in errs)
    assert any(e.startswith("envelope:") for e in errs)
    assert any(e.startswith("selection:") for e in errs)


def test_empty_view():
    assert len(m.validate_view({})) >= 4


def test_assert_frozen_raises():
    v = make_view()
    v["extra"] = 1
    with pytest.raises(ValueError, match="view-ir schema drift"):
        m.assert_frozen(v)


def test_assert_frozen_truncates_to_three():
    v = {}
    with pytest.raises(ValueError) as ei:
        m.assert_frozen(v)
    assert str(ei.value).count("; ") <= 2


def test_does_not_mutate():
    v = make_view()
    c = copy.deepcopy(v)
    m.validate_view(v)
    assert v == c
