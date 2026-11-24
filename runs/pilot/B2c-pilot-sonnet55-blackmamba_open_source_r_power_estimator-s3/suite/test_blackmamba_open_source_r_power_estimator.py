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
    assert e2.walk_k == pytest.approx(50.0)


def test_power_for_non_walking_modes(est):
    # mechanical + compute(0.5)=30 + sensors 8
    assert est.power_for("standing") == 138.0
    assert est.power_for("manipulating") == 238.0
    assert est.power_for("gesture") == 188.0


def test_power_for_ai_load(est):
    assert est.power_for("standing", ai_load=1.0) == 158.0
    assert est.power_for("standing", ai_load=0.0) == 118.0


def test_low_power_halves_sensors_and_idles_compute(est):
    assert est.power_for("low_power", ai_load=1.0) == 20.0 + 10.0 + 4.0


def test_walking_default_speed_matches_table(est):
    assert est.power_for("walking") == 300.0 + 30.0 + 8.0


def test_walking_speed_dependence(est):
    assert est.power_for("walking", speed=0.0) == 100.0 + 38.0
    assert est.power_for("walking", speed=2.0) == 100.0 + 800.0 + 38.0


def test_speed_ignored_for_other_modes(est):
    assert est.power_for("standing", speed=3.0) == est.power_for("standing")


def test_unknown_mode(est):
    with pytest.raises(ValueError):
        est.power_for("flying")


def test_all_modes_work(est):
    for m in MODES:
        assert est.power_for(m) > 0


def test_energy_wh(est):
    assert est.energy_wh("standing", 3600) == pytest.approx(138.0)
    assert est.energy_wh("standing", 1800) == pytest.approx(69.0)
    assert est.energy_wh("standing", 0) == 0.0


def test_walk_energy(est):
    # v=2: power 938, time 5s for 10 m
    assert est.walk_energy_wh(10, 2.0) == pytest.approx(938 * 5 / 3600)


def test_walk_energy_invalid_speed(est):
    with pytest.raises(ValueError):
        est.walk_energy_wh(10, 0)
    with pytest.raises(ValueError):
        est.walk_energy_wh(10, -1)


def test_most_efficient_speed(est):
    expected = math.sqrt((100 + 30 + 8) / 200)
    assert est.most_efficient_speed(5.0) == pytest.approx(expected)


def test_most_efficient_speed_clamped(est):
    assert est.most_efficient_speed(0.5) == 0.5
    assert est.most_efficient_speed(5.0, min_speed=0.9) == 0.9


def test_most_efficient_speed_is_minimum(est):
    v = est.most_efficient_speed(10.0, min_speed=0.01)
    e = lambda s: est.walk_energy_wh(1.0, s)
    assert e(v) <= e(v * 0.8)
    assert e(v) <= e(v * 1.2)


def test_efficient_speed_depends_on_load(est):
    assert est.most_efficient_speed(10, ai_load=1.0) > est.most_efficient_speed(10, ai_load=0.0)
