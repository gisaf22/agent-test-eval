# tests/test_sentineledgeai_pdf.py
import re
import zlib

import pytest

import sentineledgeai_pdf as m
from sentineledgeai_pdf import PDF, A4, text_width, _esc


def content_streams(data):
    out = []
    for mt in re.finditer(rb'<< /Length (\d+) /Filter /FlateDecode >>\nstream\n', data):
        n = int(mt.group(1))
        raw = data[mt.end():mt.end() + n]
        assert data[mt.end() + n:].startswith(b'\nendstream')
        out.append(zlib.decompress(raw).decode('latin-1'))
    return out


def test_a4_constant():
    assert A4 == (595, 842)


def test_text_width():
    assert text_width("abcd", 10) == pytest.approx(4 * 10 * 0.52)
    assert text_width("abcd", 10, bold=True) == pytest.approx(4 * 10 * 0.56)
    assert text_width("", 12) == 0
    assert text_width(123, 10) == pytest.approx(3 * 10 * 0.52)


def test_esc():
    assert _esc("a(b)c\\") == "a\\(b\\)c\\\\"
    assert _esc("€") == "?"
    assert _esc("é") == "é"
    assert _esc(42) == "42"


def test_initial_state():
    p = PDF()
    assert (p.w, p.h) == A4
    assert len(p.pages) == 1
    q = PDF((100, 200))
    assert (q.w, q.h) == (100, 200)


def test_add_page_returns_self():
    p = PDF()
    assert p.add_page() is p
    assert len(p.pages) == 2


def test_header_and_trailer():
    data = PDF().output()
    assert data.startswith(b'%PDF-1.4\n')
    assert data.endswith(b'%%EOF\n')
    assert b'/Type /Catalog' in data
    assert b'/BaseFont /Helvetica ' in data
    assert b'/BaseFont /Helvetica-Bold' in data


def test_output_is_repeatable():
    p = PDF()
    p.text(10, 10, "x")
    assert p.output() == p.output()


def test_xref_offsets_valid():
    p = PDF()
    p.text(10, 10, "x")
    p.add_page()
    p.rect(0, 0, 5, 5)
    data = p.output()
    sx = int(re.search(rb'startxref\n(\d+)\n', data).group(1))
    assert data[sx:sx + 5] == b'xref\n'
    lines = data[sx:].split(b'\n')
    count = int(lines[1].split()[1])
    assert lines[2] == b'0000000000 65535 f '
    size = int(re.search(rb'/Size (\d+)', data).group(1))
    assert size == count
    for i in range(1, count):
        off = int(lines[2 + i].split()[0])
        assert data[off:].startswith(b'%d 0 obj\n' % i)


def test_page_count_and_kids():
    p = PDF()
    p.add_page().add_page()
    data = p.output()
    assert b'/Count 3' in data
    assert len(re.findall(rb'/Type /Page /', data)) == 3
    kids = re.search(rb'/Kids \[(.*?)\]', data).group(1)
    assert len(re.findall(rb'\d+ 0 R', kids)) == 3
    assert b'/MediaBox [0 0 595 842]' in data


def test_custom_mediabox():
    assert b'/MediaBox [0 0 100 200]' in PDF((100, 200)).output()


def test_root_references_catalog():
    data = PDF().output()
    root = int(re.search(rb'/Root (\d+) 0 R', data).group(1))
    assert data.find(b'%d 0 obj\n<< /Type /Catalog' % root) != -1


def test_text_operator():
    p = PDF()
    p.text(10, 20, "Hi")
    assert content_streams(p.output()) == ["BT 0.00 g /F1 10 Tf 10.0 822.0 Td (Hi) Tj ET"]


def test_text_bold_gray_size():
    p = PDF()
    p.text(1, 2, "B", size=14, bold=True, gray=0.5)
    assert content_streams(p.output())[0] == "BT 0.50 g /F2 14 Tf 1.0 840.0 Td (B) Tj ET"


def test_text_escaped_in_stream():
    p = PDF()
    p.text(0, 0, "a(b)\\ €é")
    s = content_streams(p.output())[0]
    assert "(a\\(b\\)\\\\ ?é)" in s


def test_rect_gray_and_rgb():
    p = PDF()
    p.rect(10, 20, 100, 50)
    p.rect(10, 20, 100, 50, rgb=(1, 0.5, 0))
    s = content_streams(p.output())[0].split('\n')
    assert s[0] == "0.90 g 10.0 772.0 100.0 50.0 re f"
    assert s[1] == "1.000 0.500 0.000 rg 10.0 772.0 100.0 50.0 re f"


def test_line():
    p = PDF()
    p.line(0, 0, 100, 100)
    assert content_streams(p.output())[0] == "0.70 G 0.5 w 0.0 842.0 m 100.0 742.0 l S"


def test_ops_go_to_latest_page():
    p = PDF()
    p.text(0, 0, "one")
    p.add_page()
    p.text(0, 0, "two")
    streams = content_streams(p.output())
    assert len(streams) == 2
    assert "one" in streams[0] and "two" not in streams[0]
    assert "two" in streams[1]


def test_empty_page_stream():
    assert content_streams(PDF().output()) == [""]


def test_operation_order_preserved():
    p = PDF()
    p.rect(0, 0, 1, 1)
    p.line(0, 0, 1, 1)
    p.text(0, 0, "t")
    s = content_streams(p.output())[0].split('\n')
    assert s[0].endswith("re f") and s[1].endswith("l S") and s[2].startswith("BT")
