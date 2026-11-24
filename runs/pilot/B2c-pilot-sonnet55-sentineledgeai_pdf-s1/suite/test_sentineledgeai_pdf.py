# tests/test_sentineledgeai_pdf.py
import re
import zlib

import pytest

import sentineledgeai_pdf as m
from sentineledgeai_pdf import PDF, A4, _esc, text_width


def streams(data):
    res = []
    for mt in re.finditer(rb'/Length (\d+) /Filter /FlateDecode >>\nstream\n', data):
        n = int(mt.group(1))
        raw = data[mt.end():mt.end() + n]
        assert data[mt.end() + n:].startswith(b'\nendstream')
        res.append(zlib.decompress(raw).decode('latin-1'))
    return res


def test_a4_constant():
    assert A4 == (595, 842)


def test_text_width():
    assert text_width("abcd", 10) == pytest.approx(4 * 10 * 0.52)
    assert text_width("abcd", 10, bold=True) == pytest.approx(4 * 10 * 0.56)
    assert text_width("", 12) == 0
    assert text_width(123, 10) == pytest.approx(3 * 5.2)


def test_esc():
    assert _esc("a(b)c") == "a\\(b\\)c"
    assert _esc("a\\b") == "a\\\\b"
    assert _esc("€") == "?"
    assert _esc("é") == "é"
    assert _esc(42) == "42"


def test_init_and_add_page():
    p = PDF()
    assert (p.w, p.h) == A4
    assert len(p.pages) == 1
    assert p.add_page() is p
    assert len(p.pages) == 2
    q = PDF((100, 200))
    assert (q.w, q.h) == (100, 200)


def test_structure_header_trailer():
    data = PDF().output()
    assert data.startswith(b'%PDF-1.4\n')
    assert data.endswith(b'%%EOF\n')
    assert b'/Helvetica-Bold' in data and b'/WinAnsiEncoding' in data
    assert b'/MediaBox [0 0 595 842]' in data
    assert b'/Count 1' in data


def test_xref_offsets_valid():
    p = PDF()
    p.text(10, 10, "hi")
    p.add_page()
    p.rect(0, 0, 5, 5)
    data = p.output()
    sx = int(re.search(rb'startxref\n(\d+)\n', data).group(1))
    assert data[sx:].startswith(b'xref\n')
    mt = re.match(rb'xref\n0 (\d+)\n', data[sx:])
    count = int(mt.group(1))
    entries = re.findall(rb'(\d{10}) (\d{5}) ([nf]) \n', data[sx:])
    assert len(entries) == count
    assert entries[0] == (b'0000000000', b'65535', b'f')
    for i, (off, gen, kind) in enumerate(entries[1:], 1):
        assert kind == b'n'
        assert data[int(off):].startswith(b'%d 0 obj\n' % i)
    assert (b'/Size %d' % count) in data


def test_page_count_and_kids():
    p = PDF()
    p.add_page()
    p.add_page()
    data = p.output()
    assert b'/Count 3' in data
    assert data.count(b'/Type /Page ') == 3
    kids = re.search(rb'/Kids \[([^\]]*)\]', data).group(1)
    assert len(re.findall(rb'\d+ 0 R', kids)) == 3
    assert len(streams(data)) == 3


def test_root_points_to_catalog():
    data = PDF().output()
    root = int(re.search(rb'/Root (\d+) 0 R', data).group(1))
    assert (b'%d 0 obj\n<< /Type /Catalog' % root) in data


def test_text_op_and_flip():
    p = PDF()
    p.text(50, 100, "Hello", size=12, bold=True, gray=0.5)
    op = p.pages[0][0]
    assert op == 'BT 0.50 g /F2 12 Tf 50.0 742.0 Td (Hello) Tj ET'
    p.text(1, 2, "x")
    assert '/F1 10 Tf' in p.pages[0][1]


def test_text_escaped_in_stream():
    p = PDF()
    p.text(0, 0, "a(b)\\ €")
    s = streams(p.output())[0]
    assert '(a\\(b\\)\\\\ ?)' in s


def test_rect_ops():
    p = PDF()
    p.rect(10, 20, 100, 50)
    assert p.pages[0][-1] == '0.90 g 10.0 772.0 100.0 50.0 re f'
    p.rect(0, 0, 1, 1, rgb=(1, 0.5, 0))
    assert p.pages[0][-1].startswith('1.000 0.500 0.000 rg ')


def test_line_op():
    p = PDF()
    p.line(10, 10, 100, 20)
    assert p.pages[0][-1] == '0.70 G 0.5 w 10.0 832.0 m 100.0 822.0 l S'


def test_ops_go_to_latest_page():
    p = PDF()
    p.text(0, 0, "one")
    p.add_page()
    p.text(0, 0, "two")
    s = streams(p.output())
    assert "one" in s[0] and "two" not in s[0]
    assert "two" in s[1]


def test_stream_content_roundtrip_multiple_ops():
    p = PDF()
    p.text(0, 0, "a")
    p.line(0, 0, 1, 1)
    s = streams(p.output())[0]
    assert s.split('\n') == p.pages[0]


def test_empty_page_ok():
    s = streams(PDF().output())
    assert s == ['']


def test_deterministic_and_repeatable():
    p = PDF()
    p.text(1, 1, "x")
    assert p.output() == p.output()


def test_custom_size_mediabox_and_flip():
    p = PDF((200, 300))
    p.text(10, 10, "x")
    assert '290.0 Td' in p.pages[0][0]
    assert b'/MediaBox [0 0 200 300]' in p.output()
