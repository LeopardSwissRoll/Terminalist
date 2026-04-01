"""Shared test fixtures for Terminalist.

Consolidates helper patterns from individual test files.
All fixtures reuse terminalist.* imports (no logic duplication).
"""

from __future__ import annotations

import threading
from pathlib import Path

# ── Exclude standalone/manual-only files from default pytest collection ──
collect_ignore = [
    "terminalist/integration/test_io.py",
    "terminalist/integration/test_handler_integration.py",
]
from unittest.mock import MagicMock

import pyte
from pyte.screens import Char

from terminalist.core.pane import Pane, Rect
from terminalist.core.terminal_session import _viewport_rows
from terminalist.frontend.compositor import Compositor
from terminalist.frontend.vt100_writer import VT100Writer
from terminalist.pyte_patch import PreservingScreen, apply as patch_pyte


# ── pyte patch (once per process) ──

_pyte_patched = False


def _ensure_pyte_patched():
    global _pyte_patched
    if not _pyte_patched:
        patch_pyte()
        _pyte_patched = True


_ensure_pyte_patched()


# ── FakeSession ──


class FakeSession:
    """Lightweight session for testing. Real pyte screen, no PTY.

    Matches TerminalSession's interface for the properties that
    Compositor/Pane access: session_id, _screen, _stream, _lock, resize().
    """

    def __init__(self, session_id: str, cols: int, rows: int) -> None:
        self.session_id = session_id
        self._screen = PreservingScreen(cols, rows, history=100)
        self._stream = pyte.Stream(self._screen)
        self._lock = threading.Lock()
        self._dirty_listeners: list = []
        self._raw_output_listeners: list = []

    def resize(self, cols: int, rows: int) -> None:
        with self._lock:
            self._screen.resize(rows, cols)

    def is_alive(self) -> bool:
        return True

    def get_cursor_position(self) -> tuple[int, int]:
        return (self._screen.cursor.x, self._screen.cursor.y)

    def get_screen_snapshot(self, scroll_offset: int = 0) -> tuple[list, int, int, int, int]:
        from pyte.screens import Char as _Char
        EMPTY = _Char(" ", "default", "default", False, False, False, False, False, False)
        with self._lock:
            rows = self._screen.lines
            cols = self._screen.columns
            history_top = list(getattr(getattr(self._screen, "history", None), "top", ()))
            visible_rows = [self._screen.buffer[y] for y in range(rows)]
            viewport_rows, cx, cy = _viewport_rows(
                history_top,
                visible_rows,
                rows,
                self._screen.cursor.x,
                self._screen.cursor.y,
                scroll_offset,
            )
            grid = [
                [
                    viewport_rows[y][x] if x in viewport_rows[y] else EMPTY
                    for x in range(cols)
                ]
                for y in range(rows)
            ]
            return grid, cx, cy, cols, rows

    def get_max_scroll_offset(self) -> int:
        with self._lock:
            return len(getattr(getattr(self._screen, "history", None), "top", ()))

    def add_raw_output_listener(self, cb) -> None:
        self._raw_output_listeners.append(cb)

    def add_dirty_listener(self, cb) -> None:
        self._dirty_listeners.append(cb)

    def remove_dirty_listener(self, cb) -> None:
        try:
            self._dirty_listeners.remove(cb)
        except ValueError:
            pass

    def emit_dirty(self) -> None:
        for cb in list(self._dirty_listeners):
            cb()

    def enter_manual(self) -> None:
        pass

    def exit_manual(self) -> None:
        pass


# ── Factory functions ──


def make_pane(pane_id: str, cols: int = 20, rows: int = 5, text: str = "") -> Pane:
    """Create a Pane with a real pyte screen (no PTY needed).

    Uses FakeSession instead of MagicMock for Phase 4 compatibility.
    """
    session = FakeSession(pane_id, cols, rows)
    if text:
        with session._lock:
            session._stream.feed(text)

    p = Pane.__new__(Pane)
    p.pane_id = pane_id
    p.session = session
    p.frame_rect = Rect(0, 0, cols, rows)
    p.content_rect = Rect(0, 0, cols, rows)
    p.focused = False
    p._copy_mode = False
    p._scroll_offset = 0
    return p


def mock_pane(pane_id: str, cols: int = 80, rows: int = 24) -> Pane:
    """Create a Pane with a mock session (layout testing only, no screen content)."""
    session = MagicMock()
    session.session_id = pane_id
    session._screen = MagicMock()
    session._screen.columns = cols
    session._screen.lines = rows

    p = Pane.__new__(Pane)
    p.pane_id = pane_id
    p.session = session
    p.frame_rect = Rect(0, 0, cols, rows)
    p.content_rect = Rect(0, 0, cols, rows)
    p.focused = False
    p._copy_mode = False
    p._scroll_offset = 0
    return p


def feed_pane(pane: Pane, text: str) -> None:
    """Feed VT100 text to pane's pyte screen under lock."""
    with pane.session._lock:
        pane.session._stream.feed(text)


def capture_compositor(
    w: int,
    h: int,
    *,
    show_root_border: bool = False,
) -> tuple[Compositor, list[str]]:
    """Create Compositor with captured VT100 output.

    Returns (compositor, output_list). Each flush() appends to output_list.
    """
    output: list[str] = []
    writer = VT100Writer()

    def patched_flush():
        data = "".join(writer._buf)
        writer._buf.clear()
        output.append(data)

    writer.flush = patched_flush
    comp = Compositor(w, h, writer, show_root_border=show_root_border)
    return comp, output


def make_screen(
    cols: int = 20, rows: int = 5,
) -> tuple[pyte.Screen, pyte.Stream, threading.Lock]:
    """Create a pyte Screen + Stream + Lock (for screen_sync tests)."""
    s = pyte.Screen(cols, rows)
    st = pyte.Stream(s)
    lock = threading.Lock()
    return s, st, lock


# Char factory for concise test assertions
C = lambda data, fg="default", bg="default", **kw: Char(
    data, fg, bg,
    kw.get("bold", False), kw.get("italics", False),
    kw.get("underscore", False), kw.get("strikethrough", False),
    kw.get("reverse", False), kw.get("blink", False),
)
