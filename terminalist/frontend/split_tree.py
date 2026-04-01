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
    """Compute shared-boundary frame rects + PTY content rects.

    Frame rects represent the visual pane box and may share boundary
    coordinates with siblings. Content rects remain gap-separated so
    PTY content does not overwrite border cells.
    """
    layout_frames(node, rect, shared_boundary=True)
    compute_content_rects(node, show_root_border=False)
    for pane in all_panes(node):
        log("layout", f"[{pane.pane_id}] frame={pane.frame_rect} content={pane.content_rect}")


def layout_frames(node: SplitNode, rect: Rect, shared_boundary: bool) -> None:
    """Assign visual frame rects to leaves.

    When shared_boundary=True, sibling panes share the same split-line
    coordinate. This matches the mask/owner renderer model.
    """
    if isinstance(node, Leaf):
        node.pane.frame_rect = Rect(rect.x, rect.y, max(rect.w, 1), max(rect.h, 1))
        return

    if not isinstance(node, Split):
        return

    if node.direction == Direction.VERTICAL:
        first_w, second_w = _split_sizes(rect.w, node.ratio, MIN_PANE_W)
        border_x = rect.x + first_w
        use_shared = shared_boundary and can_split(rect, node.direction)
        if use_shared:
            first_rect = Rect(rect.x, rect.y, border_x - rect.x + 1, rect.h)
            second_rect = Rect(border_x, rect.y, rect.right - border_x + 1, rect.h)
        else:
            first_rect = Rect(rect.x, rect.y, first_w, rect.h)
            second_rect = Rect(border_x + 1, rect.y, second_w, rect.h)
    else:
        first_h, second_h = _split_sizes(rect.h, node.ratio, MIN_PANE_H)
        border_y = rect.y + first_h
        use_shared = shared_boundary and can_split(rect, node.direction)
        if use_shared:
            first_rect = Rect(rect.x, rect.y, rect.w, border_y - rect.y + 1)
            second_rect = Rect(rect.x, border_y, rect.w, rect.bottom - border_y + 1)
        else:
            first_rect = Rect(rect.x, rect.y, rect.w, first_h)
            second_rect = Rect(rect.x, border_y + 1, rect.w, second_h)

    layout_frames(node.first, first_rect, shared_boundary)
    layout_frames(node.second, second_rect, shared_boundary)


def compute_content_rects(node: SplitNode, show_root_border: bool) -> None:
    """Derive PTY content rects from shared-boundary frame rects."""
    panes = all_panes(node)
    if not panes:
        return

    root_left = min(pane.frame_rect.x for pane in panes)
    root_top = min(pane.frame_rect.y for pane in panes)
    root_right = max(pane.frame_rect.right for pane in panes)
    root_bottom = max(pane.frame_rect.bottom for pane in panes)

    for pane in panes:
        frame = pane.frame_rect
        left = frame.x
        right = frame.right
        top = frame.y
        bottom = frame.bottom

        if _edge_has_owner(pane, panes, "left") and (right - left + 1) > MIN_PANE_W:
            left += 1
        if _edge_has_owner(pane, panes, "right") and (right - left + 1) > MIN_PANE_W:
            right -= 1
        if _edge_has_owner(pane, panes, "top") and (bottom - top + 1) > MIN_PANE_H:
            top += 1
        if _edge_has_owner(pane, panes, "bottom") and (bottom - top + 1) > MIN_PANE_H:
            bottom -= 1

        if show_root_border and frame.x == root_left and (right - left + 1) > MIN_PANE_W:
            left += 1
        if show_root_border and frame.right == root_right and (right - left + 1) > MIN_PANE_W:
            right -= 1
        if show_root_border and frame.y == root_top and (bottom - top + 1) > MIN_PANE_H:
            top += 1
        if show_root_border and frame.bottom == root_bottom and (bottom - top + 1) > MIN_PANE_H:
            bottom -= 1

        if right < left:
            left = right = frame.x + max(0, (frame.w - 1) // 2)
        if bottom < top:
            top = bottom = frame.y + max(0, (frame.h - 1) // 2)

        content = Rect(left, top, max(1, right - left + 1), max(1, bottom - top + 1))
        pane.set_geometry(frame, content)


def _edge_has_owner(pane: Pane, panes: list[Pane], side: str) -> bool:
    frame = pane.frame_rect
    for other in panes:
        if other is pane:
            continue
        other_frame = other.frame_rect
        if side == "left":
            if other_frame.right == frame.x and _range_overlap(frame.y, frame.bottom, other_frame.y, other_frame.bottom) > 0:
                return True
        elif side == "right":
            if other_frame.x == frame.right and _range_overlap(frame.y, frame.bottom, other_frame.y, other_frame.bottom) > 0:
                return True
        elif side == "top":
            if other_frame.bottom == frame.y and _range_overlap(frame.x, frame.right, other_frame.x, other_frame.right) > 0:
                return True
        elif side == "bottom":
            if other_frame.y == frame.bottom and _range_overlap(frame.x, frame.right, other_frame.x, other_frame.right) > 0:
                return True
    return False


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


def remove_pane(root: SplitNode, target_pane_id: str) -> tuple[SplitNode | None, SplitNode | None]:
    """Remove a Leaf and collapse its parent Split.

    Returns (new_root, replacement_subtree). replacement_subtree is the
    subtree that replaced the removed pane's parent, useful for focus
    fallback after close.
    """
    new_root, removed, replacement = _remove_recursive(root, target_pane_id)
    if not removed:
        return root, None
    return new_root, replacement


def _remove_recursive(node: SplitNode, target: str) -> tuple[SplitNode | None, bool, SplitNode | None]:
    if isinstance(node, Leaf):
        if node.pane.pane_id == target:
            return None, True, None
        return node, False, None

    if isinstance(node, Split):
        new_first, removed_first, replacement_first = _remove_recursive(node.first, target)
        if removed_first:
            if new_first is None:
                return node.second, True, node.second
            node.first = new_first
            return node, True, replacement_first

        new_second, removed_second, replacement_second = _remove_recursive(node.second, target)
        if removed_second:
            if new_second is None:
                return node.first, True, node.first
            node.second = new_second
            return node, True, replacement_second

        return node, False, None

    return node, False, None


# ── Split ratio adjustment ──


def adjust_ratio(
    root: SplitNode,
    pane_id: str,
    direction: Direction,
    delta: float = 0.05,
) -> bool:
    """Adjust the nearest ancestor split on the requested axis.

    `direction` is the split axis to adjust:
    - Direction.VERTICAL   -> move a left/right divider
    - Direction.HORIZONTAL -> move an up/down divider

    Positive delta moves the divider toward the second pane (right/down),
    negative delta toward the first pane (left/up).
    """
    path = _path_to_pane(root, pane_id)
    if not path:
        return False

    for split in reversed(path):
        if split.direction != direction:
            continue

        bounds = _subtree_bounds(split)
        if bounds is None:
            return False

        total = bounds.w if direction == Direction.VERTICAL else bounds.h
        min_size = MIN_PANE_W if direction == Direction.VERTICAL else MIN_PANE_H
        if total < min_size * 2 + 1:
            return False

        min_ratio = (min_size + 1) / total
        max_ratio = (total - min_size) / total
        new_ratio = min(max(split.ratio + delta, min_ratio), max_ratio)
        if abs(new_ratio - split.ratio) < 1e-9:
            return False

        split.ratio = new_ratio
        return True

    return False


def _path_to_pane(node: SplitNode, pane_id: str) -> list[Split]:
    if isinstance(node, Leaf):
        return [] if node.pane.pane_id == pane_id else []

    if isinstance(node, Split):
        left_path = _path_to_pane(node.first, pane_id)
        if left_path or find_leaf(node.first, pane_id):
            return [*left_path, node]
        right_path = _path_to_pane(node.second, pane_id)
        if right_path or find_leaf(node.second, pane_id):
            return [*right_path, node]

    return []


def _subtree_bounds(node: SplitNode) -> Rect | None:
    panes = all_panes(node)
    if not panes:
        return None
    left = min(pane.frame_rect.x for pane in panes)
    top = min(pane.frame_rect.y for pane in panes)
    right = max(pane.frame_rect.right for pane in panes)
    bottom = max(pane.frame_rect.bottom for pane in panes)
    return Rect(left, top, right - left + 1, bottom - top + 1)


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
    source_rect = source_leaf.pane.frame_rect
    candidates: list[tuple[int, float, Pane]] = []
    for pane in all_panes(root):
        if pane.pane_id == pane_id:
            continue

        other = pane.frame_rect
        if direction == Direction.VERTICAL:
            if toward_second:
                if other.x != source_rect.right:
                    continue
            else:
                if other.right != source_rect.x:
                    continue
            overlap = _range_overlap(source_rect.y, source_rect.bottom, other.y, other.bottom)
            distance = abs(other.center_y - source_rect.center_y)
        else:
            if toward_second:
                if other.y != source_rect.bottom:
                    continue
            else:
                if other.bottom != source_rect.y:
                    continue
            overlap = _range_overlap(source_rect.x, source_rect.right, other.x, other.right)
            distance = abs(other.center_x - source_rect.center_x)

        if overlap <= 0:
            continue
        candidates.append((-overlap, distance, pane))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2].pane_id))
    return candidates[0][2]

def _range_overlap(a1: int, a2: int, b1: int, b2: int) -> int:
    start = max(a1, b1)
    end = min(a2, b2)
    return max(0, end - start + 1)


# ── Hit test (mouse click → pane) ──


def hit_test(node: SplitNode, x: int, y: int) -> Pane | None:
    """Find the pane at screen coordinates using content rects.

    Border cells are already excluded because hit-testing uses content_rect,
    not the visual frame rect. Bounds stay inclusive so 1xN / Nx1 content
    panes remain clickable without special casing.
    """
    if node is None:
        return None

    hits: list[Pane] = []
    for pane in all_panes(node):
        r = pane.content_rect
        inside = r.x <= x <= r.right and r.y <= y <= r.bottom
        if inside:
            hits.append(pane)

    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]
    hits.sort(key=lambda pane: abs(pane.content_rect.center_x - x) + abs(pane.content_rect.center_y - y))
    return hits[0]
