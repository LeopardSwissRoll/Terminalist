"""Split tree unit tests — pure logic, no PTY needed."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from terminalist.core.pane import Pane, Rect
from terminalist.frontend.split_tree import (
    Direction, Leaf, Split, SplitNode, BorderSegment,
    layout, all_panes, find_leaf,
    split_pane, remove_pane, find_neighbor, borders,
)

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


def _mock_pane(pane_id: str) -> Pane:
    """Create a Pane with a mock session (no PTY needed)."""
    session = MagicMock()
    session.session_id = pane_id
    session._screen = MagicMock()
    session._screen.columns = 80
    session._screen.lines = 24
    p = Pane.__new__(Pane)
    p.pane_id = pane_id
    p.session = session
    p.rect = Rect(0, 0, 80, 24)
    p.focused = False
    p._copy_mode = False
    p._scroll_offset = 0
    return p


# ══════════════════════════════════════════════
#  Layout tests
# ══════════════════════════════════════════════

def test_single_leaf_layout():
    """Single leaf gets the full rect."""
    pane = _mock_pane("a")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 80, 24))
    assert pane.rect == Rect(0, 0, 80, 24)


def test_vertical_split_layout():
    """Vertical split divides width with 1-col border."""
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 24))
    # 80 * 0.5 - 1 = 39, border at 39, second starts at 40, width = 40
    assert a.rect.w == 39, f"a.w={a.rect.w}"
    assert b.rect.x == 40, f"b.x={b.rect.x}"
    assert b.rect.w == 40, f"b.w={b.rect.w}"
    assert a.rect.w + 1 + b.rect.w == 80, "widths + border should equal total"


def test_horizontal_split_layout():
    """Horizontal split divides height with 1-row border."""
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.HORIZONTAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 24))
    assert a.rect.h + 1 + b.rect.h == 24, f"a.h={a.rect.h} b.h={b.rect.h}"
    assert b.rect.y == a.rect.h + 1


def test_nested_split_layout():
    """Nested split: top half = A, bottom half = B | C."""
    a = _mock_pane("a")
    b = _mock_pane("b")
    c = _mock_pane("c")
    root = Split(
        Direction.HORIZONTAL, 0.5,
        Leaf(a),
        Split(Direction.VERTICAL, 0.5, Leaf(b), Leaf(c)),
    )
    layout(root, Rect(0, 0, 80, 24))
    assert a.rect.h + 1 + b.rect.h == 24
    assert b.rect.w + 1 + c.rect.w == 80


def test_layout_with_offset():
    """Layout with non-zero x/y offset."""
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(10, 5, 60, 20))
    assert a.rect.x == 10
    assert a.rect.y == 5
    assert b.rect.y == 5
    assert b.rect.x == 10 + a.rect.w + 1


def test_layout_unequal_ratio():
    """70/30 split."""
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.7, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 100, 24))
    assert a.rect.w > b.rect.w, f"a.w={a.rect.w} should be > b.w={b.rect.w}"
    assert a.rect.w + 1 + b.rect.w == 100


def test_layout_minimum_size():
    """Very small terminal — both panes get minimum size."""
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 5, 3))  # 5 cols: min 2 + border 1 + min 2 = 5
    assert a.rect.w >= 2
    assert b.rect.w >= 2


# ══════════════════════════════════════════════
#  Tree traversal
# ══════════════════════════════════════════════

def test_all_panes_single():
    a = _mock_pane("a")
    assert len(all_panes(Leaf(a))) == 1


def test_all_panes_multiple():
    a, b, c = _mock_pane("a"), _mock_pane("b"), _mock_pane("c")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a),
                 Split(Direction.HORIZONTAL, 0.5, Leaf(b), Leaf(c)))
    panes = all_panes(root)
    ids = [p.pane_id for p in panes]
    assert ids == ["a", "b", "c"]


def test_find_leaf_exists():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    assert find_leaf(root, "b").pane.pane_id == "b"


def test_find_leaf_not_found():
    a = _mock_pane("a")
    assert find_leaf(Leaf(a), "nonexistent") is None


# ══════════════════════════════════════════════
#  Tree mutation
# ══════════════════════════════════════════════

def test_split_pane_creates_split():
    a = _mock_pane("a")
    b = _mock_pane("b")
    root = Leaf(a)
    new_root = split_pane(root, "a", b, Direction.VERTICAL)
    assert isinstance(new_root, Split)
    panes = all_panes(new_root)
    assert len(panes) == 2
    assert panes[0].pane_id == "a"
    assert panes[1].pane_id == "b"


def test_split_pane_nested():
    """Split an already-split pane."""
    a, b, c = _mock_pane("a"), _mock_pane("b"), _mock_pane("c")
    root = split_pane(Leaf(a), "a", b, Direction.VERTICAL)
    root = split_pane(root, "b", c, Direction.HORIZONTAL)
    panes = all_panes(root)
    assert len(panes) == 3


def test_remove_pane_collapses():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    new_root = remove_pane(root, "a")
    assert isinstance(new_root, Leaf)
    assert new_root.pane.pane_id == "b"


def test_remove_last_pane():
    a = _mock_pane("a")
    assert remove_pane(Leaf(a), "a") is None


def test_remove_from_nested():
    a, b, c = _mock_pane("a"), _mock_pane("b"), _mock_pane("c")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a),
                 Split(Direction.HORIZONTAL, 0.5, Leaf(b), Leaf(c)))
    new_root = remove_pane(root, "b")
    panes = all_panes(new_root)
    ids = [p.pane_id for p in panes]
    assert "b" not in ids
    assert len(panes) == 2


# ══════════════════════════════════════════════
#  Neighbor finding
# ══════════════════════════════════════════════

def test_neighbor_right():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    neighbor = find_neighbor(root, "a", Direction.VERTICAL, toward_second=True)
    assert neighbor is not None and neighbor.pane_id == "b"


def test_neighbor_left():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    neighbor = find_neighbor(root, "b", Direction.VERTICAL, toward_second=False)
    assert neighbor is not None and neighbor.pane_id == "a"


def test_neighbor_none_at_edge():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    # a has no left neighbor
    assert find_neighbor(root, "a", Direction.VERTICAL, toward_second=False) is None


def test_neighbor_wrong_direction():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    # Vertical split has no horizontal neighbors
    assert find_neighbor(root, "a", Direction.HORIZONTAL, toward_second=True) is None


# ══════════════════════════════════════════════
#  Border collection
# ══════════════════════════════════════════════

def test_borders_single_pane():
    a = _mock_pane("a")
    segs = borders(Leaf(a), Rect(0, 0, 80, 24))
    assert segs == []


def test_borders_vertical_split():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    segs = borders(root, Rect(0, 0, 80, 24))
    assert len(segs) == 1
    seg = segs[0]
    assert seg.direction == Direction.VERTICAL
    assert seg.length == 24
    assert seg.x == 39  # 80 * 0.5 - 1 = 39


def test_borders_nested():
    a, b, c = _mock_pane("a"), _mock_pane("b"), _mock_pane("c")
    root = Split(
        Direction.HORIZONTAL, 0.5,
        Leaf(a),
        Split(Direction.VERTICAL, 0.5, Leaf(b), Leaf(c)),
    )
    segs = borders(root, Rect(0, 0, 80, 24))
    assert len(segs) == 2  # 1 horizontal + 1 vertical


# ══════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Split Tree Unit Tests")
    print("=" * 60)

    print("\n── Layout ──")
    run_test("single_leaf_layout", test_single_leaf_layout)
    run_test("vertical_split_layout", test_vertical_split_layout)
    run_test("horizontal_split_layout", test_horizontal_split_layout)
    run_test("nested_split_layout", test_nested_split_layout)
    run_test("layout_with_offset", test_layout_with_offset)
    run_test("layout_unequal_ratio", test_layout_unequal_ratio)
    run_test("layout_minimum_size", test_layout_minimum_size)

    print("\n── Traversal ──")
    run_test("all_panes_single", test_all_panes_single)
    run_test("all_panes_multiple", test_all_panes_multiple)
    run_test("find_leaf_exists", test_find_leaf_exists)
    run_test("find_leaf_not_found", test_find_leaf_not_found)

    print("\n── Mutation ──")
    run_test("split_pane_creates_split", test_split_pane_creates_split)
    run_test("split_pane_nested", test_split_pane_nested)
    run_test("remove_pane_collapses", test_remove_pane_collapses)
    run_test("remove_last_pane", test_remove_last_pane)
    run_test("remove_from_nested", test_remove_from_nested)

    print("\n── Neighbor ──")
    run_test("neighbor_right", test_neighbor_right)
    run_test("neighbor_left", test_neighbor_left)
    run_test("neighbor_none_at_edge", test_neighbor_none_at_edge)
    run_test("neighbor_wrong_direction", test_neighbor_wrong_direction)

    print("\n── Borders ──")
    run_test("borders_single_pane", test_borders_single_pane)
    run_test("borders_vertical_split", test_borders_vertical_split)
    run_test("borders_nested", test_borders_nested)

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
