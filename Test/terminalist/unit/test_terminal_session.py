from pathlib import Path
import threading
import time

from pyte.screens import Char

from terminalist.core.terminal_session import TerminalSession
from terminalist.core.terminal_session import SessionState


def _session(cols: int = 10, rows: int = 3) -> TerminalSession:
    return TerminalSession("s", ["cmd"], Path("."), cols=cols, rows=rows)


def _feed(session: TerminalSession, text: str) -> None:
    with session._lock:
        session._stream.feed(text)


class _FakeBackend:
    def __init__(self) -> None:
        self.pid = 1

    def spawn(self, *_args, **_kwargs) -> None:
        return None

    def is_alive(self) -> bool:
        return False

    def write(self, _data: str) -> None:
        return None

    def terminate(self) -> None:
        return None

    def set_size(self, _rows: int, _cols: int) -> None:
        return None

    def read(self, _size: int) -> str:
        raise EOFError


def test_get_scrollback_lines_combines_history_and_visible_rows():
    session = _session(rows=3)
    _feed(session, "L1\r\nL2\r\nL3\r\nL4")

    assert session.get_scrollback_lines() == ["L1", "L2", "L3", "L4"]


def test_get_scrollback_lines_handles_sparse_rows():
    session = _session(cols=8, rows=2)
    with session._lock:
        row = session._screen.buffer[0]
        row[3] = Char("x", "default", "default", False, False, False, False, False, False)

    lines = session.get_scrollback_lines()

    assert lines[0] == "   x"


def test_get_scrollback_lines_skips_cjk_stub_cells():
    session = _session(cols=8, rows=2)
    _feed(session, "한글")

    lines = session.get_scrollback_lines()

    assert lines[0] == "한글"


def test_get_scrollback_lines_survives_materialized_empty_rows():
    session = _session(cols=8, rows=3)
    with session._lock:
        _ = [session._screen.buffer[y] for y in range(session._screen.lines)]
        session._stream.feed("alpha\r\nbeta")

    lines = session.get_scrollback_lines()

    assert lines == ["alpha", "beta", ""]


def test_dirty_notifications_are_coalesced_within_debounce_window():
    session = _session()
    session._dirty_flush_delay_s = 0.01
    called = threading.Event()
    count = 0
    count_lock = threading.Lock()

    def listener() -> None:
        nonlocal count
        with count_lock:
            count += 1
        called.set()

    session.add_dirty_listener(listener)

    session._dirty_rows.add(1)
    session._schedule_dirty_flush()
    time.sleep(0.002)
    session._dirty_rows.add(2)
    session._schedule_dirty_flush()

    assert called.wait(0.2)
    assert count == 1


def test_dirty_notifications_fire_again_after_debounce_window():
    session = _session()
    session._dirty_flush_delay_s = 0.005
    first = threading.Event()
    second = threading.Event()
    count = 0
    count_lock = threading.Lock()

    def listener() -> None:
        nonlocal count
        with count_lock:
            count += 1
            if count == 1:
                first.set()
            elif count == 2:
                second.set()

    session.add_dirty_listener(listener)

    session._dirty_rows.add(1)
    session._schedule_dirty_flush()
    assert first.wait(0.2)

    session._dirty_rows.add(3)
    session._schedule_dirty_flush()
    assert second.wait(0.2)
    assert count == 2


def test_dirty_rows_are_preserved_until_coalesced_flush():
    session = _session()
    session._dirty_flush_delay_s = 1.0
    session.add_dirty_listener(lambda: None)

    session._dirty_rows.add(1)
    session._schedule_dirty_flush()
    session._dirty_rows.add(4)
    session._schedule_dirty_flush()

    assert session._dirty_rows == {1, 4}
    session._cancel_dirty_flush()


def test_spawn_sets_starting_before_reader_thread_starts(monkeypatch):
    session = TerminalSession("s", ["cmd"], Path("."), backend=_FakeBackend())
    seen: list[SessionState] = []

    class FakeThread:
        def __init__(self, *, target, daemon):
            self.target = target
            self.daemon = daemon

        def start(self) -> None:
            seen.append(session.state)

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr("terminalist.core.terminal_session.threading.Thread", FakeThread)

    session.spawn()

    assert seen == [SessionState.STARTING]
