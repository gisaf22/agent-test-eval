# tests/test_depthcharge_log.py
import logging
import sys

import pytest

import depthcharge_log as dl


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.NOTSET)
        self.records = []

    def emit(self, record):
        self.records.append(record)


class FakeStdout:
    def __init__(self, tty):
        self.tty = tty

    def isatty(self):
        return self.tty

    def write(self, s):
        return len(s)

    def flush(self):
        pass


@pytest.fixture
def logger_name(request):
    return "dc_test_" + request.node.name


@pytest.fixture
def inst(logger_name):
    lg = dl.DepthchargeLog(logger_name=logger_name)
    h = Capture()
    lg.logger.addHandler(h)
    lg.logger.propagate = False
    lg.h = h
    yield lg
    lg.logger.removeHandler(h)


@pytest.fixture
def restore_root_level():
    old = dl.get_level()
    yield
    dl.set_level(old)


def test_constants_ordering():
    assert dl.DEBUG < dl.NOTE < dl.INFO < dl.WARNING < dl.ERROR < dl.SILENT
    assert dl.NOTE == logging.DEBUG + (logging.INFO - logging.DEBUG) // 2
    assert dl.SILENT > logging.CRITICAL


def test_level_name_map(inst):
    expected = {
        'debug': dl.DEBUG, 'note': dl.NOTE, 'info': dl.INFO,
        'warn': dl.WARNING, 'warning': dl.WARNING, 'error': dl.ERROR,
        'fatal': dl.ERROR, 'critical': dl.ERROR, 'silent': dl.SILENT,
    }
    for name, val in expected.items():
        inst.level = name
        assert inst.level == val
        inst.level = name.upper()
        assert inst.level == val


def test_level_int(inst):
    inst.level = dl.INFO
    assert inst.level == dl.INFO


def test_invalid_level(inst):
    with pytest.raises(ValueError, match="Invalid log level"):
        inst.level = "bogus"


def test_shared_logger():
    a = dl.DepthchargeLog(logger_name="dc_shared_x")
    b = dl.DepthchargeLog(logger_name="dc_shared_x")
    assert a.logger is b.logger


def test_prefix_symbols_and_levels(inst):
    inst.level = dl.DEBUG
    inst.debug("d")
    inst.note("n")
    inst.info("i")
    inst.warning("w")
    inst.error("e")
    recs = inst.h.records
    assert [r.levelno for r in recs] == [dl.DEBUG, dl.NOTE, dl.INFO, dl.WARNING, dl.ERROR]
    syms = ['[#] ', '[*] ', '[+] ', '[!] ', '[X] ']
    for r, s, m in zip(recs, syms, "dniwe"):
        msg = r.getMessage()
        assert s in msg
        assert msg.endswith(m)


def test_custom_prefix_gets_space(inst, logger_name):
    lg = dl.DepthchargeLog(prefix="abc", logger_name=logger_name)
    assert lg._pfx_info.endswith("abc ")
    lg2 = dl.DepthchargeLog(prefix="abc ", logger_name=logger_name)
    assert lg2._pfx_info.endswith("abc ")
    assert not lg2._pfx_info.endswith("abc  ")


def test_prefix_in_message(inst, logger_name):
    lg = dl.DepthchargeLog(prefix="mod", logger_name=logger_name)
    inst.level = dl.DEBUG
    lg.info("hello")
    assert inst.h.records[-1].getMessage().endswith("mod hello")


def test_format_args(inst):
    inst.level = dl.DEBUG
    inst.info("x=%d y=%s", 5, "z")
    assert inst.h.records[-1].getMessage().endswith("x=5 y=z")


def test_filtering(inst):
    inst.level = dl.WARNING
    inst.debug("a")
    inst.note("b")
    inst.info("c")
    inst.warning("d")
    inst.error("e")
    assert len(inst.h.records) == 2


def test_note_level_filters_debug(inst):
    inst.level = 'note'
    inst.debug("a")
    inst.note("b")
    assert len(inst.h.records) == 1


def test_silent(inst):
    inst.level = 'silent'
    inst.error("x")
    assert inst.h.records == []


def test_kwargs_passthrough(inst):
    inst.level = dl.DEBUG
    inst.info("hi", extra={"foo": 1})
    assert inst.h.records[-1].foo == 1


def test_module_level_functions(restore_root_level):
    h = Capture()
    root = dl._depthcharge_root.logger
    root.addHandler(h)
    try:
        dl.set_level('debug')
        assert dl.get_level() == dl.DEBUG
        dl.debug("a")
        dl.note("b")
        dl.info("c")
        dl.warning("d")
        dl.error("e")
        assert [r.levelno for r in h.records] == [dl.DEBUG, dl.NOTE, dl.INFO, dl.WARNING, dl.ERROR]
        h.records.clear()
        dl.set_level(dl.ERROR)
        dl.warning("x")
        dl.error("y")
        assert len(h.records) == 1
    finally:
        root.removeHandler(h)


def test_set_level_invalid(restore_root_level):
    with pytest.raises(ValueError):
        dl.set_level("nope")


def test_root_has_stream_handler():
    assert any(isinstance(x, logging.StreamHandler)
               for x in dl._depthcharge_root.logger.handlers)


@pytest.mark.parametrize("system", ["Linux", "Darwin"])
def test_color_prefixes_on_tty(monkeypatch, system, logger_name):
    monkeypatch.setattr(dl.platform, "system", lambda: system)
    monkeypatch.setattr(sys, "stdout", FakeStdout(True))
    lg = dl.DepthchargeLog(prefix="p", logger_name=logger_name)
    assert lg._pfx_debug == '\033[34m[#] \033[0m' + 'p '
    assert lg._pfx_note == '\033[36m[*] \033[0m' + 'p '
    assert lg._pfx_info == '\033[32m[+] \033[0m' + 'p '
    assert lg._pfx_warning == '\033[33m[!] \033[0m' + 'p '
    assert lg._pfx_error == '\033[31m[X] \033[0m' + 'p '


def test_no_color_when_not_tty(monkeypatch, logger_name):
    monkeypatch.setattr(dl.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sys, "stdout", FakeStdout(False))
    lg = dl.DepthchargeLog(logger_name=logger_name)
    assert lg._pfx_info == '[+] '
    assert lg._pfx_error == '[X] '


def test_no_color_on_other_platform(monkeypatch, logger_name):
    monkeypatch.setattr(dl.platform, "system", lambda: "Windows")
    monkeypatch.setattr(sys, "stdout", FakeStdout(True))
    lg = dl.DepthchargeLog(logger_name=logger_name)
    assert lg._pfx_debug == '[#] '
    assert lg._pfx_note == '[*] '
    assert lg._pfx_warning == '[!] '
