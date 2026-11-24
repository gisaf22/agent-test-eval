# tests/test_sentineledgeai_pdf.py
import re
import zlib

import pytest

import sentineledgeai_pdf as m
from sentineledgeai_pdf import PDF, A4, text_width, _esc


def parse(data):
    """Return (objects dict num->bytes, trailer text) using the xref table."""
    sx = int(re.search(rb"startxref\n(\d+)\n%%EOF\n$", data).group(1))
    assert data[sx:sx + 4] == b"xref"
    lines = data[sx:].split(b"\n")
    count = int(lines[1].split()[1])
    entries = lines[2:2 + count]
    assert entries[0] == b"0000000000 65535 f "
    objs = {}
    for i, e in enumerate(entries[1:], 1):
        off = int(e[:10])
        assert e[10:] == b" 00000 n "
        assert data[off:].startswith(b"%d 0 obj\n" % i)
        end = data.index(b"\nendobj\n", off)
        objs[i] = data[off + len(b"%d 0 obj\n" % i):end]
    return objs, data[sx:]


def contents(data):
    objs, _ = parse(data)
    res = []
    for body in objs.values():
        if b"/FlateDecode" in body:
            length = int(re.search(rb"/Length (\d+)", body).group(1))
            start = body.index(b"stream\n") + 7
            res.append(zlib.decompress(body[start:start + length]).decode("latin-1"))
    return res


def test_a4_constant():
    assert A4 == (595, 842)


def test_text_width():
    assert text_width("abcd", 10) == pytest.approx(4 * 10 * 0.52)
    assert text_width("abcd", 10, bold=True) == pytest.approx(4 * 10 * 0.56)
    assert text_width("", 12) == 0
    assert text_width(123, 10) == pytest.approx(3 * 10 * 0.52)


def test_esc():
    assert _esc("a(b)c\\d") == "a\\(b\\)c\\\\d"
    assert _esc("€") == "?"
    assert _esc("é") == "é"
    assert _esc(42) == "42"


def test_init_has_one_page_and_size():
    p = PDF()
    assert len(p.pages) == 1
    assert (p.w, p.h) == A4
    q = PDF((100, 200))
    assert (q.w, q.h) == (100, 200)


def test_add_page_returns_self():
    p = PDF()
    assert p.add_page() is p
    assert len(p.pages) == 2


def test_header_and_trailer():
    data = PDF().output()
    assert data.startswith(b"%PDF-1.4\n")
    assert data.endswith(b"%%EOF\n")
    objs, tail = parse(data)
    assert b"/Size %d" % (len(objs) + 1) in tail
    root = int(re.search(rb"/Root (\d+) 0 R", tail).group(1))
    assert b"/Type /Catalog" in objs[root]


def test_object_structure_single_page():
    objs, tail = parse(PDF().output())
    assert len(objs) == 6
    assert b"/Helvetica " in objs[1]
    assert b"/Helvetica-Bold" in objs[2]
    assert b"/Type /Page " in objs[4]
    assert b"/MediaBox [0 0 595 842]" in objs[4]
    assert b"/Contents 3 0 R" in objs[4]
    assert b"/Parent 5 0 R" in objs[4]
    assert b"/Kids [4 0 R]" in objs[5] and b"/Count 1" in objs[5]
    assert b"/Pages 5 0 R" in objs[6]
    assert b"/Root 6 0 R" in tail


def test_multiple_pages():
    p = PDF()
    p.text(10, 10, "one")
    p.add_page()
    p.text(10, 10, "two")
    p.add_page()
    data = p.output()
    objs, _ = parse(data)
    assert b"/Count 3" in objs[9]
    assert b"/Kids [4 0 R 6 0 R 8 0 R]" in objs[9]
    cs = contents(data)
    assert len(cs) == 3
    assert "one" in cs[0] and "two" in cs[1] and cs[2] == ""


def test_text_operator():
    p = PDF()
    p.text(50, 10, "Hi")
    assert contents(p.output())[0] == "BT 0.00 g /F1 10 Tf 50.0 832.0 Td (Hi) Tj ET"


def test_text_bold_size_gray():
    p = PDF()
    p.text(1, 2, "x", size=14, bold=True, gray=0.5)
    assert "0.50 g /F2 14 Tf 1.0 840.0 Td (x)" in contents(p.output())[0]


def test_text_escaping_and_latin1():
    p = PDF()
    p.text(0, 0, "a(b)\\ é €")
    c = contents(p.output())[0]
    assert "(a\\(b\\)\\\\ é ?)" in c


def test_rect_gray_and_rgb():
    p = PDF()
    p.rect(10, 20, 100, 50)
    p.rect(0, 0, 5, 5, rgb=(1, 0.5, 0))
    lines = contents(p.output())[0].split("\n")
    assert lines[0] == "0.90 g 10.0 772.0 100.0 50.0 re f"
    assert lines[1] == "1.000 0.500 0.000 rg 0.0 837.0 5.0 5.0 re f"


def test_line():
    p = PDF()
    p.line(0, 0, 100, 10)
    assert contents(p.output())[0] == "0.70 G 0.5 w 0.0 842.0 m 100.0 832.0 l S"


def test_ops_go_to_last_page_in_order():
    p = PDF()
    p.text(0, 0, "a")
    p.add_page()
    p.text(0, 0, "b")
    p.rect(0, 0, 1, 1)
    assert len(p.pages[0]) == 1 and len(p.pages[1]) == 2
    cs = contents(p.output())
    assert "(a)" in cs[0] and "(b)" in cs[1] and "re f" in cs[1]


def test_custom_size_flips_y():
    p = PDF((200, 100))
    p.text(5, 10, "z")
    data = p.output()
    assert b"/MediaBox [0 0 200 100]" in data
    assert "5.0 90.0 Td" in contents(data)[0]


def test_output_deterministic_and_repeatable():
    p = PDF()
    p.text(1, 1, "x")
    assert p.output() == p.output()
