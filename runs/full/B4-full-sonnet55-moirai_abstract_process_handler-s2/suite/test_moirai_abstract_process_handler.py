# tests/test_moirai_abstract_process_handler.py
import pytest

import moirai_abstract_process_handler as mod
from moirai_abstract_process_handler import AbstractProcessHandler


class FakePipe:
    def __init__(self, incoming=None):
        self.incoming = list(incoming or [])
        self.sent = []

    def poll(self):
        return bool(self.incoming)

    def recv(self):
        item = self.incoming.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def send(self, msg):
        self.sent.append(msg)


class Recorder(AbstractProcessHandler):
    def __init__(self, name, pipe):
        super().__init__(name, pipe)
        self.commands = []
        self.loops = 0
        self.on_loop = None
        self.quit_called = False

    def process_command(self, sender, cmd, args):
        self.commands.append((sender, cmd, args))

    def loop(self):
        self.loops += 1
        if self.on_loop:
            self.on_loop(self)

    def quit(self):
        self.quit_called = True


@pytest.fixture
def pipe():
    return FakePipe()


@pytest.fixture
def h(pipe):
    return Recorder("worker", pipe)


def test_init(pipe, capsys):
    h = Recorder("worker", pipe)
    assert "Starting worker..." in capsys.readouterr().out
    assert h.sleep is True
    assert h.quitting is False
    assert h.pipes() == ["parent"]
    assert h.pipe_for("parent") is pipe


def test_set_sleep(h):
    h.set_sleep(False)
    assert h.sleep is False


def test_pipe_for_unknown(h):
    assert h.pipe_for("nobody") is None


def test_set_pipe_and_remove(h):
    p = FakePipe()
    h.set_pipe("a", p)
    assert h.pipe_for("a") is p
    assert set(h.pipes()) == {"parent", "a"}
    h.set_pipe("a", None)
    assert h.pipe_for("a") is None
    assert h.pipes() == ["parent"]


def test_remove_missing_pipe_raises(h):
    with pytest.raises(KeyError):
        h.set_pipe("ghost", None)


def test_pipes_returns_copy(h):
    lst = h.pipes()
    lst.append("x")
    assert h.pipes() == ["parent"]


def test_send_command(h, pipe):
    h.send_command("parent", "hello", (1, 2))
    assert pipe.sent == [("hello", (1, 2))]


def test_send_command_no_pipe(h, capsys):
    capsys.readouterr()
    h.send_command("nobody", "x", None)
    assert "No pipe for nobody" in capsys.readouterr().out


def test_read_pipe_nonblocking_empty(h):
    assert h.read_pipe("parent") == (None, None)


def test_read_pipe_nonblocking_message(h, pipe, monkeypatch):
    monkeypatch.setattr(mod.time, "time", lambda: 1000.0)
    pipe.incoming.append(("cmd", 5))
    assert h.read_pipe("parent") == ("cmd", 5)
    assert h._last_message == 1000.0


def test_read_pipe_blocking(h, pipe):
    pipe.incoming.append(("a", 1))
    assert h.read_pipe("parent", blocking=True) == ("a", 1)


def test_read_pipe_eof_removes_pipe(h, pipe, capsys):
    pipe.incoming.append(EOFError())
    assert h.read_pipe("parent", blocking=True) == (None, None)
    assert h.pipes() == []
    assert "closed" in capsys.readouterr().out


def test_read_pipe_unknown_raises(h):
    with pytest.raises(AttributeError):
        h.read_pipe("nobody")


def test_flush(h, pipe):
    other = FakePipe([("a", 1), ("b", 2)])
    h.set_pipe("o", other)
    pipe.incoming.extend([("x", 1), ("y", 2), ("z", 3)])
    h.flush()
    assert pipe.incoming == []
    assert other.incoming == []


def test_default_hooks_return_none(pipe):
    b = AbstractProcessHandler("b", pipe)
    assert b.process_command("a", "c", None) is None
    assert b.loop() is None
    assert b.quit() is None


def test_process_quit(h, pipe):
    pipe.incoming.append(("quit", None))
    assert h._process_command("parent") == "quit"
    assert h.quitting is True
    assert pipe.sent == [("ok", None)]
    assert h.commands == []


def test_process_alive(h, pipe):
    pipe.incoming.append(("alive", None))
    assert h._process_command("parent") is None
    assert pipe.sent == [("alive", None)]
    assert h.commands == []


def test_process_close_last_pipe_quits(h, pipe):
    pipe.incoming.append(("close", None))
    assert h._process_command("parent") == "quit"
    assert pipe.sent == [("ok", None)]
    assert h.pipes() == []


def test_process_close_with_other_pipes(h, pipe):
    h.set_pipe("o", FakePipe())
    pipe.incoming.append(("close", None))
    result = h._process_command("parent")
    assert result is None
    assert pipe.sent == [("ok", None)]
    assert h.pipes() == ["o"]
    assert h.commands == [("parent", "close", None)]


def test_process_connect(h, pipe):
    child = FakePipe()
    pipe.incoming.append(("connect", ("child", child)))
    assert h._process_command("parent") is None
    assert h.pipe_for("child") is child
    assert ("ok", None) in pipe.sent
    assert h.commands == [("parent", "connect", ("child", child))]


def test_process_other_command_dispatched(h, pipe):
    pipe.incoming.append(("work", [1]))
    assert h._process_command("parent") is None
    assert h.commands == [("parent", "work", [1])]


def test_process_no_message(h):
    assert h._process_command("parent") is None
    assert h.commands == [("parent", None, None)]


def test_request_connection_ok(h, pipe):
    new = FakePipe()
    pipe.incoming.append(("ok", new))
    h.request_connection("me", "you")
    assert pipe.sent == [("connect", ("me", "you"))]
    assert h.pipe_for("you") is new


def test_request_connection_failure(h, pipe):
    pipe.incoming.append(("no", None))
    with pytest.raises(RuntimeError):
        h.request_connection("me", "you")
    assert h.pipe_for("you") is None


def test_run_quit_immediately(h, pipe, capsys):
    pipe.incoming.append(("quit", None))
    h.run()
    assert h.quit_called
    assert h.pipes() == []
    assert h.loops == 0
    assert "Shutting down worker..." in capsys.readouterr().out


def test_run_calls_loop_until_quit(h, pipe):
    def on_loop(self):
        if self.loops == 3:
            pipe.incoming.append(("quit", None))

    h.on_loop = on_loop
    h.run()
    assert h.loops == 3
    assert h.quit_called


def test_run_processes_commands(h, pipe):
    pipe.incoming.extend([("work", 1), ("quit", None)])
    h.run()
    assert h.commands == [("parent", "work", 1)]


def test_run_quit_via_close(h, pipe):
    pipe.incoming.append(("close", None))
    h.run()
    assert h.quit_called
    assert h.pipes() == []


def test_run_sleeps_when_idle(h, pipe, monkeypatch):
    slept = []
    monkeypatch.setattr(mod.time, "time", lambda: 100.0)
    monkeypatch.setattr(mod.time, "sleep", lambda s: slept.append(s))
    h._last_message = 0
    pipe.incoming.append(("quit", None))
    h.run()
    assert slept == [0.5]


def test_run_no_sleep_when_disabled(h, pipe, monkeypatch):
    slept = []
    monkeypatch.setattr(mod.time, "time", lambda: 100.0)
    monkeypatch.setattr(mod.time, "sleep", lambda s: slept.append(s))
    h._last_message = 0
    h.set_sleep(False)
    pipe.incoming.append(("quit", None))
    h.run()
    assert slept == []
