# tests/test_hangzhou_mahjong_ai_value.py
import pytest
import hangzhou_mahjong_ai_value as m
from hangzhou_mahjong_ai_value import V, start_value, after_hand


def test_table_shapes():
    assert len(V[16]) == 17
    assert len(V[8]) == 9
    for t in V.values():
        for row in t:
            assert len(row) == 4


def test_zero_row():
    assert V[16][0] == [0.0] * 4
    assert V[8][0] == [0.0] * 4


@pytest.mark.parametrize("total", [8, 16])
def test_start_value_matches_table(total):
    for h in range(1, len(V[total])):
        for d in range(4):
            assert start_value(d, h, total) == V[total][h][d]


@pytest.mark.parametrize("h", [0, -1, -10])
def test_game_over_zero(h):
    assert start_value(0, h, 16) == 0.0
    assert start_value(1, h, 8) == 0.0


def test_dealer_rel_modulo():
    assert start_value(4, 5, 16) == start_value(0, 5, 16)
    assert start_value(7, 5, 16) == V[16][5][3]
    assert start_value(-1, 5, 16) == V[16][5][3]


def test_unknown_total_defaults_to_16():
    assert start_value(1, 3, 12) == V[16][3][1]


def test_hands_left_clamped():
    assert start_value(0, 100, 8) == V[8][8][0]
    assert start_value(2, 50, 16) == V[16][16][2]


def test_float_and_string_like_inputs():
    assert start_value(1.0, 3.0, 16.0) == V[16][3][1]


def test_extra_args_ignored():
    assert start_value(0, 4, 16, scores=[1, 2, 3, 4], seat=2) == V[16][4][0]


def test_after_hand_last():
    info = {"last": True, "dealer": 0, "seat": 1, "rounds": 16, "hand_no": 16}
    assert after_hand(info) == 0.0


def test_after_hand_next():
    info = {"last": False, "dealer": 2, "seat": 1, "rounds": 16, "hand_no": 1}
    # next hand: hands_left = 16, rel = 1
    assert after_hand(info) == V[16][16][1]


def test_after_hand_relative_wrap():
    info = {"last": False, "dealer": 0, "seat": 3, "rounds": 8, "hand_no": 4}
    assert after_hand(info) == V[8][5][1]


def test_after_hand_second_to_last():
    info = {"last": False, "dealer": 1, "seat": 1, "rounds": 8, "hand_no": 7}
    assert after_hand(info) == V[8][2][0]
