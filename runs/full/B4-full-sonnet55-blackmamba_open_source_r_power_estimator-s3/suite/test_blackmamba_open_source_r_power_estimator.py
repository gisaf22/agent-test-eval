# tests/test_blackmamba_open_source_r_power_estimator.py
import math
import pytest

from blackmamba_open_source_r_power_estimator import PowerEstimator, MODES


TABLE = {
    "standing": 100.0,
    "walking": 300.0,
    "manipulating": 200.0,
    "gesture": 150.0,
    "low_power": 20.0,
    "compute_idle": 10.0,
    "compute_active": 50.0,
    "sensors": 8.0,
}


@pytest.fixture
def est():
    return PowerEstimator(TABLE, 1.0)


def test_init_converts_to_float():
    e = PowerEstimator({"standing": 1, "walking": 2}, 1.0)
    assert all(isinstance(v, float) for v in e.table.values())


def test_from_config():
    cfg = {"power_w": TABLE, "motion": {"nominal_walk_speed_m_s": "2"}}
    e = PowerEstimator.from_config(cfg)
    assert e.nominal_walk_speed == 2.0
    assert e.table["walking"] == 300.0


def test_compute_power_interpolates(est):
    assert est.compute_power_w(0.0) == 10.0
    assert est.compute_power_w(1.0) == 50.0
    assert est.compute_power_w(0.5) == 30.0


def test_compute_power_clamps(est):
    assert est.compute_power_w(-5) == 10.0
    assert est.compute_power_w(7) == 50.0


def test_walk_k(est):
    assert est.walk_k == 200.0
    e2 = PowerEstimator(TABLE, 2.0)
    assert e2.walk_k == pytest.approx(50.0)


def test_unknown_mode(est):
    with pytest.raises(ValueError):
        est.power_for("flying")


def test_standing_power(est):
    assert est.power_for("standing", ai_load=0.5) == 100 + 30 + 8


@pytest.mark.parametrize("mode", ["standing", "manipulating", "gesture"])
def test_static_modes(est, mode):
    assert est.power_for(mode, 1.0) == TABLE[mode] + 50 + 8


def test_low_power_ignores_load_and_halves_sensors(est):
    assert est.power_for("low_power", 1.0) == 20 + 10 + 4
    assert est.power_for("low_power", 0.0) == est.power_for("low_power", 1.0)


def test_walking_default_speed_equals_table(est):
    assert est.power_for("walking") == 300 + 30 + 8


def test_walking_speed_dependence(est):
    assert est.power_for("walking", 0.5, 2.0) == 100 + 200 * 4 + 30 + 8
    assert est.power_for("walking", 0.5, 0.0) == 100 + 30 + 8


def test_speed_ignored_for_other_modes(est):
    assert est.power_for("standing", 0.5, 5.0) == est.power_for("standing", 0.5)


def test_energy_wh(est):
    p = est.power_for("standing")
    assert est.energy_wh("standing", 3600) == pytest.approx(p)
    assert est.energy_wh("standing", 0) == 0


def test_walk_energy(est):
    e = est.walk_energy_wh(10.0, 2.0)
    assert e == pytest.approx(est.power_for("walking", 0.5, 2.0) * 5 / 3600)


@pytest.mark.parametrize("s", [0, -1])
def test_walk_energy_bad_speed(est, s):
    with pytest.raises(ValueError):
        est.walk_energy_wh(5, s)


def test_most_efficient_speed(est):
    expected = math.sqrt((100 + 30 + 8) / 200)
    assert est.most_efficient_speed(5.0) == pytest.approx(expected)


def test_most_efficient_speed_is_minimum(est):
    v = est.most_efficient_speed(5.0)
    e = est.walk_energy_wh(100, v)
    assert e <= est.walk_energy_wh(100, v * 1.2)
    assert e <= est.walk_energy_wh(100, v * 0.8)


def test_most_efficient_speed_clamped(est):
    assert est.most_efficient_speed(0.5, min_speed=0.1) == 0.5
    assert est.most_efficient_speed(5.0, min_speed=0.9) == 0.9


def test_modes_constant():
    assert set(MODES) == {"standing", "walking", "manipulating", "gesture", "low_power"}
