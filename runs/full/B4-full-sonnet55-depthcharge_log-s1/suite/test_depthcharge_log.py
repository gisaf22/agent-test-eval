# tests/test_depthcharge_log.py
import logging
import sys

import pytest

import depthcharge_log as dl


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.NOTSET)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def handler():
    name = "test_dl_logger_unique"
    lg = logging.getLogger(name)
    old_level = lg.level
    old_prop = lg.propagate
    lg.propagate = False
    h = ListHandler()
    lg.addHandler(h)
    yield h
    lg.removeHandler(h)
    lg.setLevel(old_level)
    lg.propagate = old_prop


@pytest.fixture
def log(handler, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    return dl.DepthchargeLog(logger_name="test_dl_logger_unique")


@pytest.fixture
def restore_root():
    old = dl.get_level()
    yield
    dl.set_level(old)


def test_level_constants():
    assert dl.DEBUG == logging.DEBUG
    assert dl.DEBUG < dl.NOTE < dl.INFO
    assert dl.NOTE == 15
    assert dl.INFO == logging.INFO
    assert dl.WARNING == logging.WARNING
    assert dl.ERROR == logging.ERROR
    assert dl.SILENT == 60
    assert dl.SILENT > logging.CRITICAL


@pytest.mark.parametrize("name,value", [
    ("debug", dl.DEBUG), ("note", dl.NOTE), ("info", dl.INFO),
    ("warn", dl.WARNING), ("warning", dl.WARNING), ("error", dl.ERROR),
    ("fatal", dl.ERROR), ("critical", dl.ERROR), ("silent", dl.SILENT),
    ("DEBUG", dl.DEBUG), ("Note", dl.NOTE),
])
def test_level_by_name(log, name, value):
    log.level = name
    assert log.level == value


def test_level_by_int(log):
    log.level = dl.INFO
    assert log.level == dl.INFO


def test_invalid_level_name(log):
    with pytest.raises(ValueError, match="Invalid log level"):
        log.level = "bogus"


@pytest.mark.parametrize("method,pfx,lvl", [
    ("debug", "[#] ", dl.DEBUG),
    ("note", "[*] ", dl.NOTE),
    ("info", "[+] ", dl.INFO),
    ("warning", "[!] ", dl.WARNING),
    ("error", "[X] ", dl.ERROR),
])
def test_prefix_and_level(log, handler, method, pfx, lvl):
    log.level = "debug"
    getattr(log, method)("hello")
    assert len(handler.records) == 1
    r = handler.records[0]
    assert r.levelno == lvl
    assert r.getMessage() == pfx + "hello"


def test_custom_prefix_gets_space(handler, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    l = dl.DepthchargeLog(prefix="abc", logger_name="test_dl_logger_unique")
    l.level = "debug"
    l.info("msg")
    assert handler.records[0].getMessage() == "[+] abc msg"


def test_custom_prefix_with_space_kept(handler, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    l = dl.DepthchargeLog(prefix="abc ", logger_name="test_dl_logger_unique")
    l.level = "debug"
    l.info("msg")
    assert handler.records[0].getMessage() == "[+] abc msg"


def test_color_when_tty(handler, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(dl.platform, "system", lambda: "Linux")
    l = dl.DepthchargeLog(logger_name="test_dl_logger_unique")
    l.level = "debug"
    l.error("x")
    assert handler.records[0].getMessage() == "\033[31m[X] \033[0mx"


def test_no_color_on_windows(handler, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(dl.platform, "system", lambda: "Windows")
    l = dl.DepthchargeLog(logger_name="test_dl_logger_unique")
    l.level = "debug"
    l.note("x")
    assert handler.records[0].getMessage() == "[*] x"


def test_format_args(log, handler):
    log.level = "debug"
    log.info("value %d and %s", 5, "z")
    assert handler.records[0].getMessage() == "[+] value 5 and z"


def test_filtering_by_level(log, handler):
    log.level = "warning"
    log.debug("a")
    log.note("b")
    log.info("c")
    log.warning("d")
    log.error("e")
    assert [r.getMessage()[:3] for r in handler.records] == ["[!]", "[X]"]


def test_note_hidden_at_info_shown_at_note(log, handler):
    log.level = "info"
    log.note("n")
    assert handler.records == []
    log.level = "note"
    log.note("n")
    assert len(handler.records) == 1


def test_silent(log, handler):
    log.level = "silent"
    log.error("e")
    assert handler.records == []


def test_no_args_raises(log):
    with pytest.raises(IndexError):
        log.info()


def test_shared_logger():
    a = dl.DepthchargeLog(logger_name="shared_x")
    b = dl.DepthchargeLog(logger_name="shared_x")
    assert a.logger is b.logger


def test_set_get_level(restore_root):
    dl.set_level("error")
    assert dl.get_level() == dl.ERROR
    dl.set_level(dl.DEBUG)
    assert dl.get_level() == dl.DEBUG
    with pytest.raises(ValueError):
        dl.set_level("nope")


def test_module_functions(restore_root):
    h = ListHandler()
    lg = dl._depthcharge_root.logger
    lg.addHandler(h)
    try:
        dl.set_level("debug")
        dl.debug("a")
        dl.note("b")
        dl.info("c")
        dl.warning("d")
        dl.error("e")
        levels = [r.levelno for r in h.records]
        assert levels == [dl.DEBUG, dl.NOTE, dl.INFO, dl.WARNING, dl.ERROR]
        assert all(r.getMessage().endswith(m)
                   for r, m in zip(h.records, "abcde"))
    finally:
        lg.removeHandler(h)
