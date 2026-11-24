# tests/test_ai_video_generator_text.py
import pytest

import ai_video_generator_text as m


# ---------- split_sentences ----------
def test_split_empty():
    assert m.split_sentences("") == []
    assert m.split_sentences("   \n\t ") == []


def test_split_basic():
    assert m.split_sentences("Hello world. How are you? Fine!") == [
        "Hello world.", "How are you?", "Fine!"]


def test_split_whitespace_normalised():
    assert m.split_sentences("A  b.\n\nC d.") == ["A b.", "C d."]


def test_split_no_terminal():
    assert m.split_sentences("No end here") == ["No end here"]


def test_split_abbreviation():
    assert m.split_sentences("Dr. Smith went home. He slept.") == [
        "Dr. Smith went home.", "He slept."]


def test_split_number_followed_by_lowercase():
    assert m.split_sentences("He bought 3. apples today.") == ["He bought 3. apples today."]


def test_split_number_followed_by_uppercase():
    assert m.split_sentences("He bought 3. Apples fell.") == ["He bought 3.", "Apples fell."]


def test_split_closing_quote():
    assert m.split_sentences('He said "stop." Then left.') == ['He said "stop."', "Then left."]


def test_split_ellipsis():
    assert m.split_sentences("Wait… what? Yes.") == ["Wait…", "what?", "Yes."]


def test_split_preserves_words():
    t = "One two. Three four! Five?"
    assert " ".join(m.split_sentences(t)) == t


# ---------- _split_long ----------
def test_split_long_short_unchanged():
    assert m._split_long("a b c", 5) == ["a b c"]


def test_split_long_respects_max_and_words():
    s = " ".join(f"w{i}" for i in range(50))
    out = m._split_long(s, 10)
    assert all(len(p.split()) <= 10 for p in out)
    assert " ".join(out) == s


def test_split_long_prefers_clause_boundary():
    words = [f"w{i}" for i in range(12)]
    words[5] += ","
    s = " ".join(words)
    assert m._split_long(s, 8) == [" ".join(words[:6]), " ".join(words[6:])]


def test_split_long_picks_closest_of_two_commas():
    words = [f"w{i}" for i in range(12)]
    words[5] += ","
    words[8] += ","
    s = " ".join(words)
    assert m._split_long(s, 8) == [" ".join(words[:6]), " ".join(words[6:])]
    words = [f"w{i}" for i in range(12)]
    words[4] += ","
    words[5] += ","
    out = m._split_long(" ".join(words), 8)
    assert out[0].endswith("w5,")


# ---------- segment_script ----------
def test_segment_empty():
    assert m.segment_script("") == []
    assert m.segment_script(" \n\n ") == []


def test_segment_preserves_words():
    text = ("This is the first sentence of the script. Here comes another one, a bit longer than before. "
            "Short one. And a final sentence that closes this paragraph nicely.\n\n"
            "New paragraph begins here with several words in it. Done.")
    beats = m.segment_script(text)
    assert " ".join(" ".join(beats).split()) == " ".join(text.split())


def test_segment_max_words():
    text = " ".join(f"word{i}" for i in range(100)) + "."
    beats = m.segment_script(text, min_words=5, max_words=20)
    assert all(len(b.split()) <= 20 for b in beats)
    assert len(beats) > 1


def test_segment_paragraphs_not_merged():
    beats = m.segment_script("Alpha beta gamma delta epsilon zeta eta.\n\nTheta iota kappa lambda mu nu xi.")
    assert len(beats) == 2


def test_segment_tiny_tail_merged():
    beats = m.segment_script("One two three four five six seven eight. Nine.")
    assert beats == ["One two three four five six seven eight. Nine."]


def test_segment_tiny_paragraph_merged_into_previous():
    beats = m.segment_script("One two three four five six seven eight.\n\nNine.")
    assert beats == ["One two three four five six seven eight. Nine."]


def test_segment_splits_when_both_long():
    beats = m.segment_script("One two three four five six seven. Eight nine ten eleven twelve thirteen fourteen.")
    assert len(beats) == 2


# ---------- norm_token / WER ----------
def test_norm_token():
    assert m.norm_token("Hello,") == "hello"
    assert m.norm_token("...") == ""
    assert m.norm_token("Ünï") == "ünï"
    assert m.norm_token("ＡＢ") == "ab"


def test_wer_identical_and_empty_ref():
    assert m.word_error_rate("a b c", "A, b. c!") == 0.0
    assert m.word_error_rate("", "anything") == 0.0
    assert m.word_error_rate("...", "x") == 0.0


def test_wer_values():
    assert m.word_error_rate("a b c d", "a x c d") == pytest.approx(0.25)
    assert m.word_error_rate("a b", "") == 1.0
    assert m.word_error_rate("a b", "c d") == 1.0
    assert m.word_error_rate("a b", "a b c d") == pytest.approx(0.5)


# ---------- align_words ----------
def H(word, s, e):
    return {"word": word, "start": s, "end": e}


def test_align_exact():
    out = m.align_words("Hello, world.", [H("hello", 0, 0.5), H("world", 0.6, 1.0)], 2.0)
    assert out == [{"word": "Hello,", "start": 0.0, "end": 0.5},
                   {"word": "world.", "start": 0.6, "end": 1.0}]


def test_align_interpolates_middle():
    heard = [H("a", 0, 1), H("c", 3, 4)]
    out = m.align_words("a bb c", heard, 5)
    assert out[1]["word"] == "bb"
    assert out[1]["start"] == 1.0 and out[1]["end"] == 3.0


def test_align_weighted_interpolation():
    heard = [H("a", 0, 1), H("d", 4, 5)]
    out = m.align_words("a b ccc d", heard, 5)
    assert out[1]["start"] == 1.0 and out[1]["end"] == 1.75
    assert out[2]["end"] == 4.0


def test_align_no_heard_uses_duration():
    out = m.align_words("ab cd", [], 4.0)
    assert out[0]["start"] == 0.0 and out[0]["end"] == 2.0
    assert out[1]["end"] == 4.0


def test_align_trailing_gap_and_clamp():
    out = m.align_words("a b", [H("a", 0, 1)], 3.0)
    assert out[1]["start"] == 1.0 and out[1]["end"] == 3.0
    out = m.align_words("a", [H("a", 0, 10)], 2.0)
    assert out[0]["end"] == 2.0


def test_align_empty_script():
    assert m.align_words("", [H("a", 0, 1)], 1.0) == []


def test_align_monotonic_starts():
    out = m.align_words("a b c d e", [H("a", 0, 1), H("c", 0.5, 0.8), H("e", 2, 3)], 4)
    starts = [w["start"] for w in out]
    assert starts == sorted(starts)
    assert all(w["end"] >= w["start"] for w in out)


# ---------- caption_chunks ----------
def W(word, s, e):
    return {"word": word, "start": s, "end": e}


def test_caption_empty():
    assert m.caption_chunks([]) == []


def test_caption_sentence_break():
    ws = [W("Hi", 0, .2), W("there.", .2, .5), W("Bye", .5, .7)]
    ch = m.caption_chunks(ws)
    assert [c["text"] for c in ch] == ["Hi there.", "Bye"]
    assert ch[0]["start"] == 0 and ch[0]["end"] == .5


def test_caption_gap_break():
    ws = [W("a", 0, .2), W("b", 2, 2.2)]
    assert [c["text"] for c in m.caption_chunks(ws)] == ["a", "b"]


def test_caption_quote_end():
    ws = [W('stop."', 0, .2), W("go", .2, .4)]
    assert len(m.caption_chunks(ws)) == 2


def test_caption_line_length_and_words_kept():
    words = "the quick brown fox jumps over the lazy dog while singing a very long song today".split()
    ws = [W(w, i * .3, i * .3 + .2) for i, w in enumerate(words)]
    ch = m.caption_chunks(ws, max_chars=25)
    assert len(ch) > 1
    assert all(len(c["text"]) <= 25 for c in ch)
    assert " ".join(c["text"] for c in ch).split() == words


def test_caption_prefers_comma_break():
    words = ["alpha", "beta", "gamma,", "delta", "epsilon", "zeta"]
    ws = [W(w, i * .3, i * .3 + .2) for i, w in enumerate(words)]
    ch = m.caption_chunks(ws, max_chars=20)
    assert ch[0]["text"] == "alpha beta gamma,"


def test_caption_no_break_after_function_word():
    words = ["alpha", "beta", "the", "gamma", "delta", "epsilon"]
    ws = [W(w, i * .3, i * .3 + .2) for i, w in enumerate(words)]
    ch = m.caption_chunks(ws, max_chars=22)
    assert not any(c["text"].endswith(" the") for c in ch)


def test_split_balanced_single_long_word():
    seg = [W("x" * 60, 0, 1)]
    assert m._split_balanced(seg, 10) == [seg]
