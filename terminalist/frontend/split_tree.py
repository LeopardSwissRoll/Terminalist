"""Split tree — binary tree layout for terminal panes.

A split tree recursively divides screen space between panes.
Leaf nodes hold Panes, Split nodes divide space between two children.

Border between siblings consumes 1 cell (column or row).
Minimum pane size: 2 columns × 1 row.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from terminalist.core.pane import Pane, Rect
from terminalist.debug import log

if TYPE_CHECKING:
    pass

MIN_PANE_W = 2
MIN_PANE_H = 1


class Direction(Enum):
    HORIZONTAL = "h"  # top / bottom
    VERTICAL = "v"    # left / right


class SplitNode:
    """Base class for split tree nodes."""
    pass


@dataclass
class Leaf(SplitNode):
    """Terminal node — holds one Pane."""
    pane: Pane


@dataclass
class Split(SplitNode):
    """Internal node — divides space between two children."""
    direction: Direction
    ratio: float  # 0.0–1.0, portion given to `first`
    first: SplitNode
    second: SplitNode


# ── Layout ──


def can_split(rect: Rect, direction: Direction) -> bool:
    """Check if rect has enough space for a split (min*2 + border)."""
    if direction == Direction.VERTICAL:
        return rect.w >= MIN_PANE_W * 2 + 1
    else:
        return rect.h >= MIN_PANE_H * 2 + 1


def _split_sizes(total: int, ratio: float, min_size: int) -> tuple[int, int]:
    """Calculate first/second sizes for a split, with clamping.

    Shared between layout() and _borders_recursive() to avoid inconsistency.
    Returns (first_size, second_size). Both >= min_size.
    """
    first = max(min_size, int(total * ratio) - 1)
    second = total - first - 1  # -1 for border
    if second < min_size:
        second = min_size
        first = max(min_size, total - second - 1)
    if first < min_size:
        first = min_size
    return first, second


def layout(node: SplitNode, rect: Rect) -> None:
    """Recursively compute Rects for all Leaf panes.

    Accounts for 1-cell border between Split siblings.
    Calls pane.set_rect() on each Leaf.
    Clamps all sizes to minimums (never negative/zero).
    """
    if isinstance(node, Leaf):
        clamped = Rect(rect.x, rect.y, max(rect.w, MIN_PANE_W), max(rect.h, MIN_PANE_H))
        node.pane.set_rect(clamped)
        log("layout", f"[{node.pane.pane_id}] rect={clamped}")
        return

    if isinstance(node, Split):
        if node.direction == Direction.VERTICAL:
            first_w, second_w = _split_sizes(rect.w, node.ratio, MIN_PANE_W)
            first_rect = Rect(rect.x, rect.y, first_w, rect.h)
            second_rect = Rect(rect.x + first_w + 1, rect.y, second_w, rect.h)
        else:
            first_h, second_h = _split_sizes(rect.h, node.ratio, MIN_PANE_H)
            first_rect = Rect(rect.x, rect.y, rect.w, first_h)
            second_rect = Rect(rect.x, rect.y + first_h + 1, rect.w, second_h)

        layout(node.first, first_rect)
        layout(node.second, second_rect)


# ── Tree traversal ──


def all_panes(node: SplitNode) -> list[Pane]:
    """Collect all Panes in DFS order."""
    if isinstance(node, Leaf):
        return [node.pane]
    if isinstance(node, Split):
        return all_panes(node.first) + all_panes(node.second)
    return []


def find_leaf(node: SplitNode, pane_id: str) -> Leaf | None:
    """Find a Leaf by pane_id."""
    if isinstance(node, Leaf):
        return node if node.pane.pane_id == pane_id else None
    if isinstance(node, Split):
        return find_leaf(node.first, pane_id) or find_leaf(node.second, pane_id)
    return None


# ── Tree mutation ──


def split_pane(
    root: SplitNode,
    target_pane_id: str,
    new_pane: Pane,
    direction: Direction,
    ratio: float = 0.5,
) -> SplitNode:
    """Replace a Leaf with a Split containing the old and new Panes.

    Returns the new tree root (may be the same object if target is not root).
    """
    return _split_recursive(root, target_pane_id, new_pane, direction, ratio)


def _split_recursive(
    node: SplitNode,
    target: str,
    new_pane: Pane,
    direction: Direction,
    ratio: float,
) -> SplitNode:
    if isinstance(node, Leaf):
        if node.pane.pane_id == target:
            return Split(
                direction=direction,
                ratio=ratio,
                first=node,
                second=Leaf(new_pane),
            )
        return node

    if isinstance(node, Split):
        node.first = _split_recursive(node.first, target, new_pane, direction, ratio)
        node.second = _split_recursive(node.second, target, new_pane, direction, ratio)
        return node

    return node


def remove_pane(root: SplitNode, target_pane_id: str) -> SplitNode | None:
    """Remove a Leaf and collapse its parent Split.

    Returns new root, or None if tree becomes empty.
    """
    result = _remove_recursive(root, target_pane_id)
    return result


def _remove_recursive(node: SplitNode, target: str) -> SplitNode | None:
    if isinstance(node, Leaf):
        return None if node.pane.pane_id == target else node

    if isinstance(node, Split):
        new_first = _remove_recursive(node.first, target)
        new_second = _remove_recursive(node.second, target)

        if new_first is None and new_second is None:
            return None
        if new_first is None:
            return new_second
        if new_second is None:
            return new_first

        node.first = new_first
        node.second = new_second
        return node

    return node


# ── Neighbor finding ──


def find_neighbor(
    root: SplitNode,
    pane_id: str,
    direction: Direction,
    toward_second: bool,
) -> Pane | None:
    """Find the spatially adjacent Pane in the given direction.

    toward_second=True: right (vertical) or down (horizontal)
    toward_second=False: left (vertical) or up (horizontal)

    Uses Rect positions (must call layout() first) to find the pane
    whose edge is closest to the source pane's position.
    """
    source_leaf = find_leaf(root, pane_id)
    if not source_leaf:
        return None
    source_rect = source_leaf.pane.rect

    path = _path_to(root, pane_id)
    if not path:
        return None

    # Walk up the path to find a Split with matching direction
    for i in range(len(path) - 1, -1, -1):
        node = path[i]
        if not isinstance(node, Split):
            continue
        if node.direction != direction:
            continue

        child_idx = _which_child(node, pane_id)
        if child_idx is None:
            continue

        if toward_second and child_idx == "first":
            # Target is in first, neighbor is in second
            return _nearest_pane(node.second, source_rect, direction)
        elif not toward_second and child_idx == "second":
            # Target is in second, neighbor is in first
            return _nearest_pane(node.first, source_rect, direction)

    return None


def _path_to(root: SplitNode, pane_id: str) -> list[SplitNode]:
    """Return path from root to the Leaf with pane_id (inclusive)."""
    if isinstance(root, Leaf):
        return [root] if root.pane.pane_id == pane_id else []
    if isinstance(root, Split):
        for child in (root.first, root.second):
            path = _path_to(child, pane_id)
            if path:
                return [root] + path
    return []


def _which_child(split: Split, pane_id: str) -> str | None:
    """Determine if pane_id is in 'first' or 'second' subtree."""
    if find_leaf(split.first, pane_id):
        return "first"
    if find_leaf(split.second, pane_id):
        return "second"
    return None


def _rect_overlap(a: Rect, b: Rect, direction: Direction) -> int:
    """Calculate overlap between two rects on the axis perpendicular to direction.

    For vertical movement (left/right): overlap on Y axis.
    For horizontal movement (up/down): overlap on X axis.
    """
    if direction == Direction.VERTICAL:
        # Overlap on Y axis
        start = max(a.y, b.y)
        end = min(a.y + a.h, b.y + b.h)
    else:
        # Overlap on X axis
        start = max(a.x, b.x)
        end = min(a.x + a.w, b.x + b.w)
    return max(0, end - start)


def _nearest_pane(node: SplitNode, source_rect: Rect, direction: Direction) -> Pane | None:
    """Find the pane in subtree that overlaps most with source_rect on the perpendicular axis.

    In a 2x2 grid moving right from bottom-left, this picks
    bottom-right (overlapping rows) instead of top-right.
    """
    candidates = all_panes(node)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    best = None
    best_overlap = -1
    for pane in candidates:
        overlap = _rect_overlap(source_rect, pane.rect, direction)
        if overlap > best_overlap:
            best_overlap = overlap
            best = pane
    return best


# ── Hit test (mouse click → pane) ──


def hit_test(node: SplitNode, x: int, y: int) -> Pane | None:
    """Find the Pane at screen coordinates (x, y).

    Returns None if coordinates are on a border or outside all panes.
    """
    if isinstance(node, Leaf):
        r = node.pane.rect
        if r.x <= x < r.x + r.w and r.y <= y < r.y + r.h:
            return node.pane
        return None

    if isinstance(node, Split):
        # Try both children — coordinates will match at most one
        result = hit_test(node.first, x, y)
        if result:
            return result
        return hit_test(node.second, x, y)

    return None


# ── Border collection ──


@dataclass
class BorderSegment:
    """A border line segment between two panes."""
    x: int
    y: int
    length: int
    direction: Direction  # direction of the border line itself
    active: bool = False  # True if focused pane is adjacent


def borders(
    node: SplitNode, rect: Rect, focused_pane_id: str | None = None,
) -> list[BorderSegment]:
    """Collect all border segments for rendering.

    If focused_pane_id is given, segments adjacent to the focused pane
    are marked active=True (for highlight rendering).
    """
    result: list[BorderSegment] = []
    _borders_recursive(node, rect, result, focused_pane_id)
    return result


def _borders_recursive(
    node: SplitNode, rect: Rect, out: list[BorderSegment],
    focused_id: str | None,
) -> None:
    if isinstance(node, Leaf):
        return

    if isinstance(node, Split):
        # Check if focused pane is in either child subtree
        active = False
        if focused_id:
            in_first = find_leaf(node.first, focused_id) is not None
            in_second = find_leaf(node.second, focused_id) is not None
            # Border is active if focused pane is on either side
            active = in_first or in_second

        if node.direction == Direction.VERTICAL:
            first_w, second_w = _split_sizes(rect.w, node.ratio, MIN_PANE_W)
            border_x = rect.x + first_w
            out.append(BorderSegment(border_x, rect.y, rect.h, Direction.VERTICAL, active))
            first_rect = Rect(rect.x, rect.y, first_w, rect.h)
            second_rect = Rect(border_x + 1, rect.y, second_w, rect.h)
        else:
            first_h, second_h = _split_sizes(rect.h, node.ratio, MIN_PANE_H)
            border_y = rect.y + first_h
            out.append(BorderSegment(rect.x, border_y, rect.w, Direction.HORIZONTAL, active))
            first_rect = Rect(rect.x, rect.y, rect.w, first_h)
            second_rect = Rect(rect.x, border_y + 1, rect.w, second_h)

        _borders_recursive(node.first, first_rect, out, focused_id)
        _borders_recursive(node.second, second_rect, out, focused_id)
