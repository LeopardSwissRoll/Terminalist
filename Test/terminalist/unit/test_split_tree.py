"""Split tree unit tests — pure logic, no PTY needed."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from terminalist.core.pane import Pane, Rect
from terminalist.frontend.split_tree import (
    Direction, Leaf, Split, SplitNode,
    compute_content_rects, layout_frames, layout, all_panes, find_leaf, can_split, hit_test,
    split_pane, remove_pane, find_neighbor, adjust_ratio,
    MIN_PANE_W, MIN_PANE_H,
)

from Test.conftest import mock_pane as _mock_pane

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


# ══════════════════════════════════════════════
#  Layout tests
# ══════════════════════════════════════════════

def test_single_leaf_layout():
    """Single leaf gets the full rect."""
    pane = _mock_pane("a")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 80, 24))
    assert pane.content_rect == Rect(0, 0, 80, 24)


def test_vertical_split_layout():
    """Vertical split divides width with 1-col border."""
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 24))
    # 80 * 0.5 - 1 = 39, border at 39, second starts at 40, width = 40
    assert a.content_rect.w == 39, f"a.w={a.content_rect.w}"
    assert b.content_rect.x == 40, f"b.x={b.content_rect.x}"
    assert b.content_rect.w == 40, f"b.w={b.content_rect.w}"
    assert a.content_rect.w + 1 + b.content_rect.w == 80, "widths + border should equal total"


def test_horizontal_split_layout():
    """Horizontal split divides height with 1-row border."""
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.HORIZONTAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 24))
    assert a.content_rect.h + 1 + b.content_rect.h == 24, f"a.h={a.content_rect.h} b.h={b.content_rect.h}"
    assert b.content_rect.y == a.content_rect.h + 1


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
    assert a.content_rect.h + 1 + b.content_rect.h == 24
    assert b.content_rect.w + 1 + c.content_rect.w == 80


def test_layout_with_offset():
    """Layout with non-zero x/y offset."""
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(10, 5, 60, 20))
    assert a.content_rect.x == 10
    assert a.content_rect.y == 5
    assert b.content_rect.y == 5
    assert b.content_rect.x == 10 + a.content_rect.w + 1


def test_layout_unequal_ratio():
    """70/30 split."""
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.7, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 100, 24))
    assert a.content_rect.w > b.content_rect.w, f"a.w={a.content_rect.w} should be > b.w={b.content_rect.w}"
    assert a.content_rect.w + 1 + b.content_rect.w == 100


def test_layout_minimum_size():
    """Very small terminal — both panes get minimum size."""
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 5, 3))  # 5 cols: min 2 + border 1 + min 2 = 5
    assert a.content_rect.w >= 2
    assert b.content_rect.w >= 2


def test_layout_assigns_shared_frame_rects_without_changing_content_rects():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 24))
    assert a.frame_rect.right == b.frame_rect.x
    assert a.content_rect.w == 39
    assert b.content_rect.w == 40


def test_layout_undersize_vertical():
    """Terminal too narrow for split — sizes clamped to minimum, never 0 or negative."""
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 3, 10))  # 3 < min*2+1=5
    assert a.content_rect.w >= MIN_PANE_W, f"a.w={a.content_rect.w} < {MIN_PANE_W}"
    assert b.content_rect.w >= MIN_PANE_W, f"b.w={b.content_rect.w} < {MIN_PANE_W}"


def test_layout_undersize_horizontal():
    """Terminal too short for split — sizes clamped to minimum."""
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.HORIZONTAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 2))  # 2 < min*2+1=3
    assert a.content_rect.h >= MIN_PANE_H, f"a.h={a.content_rect.h} < {MIN_PANE_H}"
    assert b.content_rect.h >= MIN_PANE_H, f"b.h={b.content_rect.h} < {MIN_PANE_H}"


def test_can_split_check():
    """can_split returns False when rect is too small."""
    assert can_split(Rect(0, 0, 80, 24), Direction.VERTICAL) is True
    assert can_split(Rect(0, 0, 4, 24), Direction.VERTICAL) is False
    assert can_split(Rect(0, 0, 5, 24), Direction.VERTICAL) is True
    assert can_split(Rect(0, 0, 80, 2), Direction.HORIZONTAL) is False
    assert can_split(Rect(0, 0, 80, 3), Direction.HORIZONTAL) is True


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
    new_root, replacement = remove_pane(root, "a")
    assert isinstance(new_root, Leaf)
    assert new_root.pane.pane_id == "b"
    assert isinstance(replacement, Leaf)
    assert replacement.pane.pane_id == "b"


def test_remove_last_pane():
    a = _mock_pane("a")
    new_root, replacement = remove_pane(Leaf(a), "a")
    assert new_root is None
    assert replacement is None


def test_remove_from_nested():
    a, b, c = _mock_pane("a"), _mock_pane("b"), _mock_pane("c")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a),
                 Split(Direction.HORIZONTAL, 0.5, Leaf(b), Leaf(c)))
    new_root, replacement = remove_pane(root, "b")
    panes = all_panes(new_root)
    ids = [p.pane_id for p in panes]
    assert "b" not in ids
    assert len(panes) == 2
    assert isinstance(replacement, Leaf)
    assert replacement.pane.pane_id == "c"


# ══════════════════════════════════════════════
#  Neighbor finding
# ══════════════════════════════════════════════

def test_neighbor_right():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 24))
    neighbor = find_neighbor(root, "a", Direction.VERTICAL, toward_second=True)
    assert neighbor is not None and neighbor.pane_id == "b"


def test_neighbor_left():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 24))
    neighbor = find_neighbor(root, "b", Direction.VERTICAL, toward_second=False)
    assert neighbor is not None and neighbor.pane_id == "a"


def test_neighbor_none_at_edge():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 24))
    # a has no left neighbor
    assert find_neighbor(root, "a", Direction.VERTICAL, toward_second=False) is None


def test_neighbor_wrong_direction():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 24))
    # Vertical split has no horizontal neighbors
    assert find_neighbor(root, "a", Direction.HORIZONTAL, toward_second=True) is None


def test_neighbor_2x2_right_from_bottom_left():
    """CRITICAL: In a 2x2 grid, right from C should go to D, not B.

    Layout:
      A | B
      -----
      C | D
    """
    a, b, c, d = _mock_pane("a"), _mock_pane("b"), _mock_pane("c"), _mock_pane("d")
    root = Split(
        Direction.HORIZONTAL, 0.5,
        Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b)),
        Split(Direction.VERTICAL, 0.5, Leaf(c), Leaf(d)),
    )
    layout(root, Rect(0, 0, 80, 24))
    neighbor = find_neighbor(root, "c", Direction.VERTICAL, toward_second=True)
    assert neighbor is not None and neighbor.pane_id == "d", \
        f"Expected 'd', got '{neighbor.pane_id if neighbor else None}'"


def test_neighbor_2x2_left_from_top_right():
    """In 2x2 grid, left from B should go to A, not C."""
    a, b, c, d = _mock_pane("a"), _mock_pane("b"), _mock_pane("c"), _mock_pane("d")
    root = Split(
        Direction.HORIZONTAL, 0.5,
        Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b)),
        Split(Direction.VERTICAL, 0.5, Leaf(c), Leaf(d)),
    )
    layout(root, Rect(0, 0, 80, 24))
    neighbor = find_neighbor(root, "b", Direction.VERTICAL, toward_second=False)
    assert neighbor is not None and neighbor.pane_id == "a", \
        f"Expected 'a', got '{neighbor.pane_id if neighbor else None}'"


def test_neighbor_2x2_down_from_top_left():
    """In 2x2 grid, down from A should go to C, not B."""
    a, b, c, d = _mock_pane("a"), _mock_pane("b"), _mock_pane("c"), _mock_pane("d")
    root = Split(
        Direction.HORIZONTAL, 0.5,
        Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b)),
        Split(Direction.VERTICAL, 0.5, Leaf(c), Leaf(d)),
    )
    layout(root, Rect(0, 0, 80, 24))
    neighbor = find_neighbor(root, "a", Direction.HORIZONTAL, toward_second=True)
    assert neighbor is not None and neighbor.pane_id == "c", \
        f"Expected 'c', got '{neighbor.pane_id if neighbor else None}'"


# ══════════════════════════════════════════════
#  Hit test
# ══════════════════════════════════════════════

def test_hit_test_single_pane():
    a = _mock_pane("a")
    root = Leaf(a)
    layout(root, Rect(0, 0, 80, 24))
    assert hit_test(root, 0, 0).pane_id == "a"
    assert hit_test(root, 79, 23).pane_id == "a"
    assert hit_test(root, 80, 0) is None  # out of bounds


def test_hit_test_vertical_split():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 24))
    assert hit_test(root, 0, 0).pane_id == "a"     # left pane
    assert hit_test(root, 79, 0).pane_id == "b"    # right pane
    assert hit_test(root, 39, 0) is None            # border


def test_hit_test_nested():
    a, b, c, d = _mock_pane("a"), _mock_pane("b"), _mock_pane("c"), _mock_pane("d")
    root = Split(
        Direction.HORIZONTAL, 0.5,
        Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b)),
        Split(Direction.VERTICAL, 0.5, Leaf(c), Leaf(d)),
    )
    layout(root, Rect(0, 0, 80, 24))
    assert hit_test(root, 0, 0).pane_id == "a"      # top-left
    assert hit_test(root, 79, 0).pane_id == "b"     # top-right
    assert hit_test(root, 0, 23).pane_id == "c"     # bottom-left
    assert hit_test(root, 79, 23).pane_id == "d"    # bottom-right


# ══════════════════════════════════════════════
#  Ratio adjustment
# ══════════════════════════════════════════════

def test_adjust_ratio_vertical_moves_nearest_matching_split():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 24))

    changed = adjust_ratio(root, "a", Direction.VERTICAL, 0.05)

    assert changed is True
    assert root.ratio > 0.5


def test_adjust_ratio_horizontal_clamps_at_minimum():
    a, b = _mock_pane("a"), _mock_pane("b")
    root = Split(Direction.HORIZONTAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 3))

    changed = adjust_ratio(root, "a", Direction.HORIZONTAL, -0.50)

    assert changed is True
    assert root.ratio >= (MIN_PANE_H + 1) / 3


def test_adjust_ratio_uses_closest_matching_ancestor():
    a, b, c = _mock_pane("a"), _mock_pane("b"), _mock_pane("c")
    inner = Split(Direction.VERTICAL, 0.5, Leaf(b), Leaf(c))
    root = Split(Direction.HORIZONTAL, 0.5, Leaf(a), inner)
    layout(root, Rect(0, 0, 80, 24))

    changed = adjust_ratio(root, "c", Direction.VERTICAL, 0.05)

    assert changed is True
    assert inner.ratio > 0.5
    assert root.ratio == 0.5


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

    run_test("layout_undersize_vertical", test_layout_undersize_vertical)
    run_test("layout_undersize_horizontal", test_layout_undersize_horizontal)
    run_test("can_split_check", test_can_split_check)

    print("\n── Neighbor ──")
    run_test("neighbor_right", test_neighbor_right)
    run_test("neighbor_left", test_neighbor_left)
    run_test("neighbor_none_at_edge", test_neighbor_none_at_edge)
    run_test("neighbor_wrong_direction", test_neighbor_wrong_direction)
    run_test("neighbor_2x2_right_from_bottom_left", test_neighbor_2x2_right_from_bottom_left)
    run_test("neighbor_2x2_left_from_top_right", test_neighbor_2x2_left_from_top_right)
    run_test("neighbor_2x2_down_from_top_left", test_neighbor_2x2_down_from_top_left)

    print("\n── Hit test ──")
    run_test("hit_test_single_pane", test_hit_test_single_pane)
    run_test("hit_test_vertical_split", test_hit_test_vertical_split)
    run_test("hit_test_nested", test_hit_test_nested)

    print("\n── Ratio adjustment ──")
    run_test("adjust_ratio_vertical_moves_nearest_matching_split", test_adjust_ratio_vertical_moves_nearest_matching_split)
    run_test("adjust_ratio_horizontal_clamps_at_minimum", test_adjust_ratio_horizontal_clamps_at_minimum)
    run_test("adjust_ratio_uses_closest_matching_ancestor", test_adjust_ratio_uses_closest_matching_ancestor)

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
