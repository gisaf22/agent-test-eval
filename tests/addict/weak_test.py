from addict import Dict


def test_attribute_access():
    d = Dict(a=1)
    assert d.a == 1


def test_is_a_dict():
    assert isinstance(Dict(), dict)
