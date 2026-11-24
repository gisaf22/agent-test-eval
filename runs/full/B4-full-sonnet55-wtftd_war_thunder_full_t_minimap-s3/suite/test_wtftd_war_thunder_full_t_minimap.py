# tests/test_wtftd_war_thunder_full_t_minimap.py
import math
import pytest
import wtftd_war_thunder_full_t_minimap as m


def cfg(**kw):
    c = {"mapZoom": 1, "mapSize": 200, "mapX": 10, "mapY": 20, "mapUp": "north",
         "mapShape": "square", "mapMarkMe": 100, "mapMarkAllies": 100,
         "mapMarkAirfields": 100, "mapMarkZones": 100, "mapTrail": False,
         "mapDim": 0.5}
    c.update(kw)
    return c


INFO = {"map_min": [0, 0], "map_max": [10000, 10000]}


# ---- keep ----
def test_keep_non_list():
    assert m.keep(None) == {"me": None, "fixed": [], "allies": []}
    assert m.keep({"a": 1})["me"] is None


def test_keep_skips_non_dict_items():
    r = m.keep([1, "x", None, {"icon": "Player", "x": .5, "y": .5}])
    assert r["me"]["x"] == 0.5


def test_keep_player_heading():
    r = m.keep([{"icon": "Player", "x": 0.5, "y": 0.5, "dx": 1, "dy": 0}])
    assert r["me"]["x"] == 0.5
    assert r["me"]["heading"] == pytest.approx(90)


def test_keep_player_default_heading_north():
    r = m.keep([{"icon": "Player", "x": 0.5, "y": 0.5}])
    assert r["me"]["heading"] == pytest.approx(0)


def test_keep_player_invalid_pos():
    assert m.keep([{"icon": "Player", "x": float("nan"), "y": 1}])["me"] is None
    assert m.keep([{"icon": "Player", "x": True, "y": 1}])["me"] is None


def test_keep_fixed_and_color_default():
    r = m.keep([{"type": "capture_zone", "x": 0.1, "y": 0.2, "color": "bad"},
                {"type": "airfield", "sx": 0.1, "sy": 0.1, "ex": 0.2, "ey": 0.2,
                 "color": "#174DFF"}])
    assert r["fixed"][0]["color"] == m.MAP_LINE
    assert r["fixed"][0]["x"] == 0.1
    assert "sx" not in r["fixed"][0]
    assert r["fixed"][1]["color"] == "#174DFF"


def test_keep_allies_only_when_asked():
    objs = [{"type": "aircraft", "x": 0.1, "y": 0.1, "color": "#174DFF"},
            {"type": "ground_model", "x": 0.2, "y": 0.2, "color": "#174DFF"}]
    assert m.keep(objs)["allies"] == []
    a = m.keep(objs, allies=True)["allies"]
    assert len(a) == 1 and a[0]["air"] is True
    g = m.keep(objs, ground=True)["allies"]
    assert len(g) == 1 and g[0]["air"] is False
    assert len(m.keep(objs, True, True)["allies"]) == 2


@pytest.mark.parametrize("color,ok", [
    ("#174DFF", True), ("#00FF00", True), ("#FA0C00", False),
    ("#FAFAFA", False), ("#808080", False), ("#FFA500", False),
    ("#FFFF00", False)])
def test_keep_enemy_colors(color, ok):
    r = m.keep([{"type": "aircraft", "x": .1, "y": .1, "color": color}], allies=True)
    assert bool(r["allies"]) is ok


def test_keep_missing_bad_color_dropped():
    r = m.keep([{"type": "aircraft", "x": .1, "y": .1}], allies=True)
    assert r["allies"] == []
    r = m.keep([{"type": "aircraft", "x": .1, "y": .1, "color": "blue"}], allies=True)
    assert r["allies"] == []


# ---- view ----
def test_view():
    assert m.view(None, 4) == (0.0, 0.0, 1.0)
    assert m.view({"x": .5, "y": .5}, 1) == (0.0, 0.0, 1.0)
    assert m.view({"x": .5, "y": .5}, 2) == (0.25, 0.25, 0.5)
    assert m.view({"x": 0.0, "y": 1.0}, 2) == (0.0, 0.5, 0.5)


# ---- bearing / home ----
def test_bearing():
    km, h = m.bearing({"x": 0, "y": 0.5}, {"x": 0.5, "y": 0.5}, (10000, 10000))
    assert km == pytest.approx(5) and h == pytest.approx(90)
    km, h = m.bearing({"x": .5, "y": .5}, {"x": .5, "y": 0}, (10000, 20000))
    assert km == pytest.approx(10) and h == pytest.approx(0)
    _, h = m.bearing({"x": .5, "y": .5}, {"x": .5, "y": 1}, (1000, 1000))
    assert h == pytest.approx(180)


def test_home_nearest_non_red():
    fixed = [{"type": "airfield", "color": "#FA0C00", "sx": .5, "sy": .5, "ex": .5, "ey": .5},
             {"type": "airfield", "color": "#174DFF", "sx": .9, "sy": .5, "ex": .9, "ey": .5},
             {"type": "airfield", "color": "#174DFF", "sx": .6, "sy": .5, "ex": .6, "ey": .5}]
    km, h = m.home({"x": .5, "y": .5}, fixed, (10000, 10000))
    assert km == pytest.approx(1) and h == pytest.approx(90)


def test_home_none():
    assert m.home({"x": 0, "y": 0}, [], (1, 1)) is None
    red = [{"type": "airfield", "color": "#FA0C00", "sx": 0, "sy": 0, "ex": 1, "ey": 1}]
    assert m.home({"x": 0, "y": 0}, red, (1, 1)) is None


# ---- draw ----
def test_draw_basic_no_me():
    d = m.draw({"me": None, "fixed": [], "allies": []}, INFO, [], cfg())
    assert d["box"] == [10, 20, 200]
    assert d["round"] is False
    assert d["marks"] == []
    assert d["dim"] == 0.5
    assert d["picture"] == {"cx": 0.5, "cy": 0.5, "k": 200.0, "turn": 0.0}
    assert d["frame"][0][0] == "p"


def test_draw_round_frame():
    d = m.draw({}, INFO, [], cfg(mapShape="round"))
    assert d["round"] is True
    assert d["frame"][0] == ["c", 110, 120, 100, m.MAP_LINE]


def test_draw_me_arrow_center():
    seen = {"me": {"x": .5, "y": .5, "heading": 0.0}, "fixed": [], "allies": []}
    d = m.draw(seen, INFO, [], cfg())
    assert len(d["marks"]) == 1
    mk = d["marks"][0]
    assert mk[0] == "p" and mk[2] == 1 and mk[3] == m.ME
    assert mk[1][0] == pytest.approx(110) and mk[1][1] < 120


def test_draw_me_outside_not_drawn():
    seen = {"me": {"x": 1.5, "y": .5, "heading": 0.0}}
    assert m.draw(seen, INFO, [], cfg())["marks"] == []


def test_draw_heading_up():
    seen = {"me": {"x": .5, "y": .5, "heading": 90.0}, "fixed": [], "allies": []}
    d = m.draw(seen, INFO, [], cfg(mapUp="heading", mapZoom=2))
    assert d["picture"]["turn"] == 90.0
    assert d["picture"]["k"] == 400
    n = [f for f in d["frame"] if f[0] == "t"][0]
    assert n[3] == "N"
    assert n[1] == pytest.approx(110 - 88) and n[2] == pytest.approx(120, abs=0.1)


def test_draw_heading_without_me_is_north():
    d = m.draw({"me": None}, INFO, [], cfg(mapUp="heading"))
    assert d["picture"]["turn"] == 0.0
    assert all(f[0] != "t" for f in d["frame"])


def test_draw_zone_and_outside_clipped():
    seen = {"me": None, "allies": [], "fixed": [
        {"type": "capture_zone", "color": "#FAFAFA", "x": .5, "y": .5},
        {"type": "capture_zone", "color": "#FAFAFA", "x": 1.5, "y": .5}]}
    d = m.draw(seen, INFO, [], cfg())
    assert len(d["marks"]) == 1
    assert d["marks"][0] == ["c", 110.0, 120.0, 5, "#FAFAFA"]


def test_draw_fixed_without_coords_ignored():
    seen = {"fixed": [{"type": "capture_zone", "color": "#FAFAFA"},
                      {"type": "airfield", "color": "#FAFAFA", "sx": .1, "sy": .1}]}
    assert m.draw(seen, INFO, [], cfg())["marks"] == []


def test_draw_airfield_outside_dropped():
    seen = {"fixed": [{"type": "airfield", "color": "#174DFF",
                       "sx": 1.5, "sy": .5, "ex": 1.6, "ey": .5}]}
    assert m.draw(seen, INFO, [], cfg())["marks"] == []


def test_draw_ally_outside_dropped():
    seen = {"allies": [{"x": 2, "y": .5, "heading": 0, "color": "#174DFF", "air": True}]}
    assert m.draw(seen, INFO, [], cfg())["marks"] == []


def test_draw_round_clips_corner():
    seen = {"me": None, "allies": [], "fixed": [
        {"type": "capture_zone", "color": "#FAFAFA", "x": .02, "y": .02}]}
    assert m.draw(seen, INFO, [], cfg())["marks"]
    assert not m.draw(seen, INFO, [], cfg(mapShape="round"))["marks"]


def test_draw_base_square():
    seen = {"fixed": [{"type": "bombing_point", "color": "#FAFAFA", "x": .5, "y": .5}]}
    mk = m.draw(seen, INFO, [], cfg())["marks"][0]
    assert mk[0] == "p" and mk[2] == 0 and mk[1][0] == 105.0


def test_draw_airfield_min_length():
    seen = {"fixed": [{"type": "airfield", "color": "#174DFF",
                       "sx": .5, "sy": .5, "ex": .5, "ey": .5}]}
    mk = m.draw(seen, INFO, [], cfg())["marks"][0]
    assert mk[0] == "l"
    assert mk[3] - mk[1] == pytest.approx(20, abs=0.2)
    assert mk[5] == 6 and mk[6] == "#174DFF"


def test_draw_allies_shapes():
    seen = {"allies": [
        {"x": .3, "y": .3, "heading": 0, "color": "#174DFF", "air": True},
        {"x": .6, "y": .6, "heading": 0, "color": "#174DFF", "air": False}]}
    ms = m.draw(seen, INFO, [], cfg())["marks"]
    assert len(ms[0][1]) == 6 and len(ms[1][1]) == 8


def test_draw_trail():
    seen = {"me": {"x": .5, "y": .5, "heading": 0.0}}
    t = [(.1, .1), (.2, .2)]
    off = m.draw(seen, INFO, t, cfg())["marks"]
    on = m.draw(seen, INFO, t, cfg(mapTrail=True))["marks"]
    lines = [x for x in on if x[0] == "l"]
    assert len(lines) == 2 and len(off) == 1
    assert lines[0][5] == 1.5 and lines[0][6] == m.ME


def test_draw_trail_outside_segments_dropped():
    seen = {"me": {"x": .5, "y": .5, "heading": 0.0}}
    t = [(3, 3), (4, 4)]
    on = m.draw(seen, INFO, t, cfg(mapTrail=True))["marks"]
    lines = [x for x in on if x[0] == "l"]
    # only the last segment, ending at the aircraft, is visible
    assert len(lines) == 1
    assert lines[0][3:5] == [110.0, 120.0]


def test_draw_airfield_text():
    seen = {"me": {"x": .5, "y": .5, "heading": 0.0},
            "fixed": [{"type": "airfield", "color": "#174DFF",
                       "sx": .6, "sy": .5, "ex": .6, "ey": .5}]}
    d = m.draw(seen, INFO, [], cfg())
    t = [f for f in d["frame"] if f[0] == "t"][0]
    assert t[3] == "AF 1.0 km 090°"
    assert t[1] == 10 and t[2] == 234


def test_draw_bad_info_no_text():
    seen = {"me": {"x": .5, "y": .5, "heading": 0.0},
            "fixed": [{"type": "airfield", "color": "#174DFF",
                       "sx": .6, "sy": .5, "ex": .6, "ey": .5}]}
    for info in ({}, {"map_min": "a", "map_max": [1, 1]}, {"map_min": [0], "map_max": [1]}):
        d = m.draw(seen, info, [], cfg())
        assert all(f[0] != "t" for f in d["frame"])


def test_mark_scale():
    seen = {"me": {"x": .5, "y": .5, "heading": 0.0}}
    a = m.draw(seen, INFO, [], cfg(mapMarkMe=100))["marks"][0][1]
    b = m.draw(seen, INFO, [], cfg(mapMarkMe=200))["marks"][0][1]
    assert abs(b[1] - 120) == pytest.approx(2 * abs(a[1] - 120), abs=0.2)


def test_sample_draws():
    d = m.draw(m.SAMPLE, m.SAMPLE_INFO, m.SAMPLE_TRAIL, cfg(mapTrail=True))
    assert d["marks"]
