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
    assert m.split_sentences("One.\n\n  Two.") == ["One.", "Two."]


def test_split_abbreviation_not_split():
    assert m.split_sentences("Dr. Smith went home. He slept.") == [
        "Dr. Smith went home.", "He slept."]


def test_split_number_followed_by_lowercase():
    assert m.split_sentences("Chapter 3. see below. Done.") == [
        "Chapter 3. see below.", "Done."]


def test_split_number_followed_by_uppercase_splits():
    assert m.split_sentences("It was 3. Then it ended.") == [
        "It was 3.", "Then it ended."]


def test_split_closing_quote():
    assert m.split_sentences('He said "stop." Then left.') == [
        'He said "stop."', "Then left."]


def test_split_no_terminal_punct():
    assert m.split_sentences("No ending here") == ["No ending here"]


def test_split_ellipsis():
    assert m.split_sentences("Wait… what happened?") == ["Wait…", "what happened?"]


# ---------- _split_long / segment_script ----------

def test_split_long_short_unchanged():
    assert m._split_long("a b c", 5) == ["a b c"]


def test_split_long_prefers_comma_near_middle():
    s = "one two three four five, six seven eight nine ten"
    assert m._split_long(s, 6) == ["one two three four five,", "six seven eight nine ten"]


def test_split_long_no_comma_halves():
    s = " ".join(str(i) for i in range(10))
    out = m._split_long(s, 5)
    assert out == ["0 1 2 3 4", "5 6 7 8 9"]


def test_split_long_respects_max():
    s = " ".join("w" * 3 for _ in range(50))
    for p in m._split_long(s, 10):
        assert len(p.split()) <= 10


def test_segment_empty():
    assert m.segment_script("") == []
    assert m.segment_script("  \n\n ") == []


def test_segment_preserves_words():
    text = ("The sun rose over the hills, painting the sky in gold. Birds began to sing. "
            "Everyone woke up slowly and smiled at the new day ahead of them all.\n\n"
            "Second paragraph here. It has two sentences in total, nothing more than that.")
    beats = m.segment_script(text)
    assert " ".join(beats).split() == text.split()


def test_segment_paragraphs_never_merge_across_boundary():
    beats = m.segment_script("Alpha beta gamma delta epsilon zeta eta theta.\n\nIota kappa lambda mu nu xi omicron pi.")
    assert len(beats) == 2
    assert beats[0].startswith("Alpha") and beats[1].startswith("Iota")


def test_segment_max_words_respected():
    text = " ".join(f"w{i}" for i in range(100)) + "."
    for b in m.segment_script(text, min_words=7, max_words=20):
        assert len(b.split()) <= 20


def test_segment_short_tail_merged():
    text = "One two three four five six seven eight. Ok."
    beats = m.segment_script(text)
    assert beats == ["One two three four five six seven eight. Ok."]


def test_segment_two_long_sentences_separate():
    text = "One two three four five six seven. Eight nine ten eleven twelve thirteen fourteen."
    assert m.segment_script(text) == [
        "One two three four five six seven.",
        "Eight nine ten eleven twelve thirteen fourteen."]


# ---------- norm_token / WER ----------

def test_norm_token():
    assert m.norm_token("Hello,") == "hello"
    assert m.norm_token("“Wow!”") == "wow"
    assert m.norm_token("...") == ""
    assert m.norm_token("Ｆull") == "full"
    assert m.norm_token("Straße") == "straße"


def test_wer_identical_and_punct_case():
    assert m.word_error_rate("Hello, World.", "hello world") == 0.0


def test_wer_empty_reference():
    assert m.word_error_rate("", "anything") == 0.0
    assert m.word_error_rate("...", "x") == 0.0


def test_wer_empty_hyp():
    assert m.word_error_rate("a b c", "") == 1.0


def test_wer_partial():
    assert m.word_error_rate("a b c d", "a b x d") == pytest.approx(0.25)


def test_wer_extra_hyp_words():
    assert m.word_error_rate("a b", "a b c d") == pytest.approx(0.5)


# ---------- align_words ----------

def H(word, s, e):
    return {"word": word, "start": s, "end": e}


def test_align_exact():
    out = m.align_words("Hello, world.", [H("hello", 0, 0.5), H("world", 0.6, 1.0)], 2.0)
    assert out == [{"word": "Hello,", "start": 0.0, "end": 0.5},
                   {"word": "world.", "start": 0.6, "end": 1.0}]


def test_align_keeps_script_words():
    out = m.align_words("Foo bar baz", [H("foo", 0, 1), H("baz", 2, 3)], 3)
    assert [w["word"] for w in out] == ["Foo", "bar", "baz"]
    assert out[1]["start"] == 1.0 and out[1]["end"] == 2.0


def test_align_interpolate_by_weight():
    out = m.align_words("a bb ccc d", [H("a", 0, 1), H("d", 5, 6)], 6)
    # gap [1,5], weights 2 and 3
    assert out[1]["start"] == 1.0
    assert out[1]["end"] == pytest.approx(1 + 4 * 2 / 5, abs=1e-3)
    assert out[2]["end"] == 5.0


def test_align_leading_gap_starts_at_zero():
    out = m.align_words("x y", [H("y", 2, 3)], 3)
    assert out[0]["start"] == 0.0 and out[0]["end"] == 2.0


def test_align_trailing_gap_uses_duration():
    out = m.align_words("x y", [H("x", 0, 1)], 4)
    assert out[1]["start"] == 1.0 and out[1]["end"] == 4.0


def test_align_no_heard():
    out = m.align_words("ab cd", [], 2.0)
    assert out[0]["start"] == 0.0
    assert out[1]["end"] == 2.0


def test_align_empty_script():
    assert m.align_words("", [H("a", 0, 1)], 1) == []


def test_align_clamped_and_monotonic():
    out = m.align_words("a b c", [H("a", 0, 1), H("b", 0.5, 9), H("c", 9, 10)], 3)
    starts = [w["start"] for w in out]
    assert starts == sorted(starts)
    for w in out:
        assert 0 <= w["start"] <= w["end"] <= 3


# ---------- _split_balanced / caption_chunks ----------

def W(word, s, e):
    return {"word": word, "start": s, "end": e}


def test_balanced_short_single_line():
    seg = [W("hi", 0, 1), W("there", 1, 2)]
    assert m._split_balanced(seg, 42) == [seg]


def test_balanced_respects_max_chars_and_order():
    seg = [W("word%d" % i, i, i + 1) for i in range(20)]
    lines = m._split_balanced(seg, 30)
    assert [w for l in lines for w in l] == seg
    for l in lines:
        assert len(" ".join(w["word"] for w in l)) <= 30


def test_balanced_prefers_comma():
    words = "alpha beta gamma, delta epsilon zeta eta theta".split()
    seg = [W(w, i, i + 1) for i, w in enumerate(words)]
    lines = m._split_balanced(seg, 30)
    assert len(lines) == 2
    assert lines[0][-1]["word"] == "gamma,"


def test_balanced_avoids_function_word_end():
    words = "the quick brown fox jumps over the lazy sleeping dog today".split()
    seg = [W(w, i, i + 1) for i, w in enumerate(words)]
    lines = m._split_balanced(seg, 30)
    for l in lines[:-1]:
        assert m.norm_token(l[-1]["word"]) not in m._FUNC


def test_chunks_empty():
    assert m.caption_chunks([]) == []


def test_chunks_sentence_boundaries():
    ws = [W("Hi.", 0, 1), W("Bye.", 1.1, 2)]
    assert m.caption_chunks(ws) == [
        {"text": "Hi.", "start": 0, "end": 1},
        {"text": "Bye.", "start": 1.1, "end": 2}]


def test_chunks_gap_splits():
    ws = [W("a", 0, 1), W("b", 2, 3)]
    out = m.caption_chunks(ws)
    assert [c["text"] for c in out] == ["a", "b"]


def test_chunks_small_gap_joins():
    ws = [W("a", 0, 1), W("b", 1.5, 2)]
    out = m.caption_chunks(ws)
    assert out == [{"text": "a b", "start": 0, "end": 2}]


def test_chunks_quote_terminators():
    ws = [W('stop."', 0, 1), W("Next", 1, 2)]
    out = m.caption_chunks(ws)
    assert [c["text"] for c in out] == ['stop."', "Next"]


def test_chunks_long_text_split_lines_within_limit():
    ws = [W("wordy%d" % i, i * 0.3, i * 0.3 + 0.2) for i in range(30)]
    out = m.caption_chunks(ws, max_chars=40)
    assert len(out) > 1
    assert all(len(c["text"]) <= 40 for c in out)
    assert " ".join(c["text"] for c in out).split() == [w["word"] for w in ws]
    assert out[0]["start"] == ws[0]["start"] and out[-1]["end"] == ws[-1]["end"]
