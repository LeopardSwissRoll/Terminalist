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


def layout(node: SplitNode, rect: Rect) -> None:
    """Recursively compute Rects for all Leaf panes.

    Accounts for 1-cell border between Split siblings.
    Calls pane.set_rect() on each Leaf.
    """
    if isinstance(node, Leaf):
        node.pane.set_rect(rect)
        log("layout", f"[{node.pane.pane_id}] rect={rect}")
        return

    if isinstance(node, Split):
        if node.direction == Direction.VERTICAL:
            # Left | border(1) | Right
            total = rect.w
            first_w = max(MIN_PANE_W, int(total * node.ratio) - 1)
            # Ensure second pane also meets minimum
            second_w = total - first_w - 1  # -1 for border
            if second_w < MIN_PANE_W:
                second_w = MIN_PANE_W
                first_w = total - second_w - 1

            first_rect = Rect(rect.x, rect.y, first_w, rect.h)
            second_rect = Rect(rect.x + first_w + 1, rect.y, second_w, rect.h)

        else:  # HORIZONTAL
            # Top / border(1) / Bottom
            total = rect.h
            first_h = max(MIN_PANE_H, int(total * node.ratio) - 1)
            second_h = total - first_h - 1
            if second_h < MIN_PANE_H:
                second_h = MIN_PANE_H
                first_h = total - second_h - 1

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
    """Find the neighboring Pane in the given direction.

    toward_second=True: right (vertical) or down (horizontal)
    toward_second=False: left (vertical) or up (horizontal)
    """
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

        # Check if the target is in the expected child
        child_idx = _which_child(node, path[i + 1] if i + 1 < len(path) else None, pane_id)
        if child_idx is None:
            continue

        if toward_second and child_idx == "first":
            # Target is in first, neighbor is in second
            return _edge_pane(node.second, not toward_second)
        elif not toward_second and child_idx == "second":
            # Target is in second, neighbor is in first
            return _edge_pane(node.first, not toward_second)

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


def _which_child(split: Split, child_node: SplitNode | None, pane_id: str) -> str | None:
    """Determine if pane_id is in 'first' or 'second' subtree."""
    if find_leaf(split.first, pane_id):
        return "first"
    if find_leaf(split.second, pane_id):
        return "second"
    return None


def _edge_pane(node: SplitNode, from_end: bool) -> Pane | None:
    """Get the edge pane of a subtree (leftmost/topmost or rightmost/bottommost)."""
    if isinstance(node, Leaf):
        return node.pane
    if isinstance(node, Split):
        if from_end:
            return _edge_pane(node.second, from_end)
        else:
            return _edge_pane(node.first, from_end)
    return None


# ── Border collection ──


@dataclass
class BorderSegment:
    """A border line segment between two panes."""
    x: int
    y: int
    length: int
    direction: Direction  # direction of the border line itself


def borders(node: SplitNode, rect: Rect) -> list[BorderSegment]:
    """Collect all border segments for rendering."""
    result: list[BorderSegment] = []
    _borders_recursive(node, rect, result)
    return result


def _borders_recursive(node: SplitNode, rect: Rect, out: list[BorderSegment]) -> None:
    if isinstance(node, Leaf):
        return

    if isinstance(node, Split):
        if node.direction == Direction.VERTICAL:
            first_w = max(MIN_PANE_W, int(rect.w * node.ratio) - 1)
            second_w = rect.w - first_w - 1
            if second_w < MIN_PANE_W:
                second_w = MIN_PANE_W
                first_w = rect.w - second_w - 1

            border_x = rect.x + first_w
            out.append(BorderSegment(border_x, rect.y, rect.h, Direction.VERTICAL))

            first_rect = Rect(rect.x, rect.y, first_w, rect.h)
            second_rect = Rect(border_x + 1, rect.y, second_w, rect.h)

        else:  # HORIZONTAL
            first_h = max(MIN_PANE_H, int(rect.h * node.ratio) - 1)
            second_h = rect.h - first_h - 1
            if second_h < MIN_PANE_H:
                second_h = MIN_PANE_H
                first_h = rect.h - second_h - 1

            border_y = rect.y + first_h
            out.append(BorderSegment(rect.x, border_y, rect.w, Direction.HORIZONTAL))

            first_rect = Rect(rect.x, rect.y, rect.w, first_h)
            second_rect = Rect(rect.x, border_y + 1, rect.w, second_h)

        _borders_recursive(node.first, first_rect, out)
        _borders_recursive(node.second, second_rect, out)
