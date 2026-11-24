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
    e = PowerEstimator({"standing": 1, "walking": 2})
    assert isinstance(e.table["standing"], float)
    assert e.nominal_walk_speed == 1.0


def test_from_config():
    cfg = {"power_w": TABLE, "motion": {"nominal_walk_speed_m_s": 2}}
    e = PowerEstimator.from_config(cfg)
    assert e.nominal_walk_speed == 2.0
    assert e.table["walking"] == 300.0


def test_compute_power_interpolates(est):
    assert est.compute_power_w(0.0) == 10.0
    assert est.compute_power_w(1.0) == 50.0
    assert est.compute_power_w(0.5) == 30.0


def test_compute_power_clamps(est):
    assert est.compute_power_w(-5) == 10.0
    assert est.compute_power_w(5) == 50.0


def test_walk_k(est):
    assert est.walk_k == 200.0
    e2 = PowerEstimator(TABLE, 2.0)
    assert e2.walk_k == 50.0


def test_power_for_standing(est):
    assert est.power_for("standing") == 100 + 30 + 8


@pytest.mark.parametrize("mode,mech", [("manipulating", 200), ("gesture", 150)])
def test_power_other_modes(est, mode, mech):
    assert est.power_for(mode, ai_load=1.0) == mech + 50 + 8


def test_low_power_ignores_load_and_halves_sensors(est):
    assert est.power_for("low_power", ai_load=1.0) == 20 + 10 + 4


def test_walking_nominal(est):
    assert est.power_for("walking") == 300 + 30 + 8


def test_walking_speed_quadratic(est):
    assert est.power_for("walking", speed=2.0) == 100 + 200 * 4 + 30 + 8
    assert est.power_for("walking", speed=0.0) == 100 + 30 + 8


def test_speed_ignored_for_non_walking(est):
    assert est.power_for("standing", speed=5.0) == est.power_for("standing")


def test_unknown_mode(est):
    with pytest.raises(ValueError):
        est.power_for("flying")


def test_all_modes_work(est):
    for m in MODES:
        assert est.power_for(m) > 0


def test_energy_wh(est):
    assert est.energy_wh("standing", 3600) == pytest.approx(138.0)
    assert est.energy_wh("standing", 0) == 0
    assert est.energy_wh("standing", 1800) == pytest.approx(69.0)


def test_walk_energy(est):
    p = est.power_for("walking", speed=2.0)
    assert est.walk_energy_wh(10, 2.0) == pytest.approx(p * 5 / 3600)


def test_walk_energy_invalid_speed(est):
    with pytest.raises(ValueError):
        est.walk_energy_wh(10, 0)
    with pytest.raises(ValueError):
        est.walk_energy_wh(10, -1)


def test_most_efficient_speed(est):
    expected = math.sqrt((100 + 30 + 8) / 200)
    assert est.most_efficient_speed(5.0) == pytest.approx(expected)


def test_efficient_speed_is_minimum(est):
    v = est.most_efficient_speed(5.0)
    e = est.walk_energy_wh(1, v)
    assert e <= est.walk_energy_wh(1, v * 1.2)
    assert e <= est.walk_energy_wh(1, v * 0.8)


def test_efficient_speed_clamped(est):
    assert est.most_efficient_speed(0.5) == 0.5
    assert est.most_efficient_speed(5.0, min_speed=0.9) == 0.9
