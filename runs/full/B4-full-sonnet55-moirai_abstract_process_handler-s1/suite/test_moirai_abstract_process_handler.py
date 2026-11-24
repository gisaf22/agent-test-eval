# tests/test_moirai_abstract_process_handler.py
import pytest

import moirai_abstract_process_handler as mod
from moirai_abstract_process_handler import AbstractProcessHandler


class FakePipe:
    def __init__(self, incoming=None, closed=False):
        self.incoming = list(incoming or [])
        self.sent = []
        self.closed = closed

    def poll(self):
        return bool(self.incoming) or self.closed

    def recv(self):
        if self.incoming:
            return self.incoming.pop(0)
        raise EOFError

    def send(self, obj):
        self.sent.append(obj)


class Recorder(AbstractProcessHandler):
    def __init__(self, name, pipe):
        super().__init__(name, pipe)
        self.commands = []
        self.loops = 0
        self.quit_called = False
        self.on_loop = None

    def process_command(self, sender, cmd, args):
        self.commands.append((sender, cmd, args))

    def loop(self):
        self.loops += 1
        if self.on_loop:
            self.on_loop(self)

    def quit(self):
        self.quit_called = True


def test_init_defaults(capsys):
    p = FakePipe()
    h = AbstractProcessHandler("X", p)
    assert "Starting X..." in capsys.readouterr().out
    assert h.sleep is True
    assert h.quitting is False
    assert h.pipe_for("parent") is p
    assert h.pipes() == ["parent"]


def test_set_sleep():
    h = AbstractProcessHandler("X", FakePipe())
    h.set_sleep(False)
    assert h.sleep is False


def test_pipe_for_unknown():
    h = AbstractProcessHandler("X", FakePipe())
    assert h.pipe_for("nope") is None


def test_set_and_remove_pipe():
    h = AbstractProcessHandler("X", FakePipe())
    q = FakePipe()
    h.set_pipe("a", q)
    assert h.pipe_for("a") is q
    assert set(h.pipes()) == {"parent", "a"}
    h.set_pipe("a", None)
    assert h.pipe_for("a") is None


def test_remove_missing_pipe_raises():
    h = AbstractProcessHandler("X", FakePipe())
    with pytest.raises(KeyError):
        h.set_pipe("zzz", None)


def test_send_command():
    p = FakePipe()
    h = AbstractProcessHandler("X", p)
    h.send_command("parent", "hi", [1])
    assert p.sent == [("hi", [1])]


def test_send_command_no_pipe(capsys):
    h = AbstractProcessHandler("X", FakePipe())
    capsys.readouterr()
    h.send_command("ghost", "hi", None)
    assert "No pipe for ghost" in capsys.readouterr().out


def test_read_pipe_nonblocking_empty():
    h = AbstractProcessHandler("X", FakePipe())
    assert h.read_pipe("parent") == (None, None)


def test_read_pipe_nonblocking_data_updates_last_message(monkeypatch):
    monkeypatch.setattr(mod.time, "time", lambda: 1000.0)
    h = AbstractProcessHandler("X", FakePipe([("c", 1)]))
    assert h._last_message == 1060.0
    monkeypatch.setattr(mod.time, "time", lambda: 2000.0)
    assert h.read_pipe("parent") == ("c", 1)
    assert h._last_message == 2000.0


def test_read_pipe_empty_does_not_update_last_message(monkeypatch):
    monkeypatch.setattr(mod.time, "time", lambda: 1000.0)
    h = AbstractProcessHandler("X", FakePipe())
    monkeypatch.setattr(mod.time, "time", lambda: 2000.0)
    h.read_pipe("parent")
    assert h._last_message == 1060.0


def test_read_pipe_blocking():
    h = AbstractProcessHandler("X", FakePipe([("a", 2)]))
    assert h.read_pipe("parent", blocking=True) == ("a", 2)


def test_read_pipe_eof_removes_pipe(capsys):
    h = AbstractProcessHandler("X", FakePipe(closed=True))
    assert h.read_pipe("parent") == (None, None)
    assert h.pipes() == []
    assert "closed" in capsys.readouterr().out


def test_read_pipe_blocking_eof():
    h = AbstractProcessHandler("X", FakePipe(closed=False))
    assert h.read_pipe("parent", blocking=True) == (None, None)
    assert h.pipes() == []


def test_read_pipe_unknown_raises():
    h = AbstractProcessHandler("X", FakePipe())
    with pytest.raises(AttributeError):
        h.read_pipe("ghost")


def test_flush():
    a = FakePipe([1, 2, 3])
    b = FakePipe([4])
    h = AbstractProcessHandler("X", a)
    h.set_pipe("b", b)
    h.flush()
    assert a.incoming == [] and b.incoming == []


def test_process_command_default_noop():
    h = AbstractProcessHandler("X", FakePipe())
    assert h.process_command("a", "b", None) is None
    assert h.loop() is None
    assert h.quit() is None


def test_internal_quit():
    p = FakePipe([("quit", None)])
    h = Recorder("X", p)
    assert h._process_command("parent") == "quit"
    assert h.quitting is True
    assert p.sent == [("ok", None)]


def test_internal_alive():
    p = FakePipe([("alive", None)])
    h = Recorder("X", p)
    assert h._process_command("parent") is None
    assert p.sent == [("alive", None)]
    assert h.commands == []


def test_internal_custom_command():
    p = FakePipe([("work", {"a": 1})])
    h = Recorder("X", p)
    assert h._process_command("parent") is None
    assert h.commands == [("parent", "work", {"a": 1})]


def test_internal_no_message():
    h = Recorder("X", FakePipe())
    assert h._process_command("parent") is None
    assert h.commands == [(("parent"), None, None)]


def test_internal_connect():
    p = FakePipe()
    child = FakePipe()
    p.incoming = [("connect", ("child", child))]
    h = Recorder("X", p)
    h._process_command("parent")
    assert h.pipe_for("child") is child
    assert ("ok", None) in p.sent


def test_internal_close_last_pipe_quits():
    p = FakePipe([("close", None)])
    h = Recorder("X", p)
    assert h._process_command("parent") == "quit"
    assert p.sent[0] == ("ok", None)
    assert h.pipes() == []


def test_internal_close_with_other_pipes():
    p = FakePipe()
    other = FakePipe([("close", None)])
    h = Recorder("X", p)
    h.set_pipe("other", other)
    assert h._process_command("other") is None
    assert other.sent[0] == ("ok", None)
    assert h.pipes() == ["parent"]


def test_request_connection_ok():
    new = FakePipe()
    p = FakePipe([("ok", new)])
    h = AbstractProcessHandler("X", p)
    h.request_connection("X", "Y")
    assert p.sent == [("connect", ("X", "Y"))]
    assert h.pipe_for("Y") is new


def test_request_connection_failure():
    p = FakePipe([("error", None)])
    h = AbstractProcessHandler("X", p)
    with pytest.raises(RuntimeError):
        h.request_connection("X", "Y")
    assert h.pipe_for("Y") is None


def test_run_quit_immediately(capsys):
    p = FakePipe([("quit", None)])
    h = Recorder("X", p)
    h.run()
    assert h.quit_called
    assert h.quitting
    assert h.pipes() == []
    assert h.loops == 0
    assert p.sent == [("ok", None)]
    assert "Shutting down X..." in capsys.readouterr().out


def test_run_loops_and_dispatches():
    p = FakePipe([("work", 1)])
    h = Recorder("X", p)

    def on_loop(self):
        if self.loops == 2:
            p.incoming.append(("quit", None))

    h.on_loop = on_loop
    h.run()
    assert h.commands[0] == ("parent", "work", 1)
    assert h.loops == 2
    assert h.quit_called


def test_run_sleeps_when_idle(monkeypatch):
    sleeps = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: sleeps.append(s))
    p = FakePipe()
    h = Recorder("X", p)
    h._last_message = mod.time.time() - 100
    h.on_loop = lambda self: p.incoming.append(("quit", None))
    h.run()
    # One sleep before the first iteration, one before the quit is read.
    assert sleeps == [0.5, 0.5]
    assert h.loops == 1


def test_run_no_sleep_when_disabled(monkeypatch):
    sleeps = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: sleeps.append(s))
    p = FakePipe()
    h = Recorder("X", p)
    h.set_sleep(False)
    h._last_message = mod.time.time() - 100
    h.on_loop = lambda self: p.incoming.append(("quit", None))
    h.run()
    assert sleeps == []
