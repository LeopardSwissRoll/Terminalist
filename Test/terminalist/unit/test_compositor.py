"""Compositor tests — internal state + diff optimization.

Composition correctness and full pipeline are covered by test_roundtrip.py.
These tests focus on compositor-specific internals that roundtrip can't catch:
- diff rendering optimization (no-change → minimal output)
- initial vs subsequent render behavior
- dirty flag management
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pyte.screens import Char

from terminalist.core.copy_mode import handle_named_key, handle_text_input
from terminalist.core.pane import Rect
from terminalist.frontend.compositor import EMPTY_CHAR
from terminalist.frontend.split_tree import Leaf, layout

from Test.conftest import make_pane as _make_pane, capture_compositor as _capture_compositor, feed_pane

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

    assert len(output) == 2
    second = output[1]
    assert "A" not in second and "B" not in second


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


def test_root_border_option_draws_outer_box():
    pane = _make_pane("a", cols=5, rows=2, text="AB")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 5, 2))

    comp, _ = _capture_compositor(5, 2, show_root_border=True)
    frame = comp.compose(root, Rect(0, 0, 5, 2), focused_pane=pane)

    assert frame[0][0].data == "┌"
    assert frame[0][4].data == "┐"
    assert frame[1][0].data == "└"
    assert frame[1][4].data == "┘"


def test_render_status_line_overlays_last_row():
    pane = _make_pane("a", cols=5, rows=2, text="AB")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 5, 2))

    comp, _ = _capture_compositor(5, 3)
    frame = comp.compose(root, Rect(0, 0, 5, 2))
    status = [
        Char("[", "white", "bright_black", False, False, False, False, False, False),
        Char("*", "bright_white", "bright_black", True, False, False, False, False, False),
        Char("]", "white", "bright_black", False, False, False, False, False, False),
        Char(" ", "white", "bright_black", False, False, False, False, False, False),
        Char(" ", "white", "bright_black", False, False, False, False, False, False),
    ]

    comp.render_status_line(status, 2, frame)

    assert frame[2][0].data == "["
    assert frame[2][1].data == "*"
    assert frame[2][1].fg == "bright_white"
    assert frame[2][1].bg == "bright_black"


def test_compose_uses_scrollback_viewport():
    pane = _make_pane("a", cols=10, rows=3)
    for i in range(1, 7):
        feed_pane(pane, f"L{i}\r\n")
    assert pane.scroll_up(2) is True

    root = Leaf(pane)
    layout(root, Rect(0, 0, 10, 3))

    comp, _ = _capture_compositor(10, 3)
    frame = comp.compose(root, Rect(0, 0, 10, 3), focused_pane=pane)
    lines = ["".join(cell.data or " " for cell in row) for row in frame]

    assert lines[0].startswith("L3"), lines
    assert lines[1].startswith("L4"), lines
    assert lines[2].startswith("L5"), lines


def test_compose_overlays_copy_cursor():
    pane = _make_pane("a", cols=10, rows=3, text="hello")
    pane.enter_copy_mode()
    root = Leaf(pane)
    layout(root, Rect(0, 0, 10, 3))

    comp, _ = _capture_compositor(10, 3)
    frame = comp.compose(root, Rect(0, 0, 10, 3), focused_pane=pane)

    assert frame[0][4].bg == "bright_green"


def test_compose_overlays_selection():
    pane = _make_pane("a", cols=10, rows=3, text="hello")
    pane.enter_copy_mode()
    state = pane.copy_mode_state
    assert state is not None
    handle_named_key(state, "space")
    handle_named_key(state, "left")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 10, 3))

    comp, _ = _capture_compositor(10, 3)
    frame = comp.compose(root, Rect(0, 0, 10, 3), focused_pane=pane)

    assert frame[0][3].bg == "bright_magenta"
    assert frame[0][4].bg == "bright_yellow"


def test_compose_overlays_search_hit():
    pane = _make_pane("a", cols=20, rows=3, text="xx needle here")
    pane.enter_copy_mode()
    state = pane.copy_mode_state
    assert state is not None
    state.cursor_line_abs = 0
    state.cursor_col = 0
    handle_named_key(state, "search")
    for ch in "needle":
        handle_text_input(state, ch)
    handle_named_key(state, "enter")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 20, 3))

    comp, _ = _capture_compositor(20, 3)
    frame = comp.compose(root, Rect(0, 0, 20, 3), focused_pane=pane)

    assert frame[0][3].bg == "bright_green"
    assert frame[0][4].bg == "bright_cyan"


# ══════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Compositor Tests (state + diff)")
    print("=" * 60)

    run_test("render_initial", test_render_initial)
    run_test("render_no_change", test_render_no_change)
    run_test("render_marks_not_dirty", test_render_marks_not_dirty)
    run_test("mark_dirty", test_mark_dirty)
    run_test("root_border_option_draws_outer_box", test_root_border_option_draws_outer_box)
    run_test("render_status_line_overlays_last_row", test_render_status_line_overlays_last_row)
    run_test("compose_uses_scrollback_viewport", test_compose_uses_scrollback_viewport)
    run_test("compose_overlays_copy_cursor", test_compose_overlays_copy_cursor)
    run_test("compose_overlays_selection", test_compose_overlays_selection)
    run_test("compose_overlays_search_hit", test_compose_overlays_search_hit)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed, {len(results)} total")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
