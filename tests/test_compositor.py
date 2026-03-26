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

sys.path.insert(0, str(Path(__file__).parent.parent))

from terminalist.core.pane import Rect
from terminalist.frontend.compositor import EMPTY_CHAR
from terminalist.frontend.split_tree import Leaf, layout

from conftest import make_pane as _make_pane, capture_compositor as _capture_compositor, feed_pane

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

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed, {len(results)} total")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
