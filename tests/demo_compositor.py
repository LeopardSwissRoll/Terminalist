"""Visual demo — Phase 1~3 compositor rendering.

Renders split panes to the actual terminal using pyte screens
(no PTY needed). Press any key to cycle through layouts.

Usage:
    python tests/demo_compositor.py [--debug]

What to verify:
  1. Two panes side-by-side with │ border between them
  2. Korean text renders correctly (no spacing issues)
  3. Colors and bold text preserved across panes
  4. Horizontal split with ─ border
  5. 3-pane nested layout (vertical + horizontal)
  6. Diff rendering: only changed cells update (watch the counter)
  7. Resize: shrink/expand terminal window during demo
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pyte
from pyte.screens import Char

from terminalist.debug import init_debug, log
from terminalist.core.pane import Pane, Rect
from terminalist.frontend.split_tree import Direction, Leaf, Split, layout, all_panes
from terminalist.frontend.compositor import Compositor
from terminalist.frontend.vt100_writer import VT100Writer


def _make_pane(pane_id: str, cols: int, rows: int) -> Pane:
    """Create a Pane with real pyte screen (no PTY)."""
    screen = pyte.Screen(cols, rows)
    stream = pyte.Stream(screen)
    lock = threading.Lock()

    class FakeSession:
        def __init__(self):
            self.session_id = pane_id
            self._screen = screen
            self._stream = stream
            self._lock = lock
        def resize(self, cols, rows):
            with self._lock:
                self._screen.resize(rows, cols)
            log("demo", f"[{pane_id}] resized to {cols}x{rows}")

    session = FakeSession()
    p = Pane.__new__(Pane)
    p.pane_id = pane_id
    p.session = session
    p.rect = Rect(0, 0, cols, rows)
    p.focused = False
    p._copy_mode = False
    p._scroll_offset = 0
    return p


def _feed(pane: Pane, text: str) -> None:
    """Feed VT100 text into pane's pyte screen."""
    with pane.session._lock:
        pane.session._stream.feed(text)


def _terminal_size() -> tuple[int, int]:
    cols, rows = os.get_terminal_size()
    return max(cols, 20), max(rows, 5)


def _enter_alt():
    sys.stdout.write("\x1b[?1049h\x1b[H\x1b[2J")
    sys.stdout.flush()


def _exit_alt():
    sys.stdout.write("\x1b[?1049l")
    sys.stdout.flush()


def _wait_key():
    """Wait for a keypress (Windows)."""
    import msvcrt
    msvcrt.getwch()


def run_demo(debug: bool = False) -> None:
    init_debug(enabled=debug, log_path="terminalist_debug_demo.log", env_tag="demo")
    log("demo", "=== Compositor visual demo starting ===")

    cols, rows = _terminal_size()
    log("demo", f"Terminal: {cols}x{rows}")

    writer = VT100Writer()
    compositor = Compositor(cols, rows, writer)

    _enter_alt()

    try:
        # ════════════════════════════════════════
        #  Demo 1: Vertical split (2 panes)
        # ════════════════════════════════════════
        a = _make_pane("left", cols, rows)
        b = _make_pane("right", cols, rows)
        root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
        layout(root, Rect(0, 0, cols, rows))

        _feed(a, "\x1b[33m")  # yellow
        _feed(a, "═══ LEFT PANE ═══\r\n")
        _feed(a, "\x1b[0m")
        _feed(a, "English text works.\r\n")
        _feed(a, "\x1b[36m한글 테스트\x1b[0m — Korean OK?\r\n")
        _feed(a, "\x1b[1;31mBold Red\x1b[0m / \x1b[32mGreen\x1b[0m / \x1b[34mBlue\x1b[0m\r\n")
        _feed(a, f"\r\nPane rect: {a.rect}")

        _feed(b, "\x1b[35m")  # magenta
        _feed(b, "═══ RIGHT PANE ═══\r\n")
        _feed(b, "\x1b[0m")
        _feed(b, "This is the right side.\r\n")
        _feed(b, "混合テスト — CJK mixed.\r\n")
        _feed(b, "\x1b[7mReverse video\x1b[0m\r\n")
        _feed(b, f"\r\nPane rect: {b.rect}")

        compositor.render(root, Rect(0, 0, cols, rows), focused_pane=a)
        log("demo", "Demo 1: Vertical split rendered")

        # Status line at bottom
        sys.stdout.write(f"\x1b[{rows};1H\x1b[7m Demo 1/4: Vertical split │ Press any key \x1b[0m")
        sys.stdout.flush()
        _wait_key()

        # ════════════════════════════════════════
        #  Demo 2: Horizontal split (2 panes)
        # ════════════════════════════════════════
        compositor.full_redraw()

        c = _make_pane("top", cols, rows)
        d = _make_pane("bottom", cols, rows)
        root2 = Split(Direction.HORIZONTAL, 0.5, Leaf(c), Leaf(d))
        layout(root2, Rect(0, 0, cols, rows))

        _feed(c, "\x1b[33m═══ TOP PANE ═══\x1b[0m\r\n")
        _feed(c, "Above the horizontal border.\r\n")
        _feed(c, f"Rect: {c.rect}")

        _feed(d, "\x1b[36m═══ BOTTOM PANE ═══\x1b[0m\r\n")
        _feed(d, "Below the horizontal border.\r\n")
        _feed(d, f"Rect: {d.rect}")

        compositor.render(root2, Rect(0, 0, cols, rows), focused_pane=c)
        log("demo", "Demo 2: Horizontal split rendered")

        sys.stdout.write(f"\x1b[{rows};1H\x1b[7m Demo 2/4: Horizontal split │ Press any key \x1b[0m")
        sys.stdout.flush()
        _wait_key()

        # ════════════════════════════════════════
        #  Demo 3: Nested 3-pane layout
        # ════════════════════════════════════════
        compositor.full_redraw()

        e = _make_pane("main", cols, rows)
        f = _make_pane("top-right", cols, rows)
        g = _make_pane("bot-right", cols, rows)
        root3 = Split(
            Direction.VERTICAL, 0.6,
            Leaf(e),
            Split(Direction.HORIZONTAL, 0.5, Leaf(f), Leaf(g)),
        )
        layout(root3, Rect(0, 0, cols, rows))

        _feed(e, "\x1b[33m═══ MAIN (60%) ═══\x1b[0m\r\n")
        _feed(e, "This is the main editing area.\r\n")
        _feed(e, "It gets 60% of the width.\r\n")
        _feed(e, "\x1b[36m한글 + English + 日本語\x1b[0m\r\n")
        for i in range(1, 8):
            _feed(e, f"  Line {i}\r\n")
        _feed(e, f"\r\nRect: {e.rect}")

        _feed(f, "\x1b[35m═ TOP RIGHT ═\x1b[0m\r\n")
        _feed(f, "Claude output\r\n")
        _feed(f, f"Rect: {f.rect}")

        _feed(g, "\x1b[32m═ BOT RIGHT ═\x1b[0m\r\n")
        _feed(g, "Shell session\r\n")
        _feed(g, f"Rect: {g.rect}")

        compositor.render(root3, Rect(0, 0, cols, rows), focused_pane=e)
        log("demo", "Demo 3: Nested 3-pane rendered")

        sys.stdout.write(f"\x1b[{rows};1H\x1b[7m Demo 3/4: Nested 3-pane │ Press any key \x1b[0m")
        sys.stdout.flush()
        _wait_key()

        # ════════════════════════════════════════
        #  Demo 4: Diff rendering (live counter)
        # ════════════════════════════════════════
        compositor.full_redraw()

        h = _make_pane("counter", cols, rows)
        j = _make_pane("static", cols, rows)
        root4 = Split(Direction.VERTICAL, 0.5, Leaf(h), Leaf(j))
        layout(root4, Rect(0, 0, cols, rows))

        _feed(j, "\x1b[33m═══ STATIC ═══\x1b[0m\r\n")
        _feed(j, "This pane doesn't change.\r\n")
        _feed(j, "Watch the left pane counter.\r\n")
        _feed(j, "Only changed cells are re-rendered\r\n")
        _feed(j, "(diff rendering optimization).\r\n")

        _feed(h, "\x1b[36m═══ LIVE COUNTER ═══\x1b[0m\r\n\r\n")

        # Initial render
        compositor.render(root4, Rect(0, 0, cols, rows), focused_pane=h)

        for tick in range(30):
            # Update counter pane only
            with h.session._lock:
                h.session._screen.cursor_position(2, 0)  # row 3
                h.session._stream.feed(f"\x1b[1;32m  Counter: {tick:04d}\x1b[0m   ({time.strftime('%H:%M:%S')})")

            compositor._dirty = True
            compositor.render(root4, Rect(0, 0, cols, rows), focused_pane=h)

            sys.stdout.write(f"\x1b[{rows};1H\x1b[7m Demo 4/4: Diff render (tick {tick}/29) │ Wait... \x1b[0m")
            sys.stdout.flush()
            time.sleep(0.15)

        log("demo", "Demo 4: Diff rendering complete")

        sys.stdout.write(f"\x1b[{rows};1H\x1b[7m All demos done! Press any key to exit. \x1b[0m")
        sys.stdout.flush()
        _wait_key()

    finally:
        _exit_alt()
        log("demo", "=== Demo ended ===")
        print("[demo] Done. Check terminalist_debug_demo.log for render stats.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    run_demo(debug=args.debug)
