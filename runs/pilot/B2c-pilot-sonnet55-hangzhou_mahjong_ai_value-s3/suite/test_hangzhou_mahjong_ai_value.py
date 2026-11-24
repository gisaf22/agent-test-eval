# tests/test_hangzhou_mahjong_ai_value.py
import pytest
import hangzhou_mahjong_ai_value as m


def test_table_shapes():
    assert len(m.V[16]) == 17
    assert len(m.V[8]) == 9
    for t in m.V.values():
        assert all(len(r) == 4 for r in t)
        assert t[0] == [0.0] * 4


@pytest.mark.parametrize("total", [16, 8])
def test_lookup_matches_table(total):
    for h in range(1, len(m.V[total])):
        for d in range(4):
            assert m.start_value(d, h, total) == m.V[total][h][d]


@pytest.mark.parametrize("h", [0, -1, -100])
def test_game_over_zero(h):
    assert m.start_value(0, h, 16) == 0.0
    assert m.start_value(1, h, 8) == 0.0


def test_dealer_rel_modulo():
    assert m.start_value(4, 3, 16) == m.V[16][3][0]
    assert m.start_value(7, 3, 16) == m.V[16][3][3]
    assert m.start_value(-1, 3, 16) == m.V[16][3][3]


def test_unknown_total_defaults_to_16():
    assert m.start_value(1, 5, 12) == m.V[16][5][1]


def test_hands_left_clamped():
    assert m.start_value(0, 100, 16) == m.V[16][16][0]
    assert m.start_value(2, 50, 8) == m.V[8][8][2]


def test_float_and_string_coercion():
    assert m.start_value(1.0, 4.0, 8.0) == m.V[8][4][1]


def test_extra_args_ignored():
    assert m.start_value(0, 4, 16, scores=[1, 2, 3, 4], seat=2) == m.V[16][4][0]


def test_after_hand_last():
    info = {"last": True, "dealer": 0, "seat": 1, "rounds": 16, "hand_no": 16}
    assert m.after_hand(info) == 0.0


def test_after_hand_next():
    info = {"last": False, "dealer": 1, "seat": 3, "rounds": 16, "hand_no": 1}
    # rel = (1-3)%4 = 2; hands_left = 16
    assert m.after_hand(info) == m.V[16][16][2]


def test_after_hand_8():
    info = {"last": False, "dealer": 0, "seat": 1, "rounds": 8, "hand_no": 7}
    assert m.after_hand(info) == m.V[8][2][3]


def test_after_hand_penultimate():
    info = {"last": False, "dealer": 2, "seat": 2, "rounds": 16, "hand_no": 15}
    assert m.after_hand(info) == m.V[16][2][0]
