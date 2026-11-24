# tests/test_depthcharge_log.py
import logging

import pytest

import depthcharge_log as dl


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=1)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def logger_name(request):
    return "dc_test_" + request.node.name


@pytest.fixture
def inst(logger_name, monkeypatch):
    # Force non-TTY so prefixes are plain
    monkeypatch.setattr(dl.sys.stdout, "isatty", lambda: False, raising=False) \
        if False else None
    lg = dl.DepthchargeLog(logger_name=logger_name)
    h = Capture()
    lg.logger.addHandler(h)
    lg.logger.propagate = False
    lg.h = h
    yield lg
    lg.logger.removeHandler(h)


@pytest.fixture
def restore_root():
    old = dl.get_level()
    yield
    dl.set_level(old)


def strip_ansi(s):
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def test_level_constants():
    assert dl.DEBUG == logging.DEBUG
    assert dl.INFO == logging.INFO
    assert dl.WARNING == logging.WARNING
    assert dl.ERROR == logging.ERROR
    assert dl.DEBUG < dl.NOTE < dl.INFO < dl.WARNING < dl.ERROR < dl.SILENT
    assert dl.NOTE == 15
    assert dl.SILENT == logging.CRITICAL + 10


@pytest.mark.parametrize("name,val", [
    ("debug", dl.DEBUG), ("note", dl.NOTE), ("info", dl.INFO),
    ("warn", dl.WARNING), ("warning", dl.WARNING), ("error", dl.ERROR),
    ("fatal", dl.ERROR), ("critical", dl.ERROR), ("silent", dl.SILENT),
    ("DEBUG", dl.DEBUG), ("Note", dl.NOTE),
])
def test_level_by_name(inst, name, val):
    inst.level = name
    assert inst.level == val


def test_level_by_int(inst):
    inst.level = dl.INFO
    assert inst.level == dl.INFO


def test_invalid_level_name(inst):
    with pytest.raises(ValueError, match="Invalid log level"):
        inst.level = "bogus"


@pytest.mark.parametrize("method,sym,lvl", [
    ("debug", "[#]", dl.DEBUG), ("note", "[*]", dl.NOTE),
    ("info", "[+]", dl.INFO), ("warning", "[!]", dl.WARNING),
    ("error", "[X]", dl.ERROR),
])
def test_method_prefix_and_level(inst, method, sym, lvl):
    inst.level = dl.DEBUG
    getattr(inst, method)("hello")
    assert len(inst.h.records) == 1
    r = inst.h.records[0]
    assert r.levelno == lvl
    assert strip_ansi(r.getMessage()) == sym + " hello"


def test_filtering(inst):
    inst.level = "warning"
    inst.debug("a")
    inst.note("b")
    inst.info("c")
    inst.warning("d")
    inst.error("e")
    assert len(inst.h.records) == 2


def test_silent_suppresses_all(inst):
    inst.level = "silent"
    inst.error("x")
    assert inst.h.records == []


def test_note_between_debug_and_info(inst):
    inst.level = "note"
    inst.debug("a")
    inst.note("b")
    inst.info("c")
    assert len(inst.h.records) == 2


def test_prefix_gets_space(logger_name):
    lg = dl.DepthchargeLog(prefix="abc", logger_name=logger_name)
    assert lg._pfx_info.endswith("abc ")


def test_prefix_existing_space_kept(logger_name):
    lg = dl.DepthchargeLog(prefix="abc ", logger_name=logger_name)
    assert lg._pfx_info.endswith("abc ")
    assert not lg._pfx_info.endswith("abc  ")


def test_empty_prefix(logger_name):
    lg = dl.DepthchargeLog(logger_name=logger_name)
    assert strip_ansi(lg._pfx_error) == "[X] "


def test_prefix_in_message(logger_name):
    lg = dl.DepthchargeLog(prefix="pfx", logger_name=logger_name)
    h = Capture()
    lg.logger.addHandler(h)
    lg.logger.propagate = False
    lg.level = "debug"
    lg.info("msg")
    assert strip_ansi(h.records[0].getMessage()) == "[+] pfx msg"


def test_format_args(inst):
    inst.level = "debug"
    inst.info("val %d %s", 5, "x")
    assert strip_ansi(inst.h.records[0].getMessage()) == "[+] val 5 x"


def test_kwargs_passthrough(inst):
    inst.level = "debug"
    inst.error("boom", extra={"foo": 1})
    assert inst.h.records[0].foo == 1


def test_shared_logger(logger_name):
    a = dl.DepthchargeLog(logger_name=logger_name)
    b = dl.DepthchargeLog(logger_name=logger_name)
    assert a.logger is b.logger
    a.level = "error"
    assert b.level == dl.ERROR


def test_tty_color(monkeypatch, logger_name):
    monkeypatch.setattr(dl.platform, "system", lambda: "Linux")
    monkeypatch.setattr(dl.sys, "stdout", type("S", (), {"isatty": lambda s: True})())
    lg = dl.DepthchargeLog(logger_name=logger_name)
    assert lg._pfx_error == "\033[31m[X] \033[0m"
    assert lg._pfx_info.startswith("\033[32m")


def test_no_color_on_windows(monkeypatch, logger_name):
    monkeypatch.setattr(dl.platform, "system", lambda: "Windows")
    monkeypatch.setattr(dl.sys, "stdout", type("S", (), {"isatty": lambda s: True})())
    lg = dl.DepthchargeLog(logger_name=logger_name)
    assert lg._pfx_error == "[X] "


def test_no_color_non_tty(monkeypatch, logger_name):
    monkeypatch.setattr(dl.platform, "system", lambda: "Linux")
    monkeypatch.setattr(dl.sys, "stdout", type("S", (), {"isatty": lambda s: False})())
    lg = dl.DepthchargeLog(logger_name=logger_name)
    assert lg._pfx_note == "[*] "


def test_set_get_level(restore_root):
    dl.set_level("info")
    assert dl.get_level() == dl.INFO
    dl.set_level(dl.DEBUG)
    assert dl.get_level() == dl.DEBUG
    with pytest.raises(ValueError):
        dl.set_level("nope")


@pytest.mark.parametrize("func,lvl", [
    ("debug", dl.DEBUG), ("note", dl.NOTE), ("info", dl.INFO),
    ("warning", dl.WARNING), ("error", dl.ERROR),
])
def test_module_functions(restore_root, func, lvl):
    h = Capture()
    root = dl._depthcharge_root.logger
    root.addHandler(h)
    try:
        dl.set_level("debug")
        getattr(dl, func)("hi %s", "there")
    finally:
        root.removeHandler(h)
    assert len(h.records) == 1
    assert h.records[0].levelno == lvl
    assert strip_ansi(h.records[0].getMessage()).endswith("hi there")


def test_root_has_stream_handler():
    hs = dl._depthcharge_root.logger.handlers
    assert any(isinstance(x, logging.StreamHandler) for x in hs)


def test_root_logger_name():
    assert dl._depthcharge_root.logger.name == "depthcharge"
