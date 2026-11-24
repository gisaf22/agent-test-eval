# tests/test_wtftd_war_thunder_full_t_minimap.py
import math
import pytest
import wtftd_war_thunder_full_t_minimap as m


def cfg(**kw):
    c = {"mapZoom": 1, "mapSize": 200, "mapX": 10, "mapY": 20, "mapUp": "north",
         "mapShape": "square", "mapMarkMe": 100, "mapMarkAllies": 100,
         "mapMarkAirfields": 100, "mapMarkZones": 100, "mapTrail": False, "mapDim": 0.5}
    c.update(kw)
    return c


INFO = {"map_min": [0, 0], "map_max": [10000, 10000]}


def test_num():
    assert m._num(1) == 1.0
    assert m._num(True) is None
    assert m._num("1") is None
    assert m._num(float("nan")) is None
    assert m._num(float("inf")) is None
    assert m._num(None) is None


def test_color_default():
    assert m._color("#12abEF", "d") == "#12abEF"
    assert m._color("#12345", "d") == "d"
    assert m._color(5, "d") == "d"
    assert m._color("#1234567", "d") == "d"


def test_ally():
    assert m._ally("#174DFF")
    assert m._ally("#30C040")
    for c in ("#FA0C00", "#FAFAFA", "#FFA000", "#FFFF00", "#808080"):
        assert not m._ally(c)


def test_heading():
    assert m._heading(0, -1) == 0
    assert m._heading(1, 0) == pytest.approx(90)
    assert m._heading(0, 1) == pytest.approx(180)
    assert m._heading(-1, 0) == pytest.approx(270)
    assert m._heading(None, None) == 0


def objs():
    return [
        {"icon": "Player", "x": 0.5, "y": 0.5, "dx": 1, "dy": 0},
        {"type": "airfield", "color": "#174DFF", "sx": 0.1, "sy": 0.1, "ex": 0.2, "ey": 0.1},
        {"type": "capture_zone", "color": "bad", "x": 0.3, "y": 0.3},
        {"type": "aircraft", "x": 0.2, "y": 0.2, "color": "#174DFF", "dx": 0, "dy": -1},
        {"type": "aircraft", "x": 0.2, "y": 0.2, "color": "#FA0C00"},
        {"type": "ground_model", "x": 0.4, "y": 0.4, "color": "#174DFF"},
        "junk",
    ]


def test_keep_default_no_units():
    r = m.keep(objs())
    assert r["me"]["heading"] == pytest.approx(90)
    assert r["allies"] == []
    assert len(r["fixed"]) == 2
    assert r["fixed"][1]["color"] == m.MAP_LINE


def test_keep_allies_and_ground():
    r = m.keep(objs(), allies=True)
    assert len(r["allies"]) == 1 and r["allies"][0]["air"]
    r = m.keep(objs(), allies=True, ground=True)
    assert len(r["allies"]) == 2
    r = m.keep(objs(), ground=True)
    assert [a["air"] for a in r["allies"]] == [False]


def test_keep_never_enemy():
    o = [{"type": "aircraft", "x": 0, "y": 0, "color": "#FA0C00"},
         {"type": "aircraft", "x": 0, "y": 0}]
    assert m.keep(o, allies=True, ground=True)["allies"] == []


def test_keep_bad_input():
    assert m.keep(None) == {"me": None, "fixed": [], "allies": []}
    assert m.keep([{"icon": "Player", "x": "a", "y": 1}])["me"] is None


def test_view():
    assert m.view(None, 4) == (0.0, 0.0, 1.0)
    assert m.view({"x": .5, "y": .5}, 1) == (0.0, 0.0, 1.0)
    assert m.view({"x": .5, "y": .5}, 2) == (0.25, 0.25, 0.5)
    assert m.view({"x": 0, "y": 1}, 2) == (0.0, 0.5, 0.5)


def test_bearing():
    d, h = m.bearing({"x": .5, "y": .5}, {"x": .6, "y": .5}, (10000, 10000))
    assert d == pytest.approx(1) and h == pytest.approx(90)
    d, h = m.bearing({"x": .5, "y": .5}, {"x": .5, "y": .4}, (10000, 10000))
    assert h == pytest.approx(0)


def test_home_skips_enemy():
    me = {"x": .5, "y": .5}
    fx = [{"type": "airfield", "color": "#FA0C00", "sx": .5, "sy": .5, "ex": .5, "ey": .5},
          {"type": "airfield", "color": "#174DFF", "sx": .6, "sy": .5, "ex": .6, "ey": .5}]
    d, h = m.home(me, fx, (10000, 10000))
    assert d == pytest.approx(1) and h == pytest.approx(90)
    assert m.home(me, fx[:1], (1, 1)) is None


def test_arrow_tip():
    a = m._arrow(10, 10, 0, 5)
    assert a[0] == pytest.approx(10) and a[1] == pytest.approx(5)
    assert len(a) == 6


def test_draw_basic():
    seen = {"me": {"x": .5, "y": .5, "heading": 0}, "fixed": [], "allies": []}
    r = m.draw(seen, INFO, [], cfg())
    assert r["box"] == [10, 20, 200]
    assert r["round"] is False
    assert r["picture"] == {"cx": .5, "cy": .5, "k": 200, "turn": 0.0}
    assert len(r["marks"]) == 1 and r["marks"][0][2] == 1 and r["marks"][0][3] == m.ME
    assert r["frame"][0][0] == "p"


def test_draw_round_and_clip():
    seen = {"me": None, "fixed": [{"type": "capture_zone", "color": "#FAFAFA", "x": 0.0, "y": 0.0}], "allies": []}
    assert m.draw(seen, INFO, [], cfg())["marks"]
    r = m.draw(seen, INFO, [], cfg(mapShape="round"))
    assert r["marks"] == [] and r["frame"][0][0] == "c"


def test_draw_heading_up():
    seen = {"me": {"x": .5, "y": .5, "heading": 90}, "fixed": [], "allies": []}
    r = m.draw(seen, INFO, [], cfg(mapUp="heading", mapZoom=2))
    assert r["picture"]["turn"] == 90
    assert r["picture"]["k"] == 400
    t = [f for f in r["frame"] if f[0] == "t"][0]
    assert t[3] == "N" and t[1] == pytest.approx(110 - 88)
    poly = r["marks"][0][1]
    assert poly[0] == pytest.approx(110, abs=0.2)
    assert poly[1] == pytest.approx(111, abs=0.2)


def test_draw_home_text():
    seen = {"me": {"x": .5, "y": .5, "heading": 0},
            "fixed": [{"type": "airfield", "color": "#174DFF", "sx": .6, "sy": .5, "ex": .6, "ey": .5}],
            "allies": []}
    r = m.draw(seen, INFO, [], cfg())
    assert any(f[0] == "t" and f[3] == "AF 1.0 km 090°" for f in r["frame"])
    assert [mk for mk in r["marks"] if mk[0] == "l"]
    r = m.draw(seen, {}, [], cfg())
    assert not any(f[0] == "t" for f in r["frame"])


def test_draw_trail_and_allies():
    seen = {"me": {"x": .5, "y": .5, "heading": 0}, "fixed": [],
            "allies": [{"x": .3, "y": .3, "heading": 0, "color": "#174DFF", "air": False}]}
    r = m.draw(seen, INFO, [(.4, .5)], cfg(mapTrail=True))
    assert len([x for x in r["marks"] if x[0] == "l"]) == 1
    assert len(r["marks"]) == 3


def test_sample_draws():
    r = m.draw(m.SAMPLE, m.SAMPLE_INFO, m.SAMPLE_TRAIL, cfg(mapTrail=True))
    assert r["marks"]


def test_bombing_point_square():
    seen = {"me": None, "allies": [],
            "fixed": [{"type": "bombing_point", "color": "#FAFAFA", "x": .5, "y": .5}]}
    r = m.draw(seen, INFO, [], cfg())
    assert r["marks"][0][0] == "p" and r["marks"][0][2] == 0


def test_airfield_outside_skipped():
    seen = {"me": {"x": .9, "y": .9, "heading": 0}, "allies": [],
            "fixed": [{"type": "airfield", "color": "#174DFF", "sx": .0, "sy": .0, "ex": .01, "ey": .0}]}
    r = m.draw(seen, INFO, [], cfg(mapZoom=4))
    assert not [x for x in r["marks"] if x[0] == "l"]


def test_allied_aircraft_arrow():
    seen = {"me": None, "fixed": [],
            "allies": [{"x": .5, "y": .5, "heading": 0, "color": "#174DFF", "air": True}]}
    r = m.draw(seen, INFO, [], cfg())
    assert len(r["marks"][0][1]) == 6


def test_bad_extent_no_text():
    seen = {"me": {"x": .5, "y": .5, "heading": 0},
            "fixed": [{"type": "airfield", "color": "#174DFF", "sx": .6, "sy": .5, "ex": .6, "ey": .5}],
            "allies": []}
    r = m.draw(seen, {"map_min": [0], "map_max": "x"}, [], cfg())
    assert not any(f[0] == "t" for f in r["frame"])


def test_zero_length_runway():
    seen = {"me": None, "allies": [],
            "fixed": [{"type": "airfield", "color": "#174DFF", "sx": .5, "sy": .5, "ex": .5, "ey": .5}]}
    r = m.draw(seen, INFO, [], cfg())
    assert r["marks"][0][0] == "l"
