"""Compositor tests — frame compose + diff rendering."""

from __future__ import annotations

import io
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pyte
from pyte.screens import Char

from terminalist.core.pane import Pane, Rect
from terminalist.frontend.compositor import Compositor, EMPTY_CHAR, BORDER_V_CHAR, BORDER_H_CHAR
from terminalist.frontend.split_tree import Direction, Leaf, Split, layout
from terminalist.frontend.vt100_writer import VT100Writer

results: list[tuple[str, bool, str]] = []


def run_test(name, fn):
    try:
        fn()
        print(f"  PASS  {name}")
        results.append((name, True, ""))
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        results.append((name, False, str(e)))
    except Exception as e:
        print(f"  FAIL  {name}: {type(e).__name__}: {e}")
        results.append((name, False, str(e)))


def _make_pane(pane_id: str, cols: int = 20, rows: int = 5, text: str = "") -> Pane:
    """Create a Pane with a real pyte screen (no PTY needed)."""
    screen = pyte.Screen(cols, rows)
    stream = pyte.Stream(screen)
    if text:
        stream.feed(text)
    lock = threading.Lock()

    # Build a pane with real screen but mock backend
    session = MagicMock()
    session.session_id = pane_id
    session._screen = screen
    session._lock = lock
    session._stream = stream
    session.resize = MagicMock()

    p = Pane.__new__(Pane)
    p.pane_id = pane_id
    p.session = session
    p.rect = Rect(0, 0, cols, rows)
    p.focused = False
    p._copy_mode = False
    p._scroll_offset = 0
    return p


def _capture_compositor(w: int, h: int) -> tuple[Compositor, list[str]]:
    """Create compositor with captured output."""
    output: list[str] = []
    writer = VT100Writer()
    # Patch flush to capture
    orig_buf = writer._buf

    def patched_flush():
        data = "".join(writer._buf)
        writer._buf.clear()
        output.append(data)

    writer.flush = patched_flush
    comp = Compositor(w, h, writer)
    return comp, output


# ══════════════════════════════════════════════
#  Compose tests
# ══════════════════════════════════════════════

def test_compose_single_pane():
    """Single pane fills the frame."""
    pane = _make_pane("a", cols=10, rows=3, text="hello")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 10, 3))

    comp, _ = _capture_compositor(10, 3)
    frame = comp.compose(root, Rect(0, 0, 10, 3))

    assert frame[0][0].data == "h"
    assert frame[0][4].data == "o"
    assert frame[0][5].data == " "  # empty after text


def test_compose_two_panes_vertical():
    """Two panes with vertical split + border."""
    a = _make_pane("a", cols=39, rows=5, text="LEFT")
    b = _make_pane("b", cols=40, rows=5, text="RIGHT")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 5))

    comp, _ = _capture_compositor(80, 5)
    frame = comp.compose(root, Rect(0, 0, 80, 5))

    # Left pane content
    assert frame[0][0].data == "L"
    # Border at x=39
    assert frame[0][39].data == "│", f"Got {frame[0][39].data!r}"
    # Right pane content
    assert frame[0][40].data == "R"


def test_compose_two_panes_horizontal():
    """Two panes with horizontal split + border."""
    a = _make_pane("a", cols=20, rows=11, text="TOP")
    b = _make_pane("b", cols=20, rows=12, text="BOT")
    root = Split(Direction.HORIZONTAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 20, 24))

    comp, _ = _capture_compositor(20, 24)
    frame = comp.compose(root, Rect(0, 0, 20, 24))

    assert frame[0][0].data == "T"
    # Border row
    border_y = a.rect.h
    assert frame[border_y][0].data == "─", f"Got {frame[border_y][0].data!r} at y={border_y}"
    # Bottom pane
    assert frame[border_y + 1][0].data == "B"


def test_compose_empty_frame():
    """Frame with no content is all EMPTY_CHAR."""
    pane = _make_pane("a", cols=5, rows=3)
    root = Leaf(pane)
    layout(root, Rect(0, 0, 5, 3))

    comp, _ = _capture_compositor(5, 3)
    frame = comp.compose(root, Rect(0, 0, 5, 3))

    for row in frame:
        for cell in row:
            assert cell.data == " "


# ══════════════════════════════════════════════
#  Render + diff tests
# ══════════════════════════════════════════════

def test_render_initial():
    """First render writes all cells (no prev_frame)."""
    pane = _make_pane("a", cols=5, rows=2, text="AB")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 5, 2))

    comp, output = _capture_compositor(5, 2)
    comp.render(root, Rect(0, 0, 5, 2))

    assert len(output) == 1
    assert "A" in output[0]
    assert "B" in output[0]


def test_render_no_change():
    """Second render with no changes writes minimal output."""
    pane = _make_pane("a", cols=5, rows=2, text="AB")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 5, 2))

    comp, output = _capture_compositor(5, 2)
    comp.render(root, Rect(0, 0, 5, 2))  # initial
    comp._dirty = True
    comp.render(root, Rect(0, 0, 5, 2))  # second

    # Second render output should be much smaller (only cursor + hide/show)
    assert len(output) == 2
    # No cell characters in second render (just cursor commands)
    second = output[1]
    assert "A" not in second and "B" not in second


def test_render_one_cell_change():
    """After modifying one cell, only that cell is emitted."""
    pane = _make_pane("a", cols=10, rows=2, text="ABCDE")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 10, 2))

    comp, output = _capture_compositor(10, 2)
    comp.render(root, Rect(0, 0, 10, 2))  # initial

    # Modify one cell
    pane.session._stream.feed("\x1b[1;3HX")  # move to col 3 row 1, write X

    comp._dirty = True
    comp.render(root, Rect(0, 0, 10, 2))  # diff render

    second = output[1]
    assert "X" in second, "Changed cell should be in output"


def test_render_marks_not_dirty():
    """After render, needs_render() returns False."""
    pane = _make_pane("a", cols=5, rows=2)
    root = Leaf(pane)
    layout(root, Rect(0, 0, 5, 2))

    comp, _ = _capture_compositor(5, 2)
    comp.render(root, Rect(0, 0, 5, 2))
    assert not comp.needs_render()


def test_mark_dirty():
    comp, _ = _capture_compositor(10, 5)
    comp._dirty = False
    comp.mark_dirty()
    assert comp.needs_render()


def test_resize_invalidates():
    comp, _ = _capture_compositor(10, 5)
    comp._prev_frame = [[EMPTY_CHAR] * 10 for _ in range(5)]
    comp._dirty = False
    comp.resize(20, 10)
    assert comp._prev_frame is None
    assert comp.needs_render()


def test_full_redraw():
    comp, _ = _capture_compositor(10, 5)
    comp._prev_frame = [[EMPTY_CHAR] * 10 for _ in range(5)]
    comp._dirty = False
    comp.full_redraw()
    assert comp._prev_frame is None
    assert comp.needs_render()


def test_cjk_in_compose():
    """CJK wide chars in pane are composed correctly."""
    pane = _make_pane("a", cols=10, rows=2, text="한글")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 10, 2))

    comp, _ = _capture_compositor(10, 2)
    frame = comp.compose(root, Rect(0, 0, 10, 2))

    assert frame[0][0].data == "한"
    assert frame[0][1].data == ""   # stub
    assert frame[0][2].data == "글"
    assert frame[0][3].data == ""   # stub


def test_render_skips_cjk_stubs():
    """CJK stub cells (data='') should not be emitted in VT100 output."""
    pane = _make_pane("a", cols=10, rows=1, text="한")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 10, 1))

    comp, output = _capture_compositor(10, 1)
    comp.render(root, Rect(0, 0, 10, 1))

    rendered = output[0]
    assert "한" in rendered
    # Stub cell should not produce an extra character
    # Count occurrences of the Korean char — should be exactly 1
    assert rendered.count("한") == 1


# ══════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Compositor Tests")
    print("=" * 60)

    print("\n── Compose ──")
    run_test("compose_single_pane", test_compose_single_pane)
    run_test("compose_two_panes_vertical", test_compose_two_panes_vertical)
    run_test("compose_two_panes_horizontal", test_compose_two_panes_horizontal)
    run_test("compose_empty_frame", test_compose_empty_frame)
    run_test("cjk_in_compose", test_cjk_in_compose)

    print("\n── Render + Diff ──")
    run_test("render_initial", test_render_initial)
    run_test("render_no_change", test_render_no_change)
    run_test("render_one_cell_change", test_render_one_cell_change)
    run_test("render_marks_not_dirty", test_render_marks_not_dirty)
    run_test("render_skips_cjk_stubs", test_render_skips_cjk_stubs)

    print("\n── State ──")
    run_test("mark_dirty", test_mark_dirty)
    run_test("resize_invalidates", test_resize_invalidates)
    run_test("full_redraw", test_full_redraw)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed, {len(results)} total")
    print("=" * 60)
    if failed:
        for name, ok, detail in results:
            if not ok:
                print(f"  FAIL  {name}: {detail}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
