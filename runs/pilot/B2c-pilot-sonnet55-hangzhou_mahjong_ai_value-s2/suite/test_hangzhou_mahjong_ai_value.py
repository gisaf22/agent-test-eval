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


@pytest.mark.parametrize("h", [0, -1, -100])
def test_game_over_is_zero(h):
    assert start_value(0, h, 16) == 0.0
    assert start_value(1, h, 8) == 0.0


def test_dealer_rel_modulo():
    assert start_value(4, 5, 16) == start_value(0, 5, 16)
    assert start_value(-1, 5, 16) == start_value(3, 5, 16)
    assert start_value(6, 3, 8) == V[8][3][2]


def test_hands_left_clamped():
    assert start_value(0, 99, 16) == V[16][16][0]
    assert start_value(2, 50, 8) == V[8][8][2]


def test_unknown_total_defaults_to_16():
    assert start_value(1, 4, 12) == V[16][4][1]
    assert start_value(1, 20, 4) == V[16][16][1]


def test_extra_args_ignored():
    assert start_value(0, 3, 16, scores=[1, 2, 3, 4], seat=2) == V[16][3][0]


def test_float_inputs_and_return_types():
    assert start_value(1.0, 2.0, 8.0) == V[8][2][1]
    assert isinstance(start_value(0, 0, 16), float)


def test_dealer_is_best_with_many_hands():
    for h in range(4, 17):
        assert V[16][h][0] == max(V[16][h])


def test_after_hand_last():
    info = {"last": True, "dealer": 0, "seat": 1, "rounds": 16, "hand_no": 16}
    assert after_hand(info) == 0.0


def test_after_hand_next_hand():
    info = {"last": False, "dealer": 3, "seat": 1, "rounds": 16, "hand_no": 1}
    # rel = 2, hands_left = 16
    assert after_hand(info) == V[16][16][2]


def test_after_hand_wraps_and_8():
    info = {"last": False, "dealer": 0, "seat": 2, "rounds": 8, "hand_no": 7}
    # rel = (0-2)%4 = 2, hands_left = 2
    assert after_hand(info) == V[8][2][2]


def test_after_hand_second_to_last():
    info = {"last": False, "dealer": 1, "seat": 1, "rounds": 16, "hand_no": 15}
    assert after_hand(info) == V[16][2][0]


def test_after_hand_missing_key():
    with pytest.raises(KeyError):
        after_hand({"last": False})
