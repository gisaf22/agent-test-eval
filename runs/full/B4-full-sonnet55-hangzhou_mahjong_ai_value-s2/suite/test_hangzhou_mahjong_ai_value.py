# tests/test_hangzhou_mahjong_ai_value.py
import pytest
from hangzhou_mahjong_ai_value import V, start_value, after_hand


def test_table_shapes():
    assert len(V[16]) == 17
    assert len(V[8]) == 9
    for t in V.values():
        for row in t:
            assert len(row) == 4
        assert t[0] == [0.0] * 4


@pytest.mark.parametrize("total", [16, 8])
def test_lookup_matches_table(total):
    for h in range(1, len(V[total])):
        for d in range(4):
            assert start_value(d, h, total) == V[total][h][d]


@pytest.mark.parametrize("h", [0, -1, -10])
def test_game_over_zero(h):
    assert start_value(0, h, 16) == 0.0
    assert start_value(2, h, 8) == 0.0


def test_dealer_rel_modulo():
    assert start_value(4, 3, 16) == start_value(0, 3, 16)
    assert start_value(-1, 3, 16) == start_value(3, 3, 16)
    assert start_value(6, 2, 8) == V[8][2][2]


def test_unknown_total_falls_back_to_16():
    assert start_value(1, 5, 12) == V[16][5][1]


def test_hands_left_clamped():
    assert start_value(0, 100, 16) == V[16][16][0]
    assert start_value(3, 50, 8) == V[8][8][3]


def test_ignores_scores_seat():
    assert start_value(1, 4, 16, scores=[1, 2, 3, 4], seat=2) == V[16][4][1]


def test_float_and_string_ints():
    assert start_value(1.0, 3.0, 16.0) == V[16][3][1]


def test_after_hand_last():
    info = {"last": True, "dealer": 1, "seat": 0, "rounds": 16, "hand_no": 16}
    assert after_hand(info) == 0.0


def test_after_hand_mid():
    info = {"last": False, "dealer": 1, "seat": 3, "rounds": 16, "hand_no": 4}
    # rel = (1-3)%4 = 2; hands_left = 16-4+1 = 13
    assert after_hand(info) == V[16][13][2]


def test_after_hand_8():
    info = {"last": False, "dealer": 0, "seat": 1, "rounds": 8, "hand_no": 7}
    assert after_hand(info) == V[8][2][3]


def test_after_hand_first_hand():
    info = {"last": False, "dealer": 2, "seat": 2, "rounds": 8, "hand_no": 1}
    assert after_hand(info) == V[8][8][0]
