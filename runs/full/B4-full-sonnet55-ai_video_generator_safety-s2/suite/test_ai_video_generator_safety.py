# tests/test_ai_video_generator_safety.py
import pytest

import ai_video_generator_safety as m


def person(generated=False, **kw):
    d = {"kind": "person", "generated": generated}
    d.update(kw)
    return d


# ---------- real_person_refs ----------

def test_refs_empty_board():
    assert m.real_person_refs({}) == []


def test_refs_none_references():
    assert m.real_person_refs({"references": None}) == []


def test_refs_filters_kind_and_generated():
    real = person()
    missing_flag = {"kind": "person"}
    refs = [real, person(generated=True), {"kind": "place"}, missing_flag, {}]
    out = m.real_person_refs({"references": refs})
    assert out == [real, missing_flag]


# ---------- texts ----------

def test_texts_empty():
    assert m.texts({}) == ["", ""]


def test_texts_collects_all_fields_in_order():
    board = {
        "title": "T",
        "style": "S",
        "shots": [{"narration": "n1", "visual": "v1"}, {"narration": None}],
        "cast": [{"look": "l1"}, {}],
    }
    assert m.texts(board, ["x"]) == ["x", "T", "S", "n1", "v1", "", "", "l1", ""]


def test_texts_none_values():
    board = {"title": None, "style": None, "shots": None, "cast": None}
    assert m.texts(board) == ["", ""]


def test_texts_does_not_mutate_extra():
    extra = ["a"]
    m.texts({"title": "t"}, extra)
    assert extra == ["a"]


# ---------- find_sexual ----------

@pytest.mark.parametrize("word", [
    "sex", "sexual", "porn", "pornography", "nackt", "nackte", "nude", "naked",
    "nudity", "blowjob", "orgasm", "erotisch", "erotic", "ficken", "masturbation",
    "penis", "vagina", "brüste", "boobs", "tits", "striptease", "strip-tease",
    "undressing", "entkleiden", "lingerie", "dessous", "bdsm", "sperma",
    "cumshot", "oben-ohne", "obenohne", "topless", "intimszene", "geschlechtsverkehr",
    "intercourse", "handjob", "erotik", "bumsen",
])
def test_detects_words(word):
    assert m.find_sexual([f"a scene with {word} here"]) is not None


def test_case_insensitive_returns_matched_text():
    assert m.find_sexual(["Very NUDE scene"]) == "NUDE"


def test_returns_first_matching_string():
    assert m.find_sexual(["clean", "porn", "sex"]) == "porn"


def test_no_match():
    assert m.find_sexual(["a cat on a sofa", "", "Essex"]) is None


def test_word_boundary_prefix_not_matched():
    assert m.find_sexual(["Essex", "unsexy"]) is None


def test_suffix_boundary():
    assert m.find_sexual(["titsy"]) is None
    assert m.find_sexual(["boobsy"]) is None


def test_punctuation_adjacent():
    assert m.find_sexual(["(nude)"]) == "nude"


def test_none_and_empty():
    assert m.find_sexual([None, ""]) is None
    assert m.find_sexual([]) is None


# ---------- check ----------

def bad_board(**kw):
    b = {"references": [person()], "shots": [{"narration": "a nude scene"}]}
    b.update(kw)
    return b


def test_check_raises_with_real_photo():
    with pytest.raises(SystemExit) as e:
        m.check(bad_board())
    msg = str(e.value)
    assert msg.startswith(m.MESSAGE)
    assert "(found: 'nude')" in msg


def test_check_no_photos_ok():
    m.check({"shots": [{"narration": "nude"}]})


def test_check_generated_person_ok():
    m.check(bad_board(references=[person(generated=True)]))


def test_check_clean_content_ok():
    m.check({"references": [person()], "title": "Hiking", "shots": [{"visual": "mountain"}]})


def test_check_has_photos_true_overrides():
    with pytest.raises(SystemExit):
        m.check({"title": "porn"}, has_photos=True)


def test_check_has_photos_false_overrides():
    m.check(bad_board(), has_photos=False)


def test_check_extra_texts():
    board = {"references": [person()]}
    with pytest.raises(SystemExit) as e:
        m.check(board, extra=["make it erotic"])
    assert "erotic" in str(e.value)


@pytest.mark.parametrize("board", [
    {"title": "sex"},
    {"style": "topless"},
    {"shots": [{"visual": "naked"}]},
    {"shots": [{"narration": "porn"}]},
    {"cast": [{"look": "lingerie"}]},
])
def test_check_each_field(board):
    board = dict(board, references=[person()])
    with pytest.raises(SystemExit):
        m.check(board)
