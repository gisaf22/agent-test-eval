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


def test_init_converts_floats():
    e = PowerEstimator({"standing": 1}, 2)
    assert isinstance(e.table["standing"], float)
    assert e.nominal_walk_speed == 2


def test_from_config():
    cfg = {"power_w": TABLE, "motion": {"nominal_walk_speed_m_s": "1.5"}}
    e = PowerEstimator.from_config(cfg)
    assert e.nominal_walk_speed == 1.5
    assert e.table["walking"] == 300.0


def test_compute_power_interpolates_and_clamps(est):
    assert est.compute_power_w(0.0) == 10.0
    assert est.compute_power_w(1.0) == 50.0
    assert est.compute_power_w(0.5) == 30.0
    assert est.compute_power_w(-3) == 10.0
    assert est.compute_power_w(5) == 50.0


def test_walk_k(est):
    assert est.walk_k == 200.0
    e2 = PowerEstimator(TABLE, 2.0)
    assert e2.walk_k == 50.0


def test_unknown_mode(est):
    with pytest.raises(ValueError):
        est.power_for("flying")


def test_modes_constant():
    assert "walking" in MODES and len(MODES) == 5


@pytest.mark.parametrize("mode,mech", [("standing", 100), ("manipulating", 200), ("gesture", 150)])
def test_static_modes(est, mode, mech):
    assert est.power_for(mode) == mech + 30 + 8
    assert est.power_for(mode, ai_load=1.0) == mech + 50 + 8


def test_low_power(est):
    # ai_load ignored, sensors halved
    assert est.power_for("low_power", ai_load=1.0) == 20 + 10 + 4


def test_walking_default_speed(est):
    assert est.power_for("walking") == 300 + 30 + 8


def test_walking_speed_dependence(est):
    assert est.power_for("walking", speed=2.0) == 100 + 800 + 30 + 8
    assert est.power_for("walking", speed=0.0) == 100 + 30 + 8


def test_speed_ignored_for_non_walking(est):
    assert est.power_for("standing", speed=5.0) == est.power_for("standing")


def test_energy_wh(est):
    assert est.energy_wh("standing", 3600) == pytest.approx(138.0)
    assert est.energy_wh("standing", 0) == 0
    assert est.energy_wh("walking", 1800, speed=1.0) == pytest.approx(338 / 2)


def test_walk_energy(est):
    # 10 m at 2 m/s = 5 s
    p = est.power_for("walking", 0.5, 2.0)
    assert est.walk_energy_wh(10, 2.0) == pytest.approx(p * 5 / 3600)


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


def test_efficient_speed_minimises_energy_per_metre(est):
    v = est.most_efficient_speed(10.0)
    e = lambda s: est.walk_energy_wh(1.0, s)
    assert e(v) <= e(v * 0.8)
    assert e(v) <= e(v * 1.2)


def test_efficient_speed_depends_on_load(est):
    assert est.most_efficient_speed(10, ai_load=1.0) > est.most_efficient_speed(10, ai_load=0.0)
