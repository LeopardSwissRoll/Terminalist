"""Mask/owner based renderer for TestPane."""

from __future__ import annotations

from dataclasses import dataclass

from Test.TestPane.layout import collect_leaves
from Test.TestPane.model import Rect, SplitNode

U = 1 << 0
D = 1 << 1
L = 1 << 2
R = 1 << 3


@dataclass(frozen=True)
class MaskCell:
    mask: int
    owners: frozenset[str]


@dataclass(frozen=True)
class RenderCell:
    ch: str
    style: str


STYLE_TO_ANSI = {
    "blank": "\x1b[0m",
    "fill_active": "\x1b[92m",
    "fill_inactive": "\x1b[90m",
    "label_active": "\x1b[1;97m",
    "label_inactive": "\x1b[37m",
    "border_active": "\x1b[1;92m",
    "border_inactive": "\x1b[90m",
}


def build_border_grid(root: SplitNode, width: int, height: int) -> list[list[MaskCell]]:
    mask_grid = [[0 for _ in range(width)] for _ in range(height)]
    owner_grid = [[set() for _ in range(width)] for _ in range(height)]

    for pane in collect_leaves(root):
        rect = pane.rect
        _add_h_segment(mask_grid, owner_grid, rect.y, rect.x, rect.right, pane.pane_id)
        _add_h_segment(mask_grid, owner_grid, rect.bottom, rect.x, rect.right, pane.pane_id)
        _add_v_segment(mask_grid, owner_grid, rect.x, rect.y, rect.bottom, pane.pane_id)
        _add_v_segment(mask_grid, owner_grid, rect.right, rect.y, rect.bottom, pane.pane_id)

    return [
        [MaskCell(mask_grid[y][x], frozenset(owner_grid[y][x])) for x in range(width)]
        for y in range(height)
    ]


def compose(root: SplitNode, focused_id: str, width: int, height: int) -> list[list[RenderCell]]:
    frame = [[RenderCell(" ", "blank") for _ in range(width)] for _ in range(height)]

    for pane in collect_leaves(root):
        is_focused = pane.pane_id == focused_id
        _fill_interior(frame, pane.rect, is_focused)
        _place_label(frame, pane.rect, pane.label, is_focused)

    border_grid = build_border_grid(root, width, height)
    for y in range(height):
        for x in range(width):
            cell = border_grid[y][x]
            if cell.mask == 0:
                continue
            style = "border_active" if focused_id in cell.owners else "border_inactive"
            frame[y][x] = RenderCell(_glyph_for_mask(cell.mask), style)

    return frame


def frame_to_ansi(frame: list[list[RenderCell]]) -> str:
    parts: list[str] = ["\x1b[H"]
    current_style = "blank"
    parts.append(STYLE_TO_ANSI[current_style])
    for row in frame:
        for cell in row:
            if cell.style != current_style:
                current_style = cell.style
                parts.append(STYLE_TO_ANSI[current_style])
            parts.append(cell.ch)
        parts.append("\x1b[0m\n")
        current_style = "blank"
        parts.append(STYLE_TO_ANSI[current_style])
    parts.append("\x1b[0m")
    return "".join(parts)


def frame_to_plain_text(frame: list[list[RenderCell]]) -> str:
    return "\n".join("".join(cell.ch for cell in row) for row in frame)


def _fill_interior(frame: list[list[RenderCell]], rect: Rect, is_focused: bool) -> None:
    fill = "#" if is_focused else "."
    style = "fill_active" if is_focused else "fill_inactive"
    for y in range(rect.y + 1, rect.bottom):
        if not (0 <= y < len(frame)):
            continue
        for x in range(rect.x + 1, rect.right):
            if 0 <= x < len(frame[y]):
                frame[y][x] = RenderCell(fill, style)


def _place_label(frame: list[list[RenderCell]], rect: Rect, label: str, is_focused: bool) -> None:
    inner_w = rect.w - 2
    inner_h = rect.h - 2
    if inner_w <= 0 or inner_h <= 0:
        return

    text = label.upper() if is_focused else label.lower()
    text = text[:inner_w]
    y = rect.y + 1 + (inner_h - 1) // 2
    x = rect.x + 1 + max(0, (inner_w - len(text)) // 2)
    style = "label_active" if is_focused else "label_inactive"
    if not (0 <= y < len(frame)):
        return
    for idx, ch in enumerate(text):
        draw_x = x + idx
        if 0 <= draw_x < len(frame[y]):
            frame[y][draw_x] = RenderCell(ch, style)


def _add_h_segment(
    mask_grid: list[list[int]],
    owner_grid: list[list[set[str]]],
    y: int,
    x1: int,
    x2: int,
    pane_id: str,
) -> None:
    if not (0 <= y < len(mask_grid)):
        return
    start = max(0, x1)
    end = min(len(mask_grid[y]) - 1, x2)
    for x in range(start, end + 1):
        if x > start:
            mask_grid[y][x] |= L
        if x < end:
            mask_grid[y][x] |= R
        owner_grid[y][x].add(pane_id)


def _add_v_segment(
    mask_grid: list[list[int]],
    owner_grid: list[list[set[str]]],
    x: int,
    y1: int,
    y2: int,
    pane_id: str,
) -> None:
    if not mask_grid or not (0 <= x < len(mask_grid[0])):
        return
    start = max(0, y1)
    end = min(len(mask_grid) - 1, y2)
    for y in range(start, end + 1):
        if y > start:
            mask_grid[y][x] |= U
        if y < end:
            mask_grid[y][x] |= D
        owner_grid[y][x].add(pane_id)


def _glyph_for_mask(mask: int) -> str:
    mapping = {
        L | R: "─",
        U | D: "│",
        D | R: "┌",
        D | L: "┐",
        U | R: "└",
        U | L: "┘",
        U | D | R: "├",
        U | D | L: "┤",
        L | R | D: "┬",
        L | R | U: "┴",
        U | D | L | R: "┼",
    }
    return mapping.get(mask, " ")
