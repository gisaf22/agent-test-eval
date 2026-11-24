# tests/test_moirai_abstract_process_handler.py
import time

import pytest

import moirai_abstract_process_handler as m
from moirai_abstract_process_handler import AbstractProcessHandler


class FakePipe:
    def __init__(self, incoming=()):
        self.incoming = list(incoming)
        self.sent = []

    def poll(self):
        return bool(self.incoming)

    def recv(self):
        if not self.incoming:
            raise EOFError
        item = self.incoming.pop(0)
        if isinstance(item, EOFError):
            raise item
        return item

    def send(self, msg):
        self.sent.append(msg)


class Recorder(AbstractProcessHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.commands = []
        self.loops = 0
        self.quit_called = False

    def process_command(self, sender, cmd, args):
        self.commands.append((sender, cmd, args))

    def loop(self):
        self.loops += 1

    def quit(self):
        self.quit_called = True


def make(incoming=()):
    p = FakePipe(incoming)
    return Recorder("test", p), p


def test_init_state(capsys):
    h, p = make()
    assert "Starting test..." in capsys.readouterr().out
    assert h.sleep is True
    assert h.quitting is False
    assert h.pipe_for("parent") is p
    assert h.pipes() == ["parent"]
    assert h._last_message > time.time() + 50


def test_set_sleep():
    h, _ = make()
    h.set_sleep(False)
    assert h.sleep is False


def test_pipe_for_unknown():
    h, _ = make()
    assert h.pipe_for("x") is None


def test_set_pipe_add_and_remove():
    h, _ = make()
    q = FakePipe()
    h.set_pipe("a", q)
    assert h.pipe_for("a") is q
    assert set(h.pipes()) == {"parent", "a"}
    h.set_pipe("a", None)
    assert h.pipe_for("a") is None


def test_set_pipe_remove_missing_raises():
    h, _ = make()
    with pytest.raises(KeyError):
        h.set_pipe("nope", None)


def test_pipes_returns_copy():
    h, _ = make()
    lst = h.pipes()
    lst.append("z")
    assert h.pipes() == ["parent"]


def test_send_command():
    h, p = make()
    h.send_command("parent", "hi", [1])
    assert p.sent == [("hi", [1])]


def test_send_command_no_pipe(capsys):
    h, _ = make()
    capsys.readouterr()
    h.send_command("ghost", "hi", None)
    assert "No pipe for ghost" in capsys.readouterr().out


def test_read_pipe_nonblocking_empty():
    h, _ = make()
    assert h.read_pipe("parent") == (None, None)


def test_read_pipe_nonblocking_message_updates_time():
    h, _ = make([("a", 1)])
    before = h._last_message
    assert h.read_pipe("parent") == ("a", 1)
    assert h._last_message < before


def test_read_pipe_blocking():
    h, _ = make([("a", 1)])
    assert h.read_pipe("parent", blocking=True) == ("a", 1)


def test_read_pipe_eof_removes_pipe(capsys):
    h, _ = make()
    assert h.read_pipe("parent", blocking=True) == (None, None)
    assert h.pipes() == []
    assert "closed" in capsys.readouterr().out


def test_read_pipe_unknown_nonblocking_raises():
    h, _ = make()
    with pytest.raises(AttributeError):
        h.read_pipe("ghost")


def test_flush():
    h, p = make([1, 2, 3])
    q = FakePipe([4, 5])
    h.set_pipe("a", q)
    h.flush()
    assert p.incoming == [] and q.incoming == []


def test_base_hooks_noop():
    b = AbstractProcessHandler("b", FakePipe())
    assert b.process_command("x", "y", None) is None
    assert b.loop() is None
    assert b.quit() is None


def test_process_quit():
    h, p = make([("quit", None)])
    assert h._process_command("parent") == "quit"
    assert h.quitting is True
    assert p.sent == [("ok", None)]
    assert h.commands == []


def test_process_close_last_pipe():
    h, p = make([("close", None)])
    assert h._process_command("parent") == "quit"
    assert p.sent == [("ok", None)]
    assert h.pipes() == []


def test_process_close_with_other_pipes():
    h, p = make([("close", None)])
    h.set_pipe("a", FakePipe())
    assert h._process_command("parent") is None
    assert p.sent == [("ok", None)]
    assert h.pipes() == ["a"]
    assert h.commands == [("parent", "close", None)]


def test_process_connect():
    h, p = make([("connect", ("peer", FakePipe()))])
    newp = p.incoming[0][1][1]
    assert h._process_command("parent") is None
    assert h.pipe_for("peer") is newp
    assert p.sent == [("ok", None)]


def test_process_alive():
    h, p = make([("alive", None)])
    assert h._process_command("parent") is None
    assert p.sent == [("alive", None)]
    assert h.commands == []


def test_process_custom_command():
    h, p = make([("work", 42)])
    assert h._process_command("parent") is None
    assert h.commands == [("parent", "work", 42)]
    assert p.sent == []


def test_process_no_message_dispatches_none():
    h, _ = make()
    assert h._process_command("parent") is None
    assert h.commands == [("parent", None, None)]


def test_request_connection_ok():
    newp = FakePipe()
    h, p = make([("ok", newp)])
    h.request_connection("me", "you")
    assert p.sent == [("connect", ("me", "you"))]
    assert h.pipe_for("you") is newp


def test_request_connection_fail():
    h, _ = make([("no", None)])
    with pytest.raises(RuntimeError, match="Can not connect me with you"):
        h.request_connection("me", "you")
    assert h.pipe_for("you") is None


def test_run_quit(capsys):
    h, p = make([("work", 1), ("quit", None)])
    h.set_sleep(False)
    h.set_pipe("other", FakePipe())
    h.run()
    assert h.quit_called
    assert h.pipes() == []
    assert h.commands[0] == ("parent", "work", 1)
    assert h.loops == 1
    assert "Shutting down test..." in capsys.readouterr().out


def test_run_close_only_pipe():
    h, p = make([("close", None)])
    h.set_sleep(False)
    h.run()
    assert h.quit_called
    assert h.loops == 0


def test_run_sleeps_when_idle(monkeypatch):
    h, p = make([("quit", None)])
    h._last_message = time.time() - 10
    slept = []
    monkeypatch.setattr(m.time, "sleep", lambda s: slept.append(s))
    h.run()
    assert slept == [0.5]


def test_run_no_sleep_when_disabled(monkeypatch):
    h, p = make([("quit", None)])
    h._last_message = time.time() - 10
    h.set_sleep(False)
    slept = []
    monkeypatch.setattr(m.time, "sleep", lambda s: slept.append(s))
    h.run()
    assert slept == []
