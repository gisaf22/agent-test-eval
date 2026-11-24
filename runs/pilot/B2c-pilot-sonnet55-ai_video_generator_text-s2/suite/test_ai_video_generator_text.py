# tests/test_ai_video_generator_text.py
import pytest

import ai_video_generator_text as m


# ---------- split_sentences ----------

def test_split_empty_and_whitespace():
    assert m.split_sentences("") == []
    assert m.split_sentences("  \n\t ") == []


def test_split_basic():
    assert m.split_sentences("Hello world. How are you? Fine!") == [
        "Hello world.", "How are you?", "Fine!"]


def test_split_normalizes_whitespace():
    assert m.split_sentences("One   two.\n\nThree  four.") == ["One two.", "Three four."]


def test_split_abbreviation_not_boundary():
    assert m.split_sentences("Dr. Smith went home. He slept.") == [
        "Dr. Smith went home.", "He slept."]


def test_split_no_terminal_punct():
    assert m.split_sentences("just some words") == ["just some words"]


def test_split_number_followed_by_lowercase():
    assert m.split_sentences("It was 5. then we left. Done.") == [
        "It was 5. then we left.", "Done."]


def test_split_number_followed_by_uppercase_splits():
    assert m.split_sentences("It was 5. Then we left.") == ["It was 5.", "Then we left."]


def test_split_closing_quote():
    assert m.split_sentences('He said "stop." Then left.') == ['He said "stop."', "Then left."]


def test_split_ellipsis():
    assert m.split_sentences("Wait… what happened?") == ["Wait…", "what happened?"]


# ---------- _split_long ----------

def test_split_long_short_unchanged():
    assert m._split_long("a b c", 5) == ["a b c"]


def test_split_long_preserves_words_and_limit():
    s = " ".join(f"w{i}" for i in range(50))
    parts = m._split_long(s, 10)
    assert " ".join(parts).split() == s.split()
    assert all(len(p.split()) <= 10 for p in parts)


def test_split_long_prefers_comma():
    words = ["a"] * 9 + ["b,"] + ["c"] * 10
    parts = m._split_long(" ".join(words), 12)
    assert parts[0].endswith("b,")


def test_split_long_multiple_commas_picks_closest_to_middle():
    # commas after word 5 and word 11 (of 20); middle is 10 -> choose 11
    words = ["a"] * 4 + ["x,"] + ["a"] * 5 + ["y,"] + ["a"] * 9
    parts = m._split_long(" ".join(words), 12)
    assert parts[0].endswith("y,")
    assert len(parts[0].split()) == 11


def test_split_long_comma_closer_first_then_farther():
    # comma at 10 (closest), later comma at 15 is farther -> keep 10
    words = ["a"] * 9 + ["x,"] + ["a"] * 4 + ["y,"] + ["a"] * 5
    parts = m._split_long(" ".join(words), 15)
    assert parts[0].endswith("x,")


# ---------- segment_script ----------

def test_segment_empty():
    assert m.segment_script("") == []
    assert m.segment_script("  \n\n ") == []


def test_segment_preserves_words():
    text = ("This is the first sentence of the script. Here is another one that follows it. "
            "Short one. " + "word " * 60 + "end.\n\nNew paragraph starts here and goes on a bit more.")
    beats = m.segment_script(text)
    assert " ".join(beats).split() == text.split()
    assert all(len(b.split()) <= 26 for b in beats)


def test_segment_paragraphs_separate():
    text = "Alpha beta gamma delta epsilon zeta eta theta.\n\nIota kappa lambda mu nu xi omicron pi."
    assert len(m.segment_script(text)) == 2


def test_segment_short_tail_merged():
    text = "One two three four five six seven eight nine ten. Yes."
    assert m.segment_script(text) == [text]


def test_segment_single_short():
    assert m.segment_script("Hi there.") == ["Hi there."]


def test_segment_short_paragraph_after_long_merges_into_previous():
    text = "Alpha beta gamma delta epsilon zeta eta theta.\n\nOk."
    beats = m.segment_script(text)
    assert beats == ["Alpha beta gamma delta epsilon zeta eta theta. Ok."]


def test_segment_short_paragraph_not_merged_when_prev_full():
    long_para = " ".join(["w"] * 26) + "."
    # 26 words + terminator attached; previous beat has 26 words -> no merge
    beats = m.segment_script(long_para + "\n\nOk.")
    assert beats[-1] == "Ok."


def test_segment_two_long_sentences_split_into_beats():
    s1 = "one two three four five six seven eight."
    s2 = "nine ten eleven twelve thirteen fourteen fifteen sixteen."
    assert m.segment_script(s1 + " " + s2) == [s1, s2]


# ---------- norm_token / WER ----------

def test_norm_token():
    assert m.norm_token("Hello,") == "hello"
    assert m.norm_token("“Wow!”") == "wow"
    assert m.norm_token("...") == ""
    assert m.norm_token("Straße") == "straße"
    assert m.norm_token("ＡＢ") == "ab"


def test_wer_identical_and_empty():
    assert m.word_error_rate("a b c", "A, b. C!") == 0.0
    assert m.word_error_rate("", "anything") == 0.0
    assert m.word_error_rate("...", "x") == 0.0


def test_wer_values():
    assert m.word_error_rate("a b c d", "") == 1.0
    assert m.word_error_rate("a b c d", "a b c x") == pytest.approx(0.25)
    assert m.word_error_rate("a b", "a b c d") == pytest.approx(0.5)


# ---------- align_words ----------

def H(word, s, e):
    return {"word": word, "start": s, "end": e}


def test_align_exact():
    out = m.align_words("Hello, world!", [H("hello", 0.0, 0.5), H("world", 0.6, 1.0)], 1.5)
    assert out == [{"word": "Hello,", "start": 0.0, "end": 0.5},
                   {"word": "world!", "start": 0.6, "end": 1.0}]


def test_align_interpolates_middle():
    out = m.align_words("a bb cc d", [H("a", 0, 1), H("d", 3, 4)], 4)
    assert [o["word"] for o in out] == ["a", "bb", "cc", "d"]
    assert out[1]["start"] == 1.0 and out[1]["end"] == 2.0
    assert out[2]["start"] == 2.0 and out[2]["end"] == 3.0


def test_align_no_heard_uses_duration():
    out = m.align_words("ab cd", [], 2.0)
    assert out[0]["start"] == 0.0 and out[0]["end"] == 1.0
    assert out[1]["end"] == 2.0


def test_align_trailing_gap_to_duration():
    out = m.align_words("a b", [H("a", 0, 1)], 3.0)
    assert out[1]["start"] == 1.0 and out[1]["end"] == 3.0


def test_align_clamped_and_monotonic():
    out = m.align_words("a b", [H("a", 0, 5), H("b", 6, 9)], 4.0)
    assert all(o["end"] <= 4.0 and o["start"] <= 4.0 for o in out)
    starts = [o["start"] for o in out]
    assert starts == sorted(starts)


def test_align_empty_script():
    assert m.align_words("", [H("a", 0, 1)], 1.0) == []


def test_align_punctuation_only_token_matching_empty_heard():
    # "—" normalises to "" and matches an empty heard token; it must be interpolated
    out = m.align_words("a — b", [H("a", 0, 1), H("", 5, 6), H("b", 2, 3)], 3.0)
    assert [o["word"] for o in out] == ["a", "—", "b"]
    assert out[0]["start"] == 0.0
    assert out[2]["start"] == 2.0
    assert out[1]["start"] >= out[0]["start"]
    assert out[1]["end"] <= 2.0


def test_align_mismatch_with_gap_before_first_match():
    out = m.align_words("zz a", [H("a", 2, 3)], 3.0)
    assert out[0]["start"] == 0.0 and out[0]["end"] == 2.0
    assert out[1]["start"] == 2.0


# ---------- caption_chunks ----------

def mk(text, step=0.3, t=0.0):
    out = []
    for w in text.split():
        out.append({"word": w, "start": round(t, 3), "end": round(t + 0.2, 3)})
        t += step
    return out


def test_caption_empty():
    assert m.caption_chunks([]) == []


def test_caption_sentence_split():
    ch = m.caption_chunks(mk("Hello there. How are you?"))
    assert [c["text"] for c in ch] == ["Hello there.", "How are you?"]
    assert ch[0]["start"] == 0.0 and ch[0]["end"] == 0.5


def test_caption_gap_split():
    w = mk("one two") + mk("three four", t=5.0)
    assert [c["text"] for c in m.caption_chunks(w)] == ["one two", "three four"]


def test_caption_quote_terminator():
    ch = m.caption_chunks(mk('He said "go." Then left'))
    assert ch[0]["text"] == 'He said "go."'


def test_caption_long_balanced_lines():
    text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november"
    ch = m.caption_chunks(mk(text), max_chars=30)
    assert len(ch) >= 2
    assert " ".join(c["text"] for c in ch) == text
    assert all(len(c["text"]) <= 30 for c in ch)


def test_caption_no_break_after_function_word():
    text = "the quick brown fox jumps over the lazy dog and the cat"
    ch = m.caption_chunks(mk(text), max_chars=30)
    assert " ".join(c["text"] for c in ch) == text
    for c in ch[:-1]:
        assert c["text"].split()[-1] not in m._FUNC


def test_caption_prefers_comma():
    text = "this is quite long, and then it continues for much longer"
    ch = m.caption_chunks(mk(text), max_chars=40)
    assert ch[0]["text"].endswith(",")


def test_split_balanced_single_word():
    seg = [{"word": "x" * 100, "start": 0, "end": 1}]
    assert m._split_balanced(seg, 10) == [seg]


def test_split_balanced_oversized_word_among_others():
    seg = [{"word": w, "start": i, "end": i + 1}
           for i, w in enumerate(["short", "x" * 50, "tiny", "words", "here"])]
    lines = m._split_balanced(seg, 20)
    flat = [w["word"] for line in lines for w in line]
    assert flat == [w["word"] for w in seg]
    assert len(lines) >= 2
