"""Pane tree layout and navigation logic for TestPane."""

from __future__ import annotations

import re

from Test.TestPane.model import Direction, Leaf, MoveDirection, Pane, Rect, Split, SplitNode


PANE_ID_RE = re.compile(r"^p(\d+)$")


def can_split(rect: Rect, direction: Direction) -> bool:
    if direction == Direction.VERTICAL:
        return rect.w >= 3
    return rect.h >= 3


def layout(node: SplitNode, rect: Rect) -> None:
    if isinstance(node, Leaf):
        node.pane.rect = rect
        return

    if node.direction == Direction.VERTICAL:
        mid_x = rect.x + (rect.w - 1) // 2
        first = Rect(rect.x, rect.y, mid_x - rect.x + 1, rect.h)
        second = Rect(mid_x, rect.y, rect.right - mid_x + 1, rect.h)
    else:
        mid_y = rect.y + (rect.h - 1) // 2
        first = Rect(rect.x, rect.y, rect.w, mid_y - rect.y + 1)
        second = Rect(rect.x, mid_y, rect.w, rect.bottom - mid_y + 1)

    layout(node.first, first)
    layout(node.second, second)


def collect_leaves(node: SplitNode | None) -> list[Pane]:
    if node is None:
        return []
    if isinstance(node, Leaf):
        return [node.pane]
    return collect_leaves(node.first) + collect_leaves(node.second)


def first_leaf(node: SplitNode | None) -> Pane | None:
    if node is None:
        return None
    if isinstance(node, Leaf):
        return node.pane
    return first_leaf(node.first) or first_leaf(node.second)


def find_leaf(node: SplitNode | None, pane_id: str) -> Leaf | None:
    if node is None:
        return None
    if isinstance(node, Leaf):
        return node if node.pane.pane_id == pane_id else None
    return find_leaf(node.first, pane_id) or find_leaf(node.second, pane_id)


def hit_test(node: SplitNode | None, x: int, y: int) -> str | None:
    """Return pane_id for a click inside a pane's interior.

    Shared-boundary rects make border cells ambiguous, so we prefer the
    true interior. Degenerate panes with no interior fall back to an
    inclusive bounds check so they remain clickable.
    """
    hits: list[Pane] = []
    for pane in collect_leaves(node):
        rect = pane.rect
        if rect.w <= 2 or rect.h <= 2:
            inside = rect.x <= x <= rect.right and rect.y <= y <= rect.bottom
        else:
            inside = rect.x < x < rect.right and rect.y < y < rect.bottom
        if inside:
            hits.append(pane)

    if not hits:
        return None
    if len(hits) == 1:
        return hits[0].pane_id

    hits.sort(key=lambda pane: abs(pane.rect.center_x - x) + abs(pane.rect.center_y - y))
    return hits[0].pane_id


def split_leaf(
    root: SplitNode,
    pane_id: str,
    direction: Direction,
) -> tuple[SplitNode, str | None]:
    target = find_leaf(root, pane_id)
    if target is None or not can_split(target.pane.rect, direction):
        return root, None

    new_pane_id = _next_pane_id(root)
    new_leaf = Leaf(Pane(new_pane_id, new_pane_id, target.pane.rect))
    new_root, changed = _split_recursive(root, pane_id, direction, new_leaf)
    if not changed:
        return root, None
    return new_root, new_pane_id


def _split_recursive(
    node: SplitNode,
    pane_id: str,
    direction: Direction,
    new_leaf: Leaf,
) -> tuple[SplitNode, bool]:
    if isinstance(node, Leaf):
        if node.pane.pane_id != pane_id:
            return node, False
        return Split(direction=direction, first=node, second=new_leaf), True

    new_first, changed = _split_recursive(node.first, pane_id, direction, new_leaf)
    if changed:
        node.first = new_first
        return node, True

    new_second, changed = _split_recursive(node.second, pane_id, direction, new_leaf)
    if changed:
        node.second = new_second
        return node, True

    return node, False


def close_leaf(root: SplitNode, pane_id: str) -> tuple[SplitNode | None, SplitNode | None]:
    new_root, removed, replacement = _close_recursive(root, pane_id)
    if not removed:
        return root, None
    return new_root, replacement


def _close_recursive(node: SplitNode, pane_id: str) -> tuple[SplitNode | None, bool, SplitNode | None]:
    if isinstance(node, Leaf):
        if node.pane.pane_id == pane_id:
            return None, True, None
        return node, False, None

    new_first, removed_first, repl_first = _close_recursive(node.first, pane_id)
    if removed_first:
        if new_first is None:
            return node.second, True, node.second
        node.first = new_first
        return node, True, repl_first

    new_second, removed_second, repl_second = _close_recursive(node.second, pane_id)
    if removed_second:
        if new_second is None:
            return node.first, True, node.first
        node.second = new_second
        return node, True, repl_second

    return node, False, None


def find_neighbor(root: SplitNode, pane_id: str, direction: MoveDirection) -> str | None:
    source = find_leaf(root, pane_id)
    if source is None:
        return None

    source_rect = source.pane.rect
    candidates: list[tuple[int, float, str]] = []
    for pane in collect_leaves(root):
        if pane.pane_id == pane_id:
            continue

        overlap = _candidate_overlap(source_rect, pane.rect, direction)
        if overlap <= 0:
            continue

        distance = _candidate_distance(source_rect, pane.rect, direction)
        candidates.append((-overlap, distance, pane.pane_id))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def _candidate_overlap(source: Rect, other: Rect, direction: MoveDirection) -> int:
    if direction == MoveDirection.RIGHT:
        if other.x != source.right:
            return 0
        return _overlap(source.y, source.bottom, other.y, other.bottom)
    if direction == MoveDirection.LEFT:
        if other.right != source.x:
            return 0
        return _overlap(source.y, source.bottom, other.y, other.bottom)
    if direction == MoveDirection.DOWN:
        if other.y != source.bottom:
            return 0
        return _overlap(source.x, source.right, other.x, other.right)
    if other.bottom != source.y:
        return 0
    return _overlap(source.x, source.right, other.x, other.right)


def _candidate_distance(source: Rect, other: Rect, direction: MoveDirection) -> float:
    if direction in (MoveDirection.LEFT, MoveDirection.RIGHT):
        return abs(other.center_y - source.center_y)
    return abs(other.center_x - source.center_x)


def _overlap(a1: int, a2: int, b1: int, b2: int) -> int:
    start = max(a1, b1)
    end = min(a2, b2)
    return max(0, end - start + 1)


def _next_pane_id(root: SplitNode) -> str:
    highest = 0
    for pane in collect_leaves(root):
        match = PANE_ID_RE.match(pane.pane_id)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"p{highest + 1}"
