"""Shared test fixtures for Terminalist.

Consolidates helper patterns from individual test files.
All fixtures reuse terminalist.* imports (no logic duplication).
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

import pyte
from pyte.screens import Char

from terminalist.core.pane import Pane, Rect
from terminalist.frontend.compositor import Compositor
from terminalist.frontend.vt100_writer import VT100Writer
from terminalist.pyte_patch import apply as patch_pyte


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
        self._screen = pyte.Screen(cols, rows)
        self._stream = pyte.Stream(self._screen)
        self._lock = threading.Lock()

    def resize(self, cols: int, rows: int) -> None:
        with self._lock:
            self._screen.resize(rows, cols)

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
    p.rect = Rect(0, 0, cols, rows)
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
    p.rect = Rect(0, 0, cols, rows)
    p.focused = False
    p._copy_mode = False
    p._scroll_offset = 0
    return p


def feed_pane(pane: Pane, text: str) -> None:
    """Feed VT100 text to pane's pyte screen under lock."""
    with pane.session._lock:
        pane.session._stream.feed(text)


def capture_compositor(w: int, h: int) -> tuple[Compositor, list[str]]:
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
    comp = Compositor(w, h, writer)
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
