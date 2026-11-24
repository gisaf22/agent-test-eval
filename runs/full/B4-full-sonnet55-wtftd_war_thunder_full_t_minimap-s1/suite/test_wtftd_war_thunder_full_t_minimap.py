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


# ---- keep ----
def test_keep_non_list():
    assert m.keep(None) == {"me": None, "fixed": [], "allies": []}
    assert m.keep({"a": 1})["me"] is None


def test_keep_me_heading():
    r = m.keep([{"icon": "Player", "x": 0.5, "y": 0.5, "dx": 1, "dy": 0}])
    assert r["me"]["x"] == 0.5
    assert r["me"]["heading"] == pytest.approx(90)


def test_keep_me_default_heading_north():
    r = m.keep([{"icon": "Player", "x": 0.5, "y": 0.5}])
    assert r["me"]["heading"] == pytest.approx(0)


def test_keep_me_needs_coords():
    assert m.keep([{"icon": "Player", "x": 0.5}])["me"] is None


def test_keep_ignores_bad_numbers():
    assert m.keep([{"icon": "Player", "x": True, "y": 0.5}])["me"] is None
    assert m.keep([{"icon": "Player", "x": float("nan"), "y": 0.5}])["me"] is None
    assert m.keep(["x", 3])["fixed"] == []


def test_keep_fixed():
    r = m.keep([{"type": "capture_zone", "color": "#FAFAFA", "x": 0.1, "y": 0.2},
                {"type": "airfield", "color": "bad", "sx": 0, "sy": 0, "ex": 1, "ey": 1}])
    assert r["fixed"][0] == {"type": "capture_zone", "color": "#FAFAFA", "x": 0.1, "y": 0.2}
    assert r["fixed"][1]["color"] == m.MAP_LINE
    assert "x" not in r["fixed"][1]


def test_keep_allies_filtering():
    objs = [{"type": "aircraft", "x": .1, "y": .1, "color": "#174DFF"},
            {"type": "aircraft", "x": .2, "y": .2, "color": "#FA0C00"},
            {"type": "aircraft", "x": .3, "y": .3, "color": "#00FF00"},
            {"type": "aircraft", "x": .4, "y": .4, "color": "#FAFAFA"},
            {"type": "aircraft", "x": .5, "y": .5},
            {"type": "ground_model", "x": .6, "y": .6, "color": "#174DFF"}]
    assert m.keep(objs)["allies"] == []
    r = m.keep(objs, allies=True)["allies"]
    assert [a["x"] for a in r] == [.1, .3]
    assert all(a["air"] for a in r)
    g = m.keep(objs, ground=True)["allies"]
    assert [a["x"] for a in g] == [.6] and not g[0]["air"]


def test_ally_predicate():
    assert m._ally("#174DFF")
    assert not m._ally("#FA0C00")
    assert not m._ally("#FFA500")
    assert not m._ally("#808080")


def test_enemy_never_kept():
    objs = [{"type": "aircraft", "x": .2, "y": .2, "color": "#FA0C00"}]
    assert m.keep(objs, allies=True, ground=True)["allies"] == []


# ---- view ----
def test_view():
    assert m.view(None, 4) == (0.0, 0.0, 1.0)
    assert m.view({"x": .5, "y": .5}, 1) == (0.0, 0.0, 1.0)
    assert m.view({"x": .5, "y": .5}, 2) == (0.25, 0.25, 0.5)
    assert m.view({"x": 0.0, "y": 1.0}, 4) == (0.0, 0.75, 0.25)


# ---- bearing / home ----
def test_bearing():
    d, h = m.bearing({"x": .5, "y": .5}, {"x": .6, "y": .5}, (10000, 10000))
    assert d == pytest.approx(1) and h == pytest.approx(90)
    d, h = m.bearing({"x": .5, "y": .5}, {"x": .5, "y": .4}, (10000, 10000))
    assert h == pytest.approx(0)
    d, h = m.bearing({"x": .5, "y": .5}, {"x": .5, "y": .6}, (10000, 10000))
    assert h == pytest.approx(180)


def test_home_skips_enemy_and_picks_nearest():
    me = {"x": .5, "y": .5}
    fixed = [{"type": "airfield", "color": "#FA0C00", "sx": .5, "sy": .5, "ex": .52, "ey": .5},
             {"type": "airfield", "color": "#174DFF", "sx": .9, "sy": .5, "ex": .9, "ey": .5},
             {"type": "airfield", "color": "#174DFF", "sx": .6, "sy": .5, "ex": .6, "ey": .5}]
    d, h = m.home(me, fixed, (10000, 10000))
    assert d == pytest.approx(1) and h == pytest.approx(90)
    assert m.home(me, fixed[:1], (10000, 10000)) is None


# ---- draw ----
def test_draw_basic_structure():
    out = m.draw({"me": None, "fixed": [], "allies": []}, INFO, [], cfg())
    assert out["box"] == [10, 20, 200]
    assert out["round"] is False and out["marks"] == []
    assert out["dim"] == 0.5
    assert out["picture"] == {"cx": 0.5, "cy": 0.5, "k": 200.0, "turn": 0.0}
    assert out["frame"][0][0] == "p"


def test_draw_round_frame():
    out = m.draw({"me": None}, INFO, [], cfg(mapShape="round"))
    assert out["frame"][0] == ["c", 110, 120, 100, m.MAP_LINE]


def test_me_arrow_at_center():
    me = {"x": .5, "y": .5, "heading": 0}
    out = m.draw({"me": me}, INFO, [], cfg())
    mk = out["marks"][-1]
    assert mk[0] == "p" and mk[2] == 1 and mk[3] == m.ME
    assert mk[1][0] == pytest.approx(110) and mk[1][1] < 120


def test_heading_up_has_north_label_and_turn():
    me = {"x": .5, "y": .5, "heading": 90}
    out = m.draw({"me": me}, INFO, [], cfg(mapUp="heading"))
    assert out["picture"]["turn"] == 90
    t = out["frame"][-1]
    assert t[0] == "t" and t[3] == "N"


def test_heading_mode_without_me_is_north_up():
    out = m.draw({"me": None}, INFO, [], cfg(mapUp="heading"))
    assert out["picture"]["turn"] == 0.0
    assert all(f[0] != "t" for f in out["frame"])


def test_zone_inside_and_outside():
    seen = {"me": None, "fixed": [
        {"type": "capture_zone", "color": "#FAFAFA", "x": .5, "y": .5},
        {"type": "capture_zone", "color": "#FAFAFA", "x": 1.5, "y": .5}]}
    out = m.draw(seen, INFO, [], cfg())
    assert len(out["marks"]) == 1
    assert out["marks"][0][:3] == ["c", 110.0, 120.0]


def test_fixed_without_coordinates_ignored():
    seen = {"fixed": [{"type": "airfield", "color": "#174DFF", "sx": .5, "sy": .5},
                      {"type": "capture_zone", "color": "#FAFAFA"}]}
    assert m.draw(seen, INFO, [], cfg())["marks"] == []


def test_bombing_point_square():
    seen = {"fixed": [{"type": "bombing_point", "color": "#FAFAFA", "x": .5, "y": .5}]}
    mk = m.draw(seen, INFO, [], cfg())["marks"][0]
    assert mk[0] == "p" and mk[2] == 0


def test_airfield_runway_min_length_and_cull():
    seen = {"fixed": [
        {"type": "airfield", "color": "#174DFF", "sx": .5, "sy": .5, "ex": .5, "ey": .5},
        {"type": "airfield", "color": "#174DFF", "sx": 2, "sy": 2, "ex": 3, "ey": 3}]}
    out = m.draw(seen, INFO, [], cfg())
    assert len(out["marks"]) == 1
    l = out["marks"][0]
    assert l[0] == "l"
    assert math.hypot(l[3] - l[1], l[4] - l[2]) == pytest.approx(20, abs=0.2)


def test_round_clipping():
    seen = {"fixed": [{"type": "capture_zone", "color": "#FAFAFA", "x": .02, "y": .02}]}
    assert m.draw(seen, INFO, [], cfg(mapShape="round"))["marks"] == []
    assert len(m.draw(seen, INFO, [], cfg())["marks"]) == 1


def test_allies_shapes():
    seen = {"allies": [
        {"x": .5, "y": .5, "heading": 0, "color": "#174DFF", "air": True},
        {"x": .4, "y": .4, "heading": 0, "color": "#174DFF", "air": False}]}
    out = m.draw(seen, INFO, [], cfg())["marks"]
    assert len(out[0][1]) == 6 and len(out[1][1]) == 8


def test_ally_outside_skipped():
    seen = {"allies": [{"x": 1.5, "y": .5, "heading": 0, "color": "#174DFF", "air": True}]}
    assert m.draw(seen, INFO, [], cfg())["marks"] == []


def test_me_outside_skipped():
    seen = {"me": {"x": 1.5, "y": .5, "heading": 0}}
    assert m.draw(seen, INFO, [], cfg())["marks"] == []


def test_trail_segments_outside_skipped():
    out = m.draw({"me": None}, INFO, [(1.5, .5), (1.6, .5)], cfg(mapTrail=True))
    assert out["marks"] == []


def test_trail():
    me = {"x": .5, "y": .5, "heading": 0}
    seen = {"me": me}
    off = m.draw(seen, INFO, [(.4, .5)], cfg())["marks"]
    assert all(k[0] != "l" for k in off)
    out = m.draw(seen, INFO, [(.3, .5), (.4, .5)], cfg(mapTrail=True))["marks"]
    lines = [k for k in out if k[0] == "l"]
    assert len(lines) == 2 and lines[0][5] == 1.5


def test_zoom_centres_on_me():
    me = {"x": .5, "y": .5, "heading": 0}
    out = m.draw({"me": me}, INFO, [], cfg(mapZoom=2))
    assert out["picture"]["k"] == 400.0
    assert out["picture"]["cx"] == .5


def test_home_label():
    seen = {"me": {"x": .5, "y": .5, "heading": 0},
            "fixed": [{"type": "airfield", "color": "#174DFF", "sx": .6, "sy": .5, "ex": .6, "ey": .5}]}
    out = m.draw(seen, INFO, [], cfg())
    assert out["frame"][-1][3] == "AF 1.0 km 090°"
    assert out["frame"][-1][:3] == ["t", 10, 234]


def test_no_label_bad_info():
    seen = {"me": {"x": .5, "y": .5, "heading": 0},
            "fixed": [{"type": "airfield", "color": "#174DFF", "sx": .6, "sy": .5, "ex": .6, "ey": .5}]}
    out = m.draw(seen, {}, [], cfg())
    assert all(f[0] != "t" for f in out["frame"])


def test_mark_size_scaling():
    me = {"x": .5, "y": .5, "heading": 0}
    a = m.draw({"me": me}, INFO, [], cfg(mapMarkMe=100))["marks"][0][1]
    b = m.draw({"me": me}, INFO, [], cfg(mapMarkMe=200))["marks"][0][1]
    assert 120 - b[1] == pytest.approx(2 * (120 - a[1]), abs=0.01)


def test_sample_runs():
    seen = {"me": m.SAMPLE["me"], "fixed": m.SAMPLE["fixed"], "allies": m.SAMPLE["allies"]}
    out = m.draw(seen, m.SAMPLE_INFO, m.SAMPLE_TRAIL, cfg(mapTrail=True))
    assert out["marks"]
