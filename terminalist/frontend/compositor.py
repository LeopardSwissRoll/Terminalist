"""Compositor — merge pane screens into a frame and render via VT100 diff.

1. Extracts each pane's pyte screen → Char grid (via screen_sync)
2. Places cells into a full-screen frame at each pane's Rect offset
3. Builds border overlay via mask/owner cells
4. Diffs against prev_frame — emits VT100 only for changed cells
5. Positions hardware cursor at focused pane's cursor location
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from pyte.screens import Char

from terminalist.core.pane import Pane, Rect
from terminalist.debug import dump_render_snapshot, is_enabled, log
from terminalist.frontend.screen_sync import EMPTY_CHAR
from terminalist.frontend.split_tree import (
    SplitNode,
    all_panes,
)
from terminalist.frontend.vt100_writer import VT100Writer

U = 1 << 0
D = 1 << 1
L = 1 << 2
R = 1 << 3


@dataclass(frozen=True)
class MaskCell:
    mask: int
    owners: frozenset[str]


@lru_cache(maxsize=None)
def _border_char(glyph: str, active: bool) -> Char:
    fg = "green" if active else "bright_black"
    return Char(glyph, fg, "default", active, False, False, False, False, False)


BORDER_V_CHAR = _border_char("│", False)
BORDER_H_CHAR = _border_char("─", False)
BORDER_V_ACTIVE = _border_char("│", True)
BORDER_H_ACTIVE = _border_char("─", True)



class Compositor:
    """Merge pane screens into a frame, diff render to terminal."""

    def __init__(
        self,
        width: int,
        height: int,
        writer: VT100Writer,
        show_root_border: bool = False,
    ) -> None:
        self._width = width
        self._height = height
        self._writer = writer
        self._show_root_border = show_root_border
        self._prev_frame: list[list[Char]] | None = None
        self._dirty = True  # start dirty for initial render

    def mark_dirty(self) -> None:
        """Called by dirty listeners. Thread-safe (GIL protects bool)."""
        self._dirty = True

    def needs_render(self) -> bool:
        return self._dirty

    def resize(self, width: int, height: int) -> None:
        """Terminal resized. Invalidates prev_frame for full redraw."""
        self._width = width
        self._height = height
        self._prev_frame = None
        self._dirty = True
        log("render", f"Compositor resize: {width}x{height}")

    def compose(
        self,
        root: SplitNode,
        rect: Rect,
        focused_pane: Pane | None = None,
        status_line: list[Char] | None = None,
        status_y: int | None = None,
    ) -> list[list[Char]]:
        """Build the full frame from split tree.

        1. Fill with EMPTY_CHAR
        2. For each Leaf, copy pyte grid at content Rect offset
        3. Build border mask/owner overlay and draw glyphs
        """
        # Initialize frame
        frame = [[EMPTY_CHAR] * self._width for _ in range(self._height)]

        panes = all_panes(root)

        # Copy pane contents (clipped to Rect bounds)
        # pyte screen size may temporarily differ from Rect after resize,
        # so we clip to min(grid_size, rect_size) to prevent leaking.
        for pane in panes:
            r = pane.content_rect
            grid, _, _, _, _ = pane.session.get_screen_snapshot(scroll_offset=pane.scroll_offset)

            max_rows = min(len(grid), r.h)
            for gy in range(max_rows):
                fy = r.y + gy
                if fy >= self._height:
                    break
                row = grid[gy]
                max_cols = min(len(row), r.w)
                for gx in range(max_cols):
                    fx = r.x + gx
                    if fx >= self._width:
                        break
                    frame[fy][fx] = row[gx]

        focused_id = focused_pane.pane_id if focused_pane else None
        for y, row in enumerate(self._build_border_grid(panes)):
            for x, cell in enumerate(row):
                if cell.mask == 0:
                    continue
                glyph = _glyph_for_mask(cell.mask)
                active = focused_id is not None and focused_id in cell.owners
                frame[y][x] = _border_char(glyph, active)

        if status_line is not None and status_y is not None:
            self.render_status_line(status_line, status_y, frame)

        return frame

    def render(
        self,
        root: SplitNode,
        rect: Rect,
        focused_pane: Pane | None = None,
        status_line: list[Char] | None = None,
        status_y: int | None = None,
    ) -> None:
        """Full render cycle: compose → diff → VT100 output."""
        try:
            curr_frame = self.compose(
                root,
                rect,
                focused_pane,
                status_line=status_line,
                status_y=status_y,
            )
            prev = self._prev_frame

            self._writer.hide_cursor()

            # Diff and emit
            cells_written = 0
            for y in range(self._height):
                for x in range(self._width):
                    curr = curr_frame[y][x]
                    if prev is not None:
                        try:
                            old = prev[y][x]
                        except IndexError:
                            old = None  # prev_frame size mismatch after resize
                        if old is not None:
                            if curr is old:
                                continue
                            if curr == old:
                                continue

                    # CJK stub cell — don't emit (terminal handles wide char)
                    if curr.data == "":
                        continue

                    self._writer.move_to(x, y)
                    self._writer.set_attrs(curr)
                    self._writer.write_char(curr.data)
                    cells_written += 1

            # Position cursor at focused pane
            if focused_pane and not focused_pane.in_copy_mode:
                _, cx, cy, _, _ = focused_pane.session.get_screen_snapshot(
                    scroll_offset=focused_pane.scroll_offset,
                )
                if cx >= 0 and cy >= 0:
                    r = focused_pane.content_rect
                    self._writer.move_to(r.x + cx, r.y + cy)
                    cursor = (r.x + cx, r.y + cy)
                else:
                    cursor = None
            else:
                cursor = None

            self._writer.reset_attrs()
            self._writer.show_cursor()
            vt100_output = self._writer.peek_buffer()
            self._writer.flush()
            self._prev_frame = curr_frame
            self._dirty = False

            if is_enabled():
                dump_render_snapshot(
                    curr_frame,
                    self._width,
                    self._height,
                    vt100_output,
                    focused_pane_id=focused_pane.pane_id if focused_pane else None,
                    cursor=cursor,
                )

            if cells_written > 0:
                log("render", f"Rendered {cells_written} cells ({self._width}x{self._height})")
        except Exception as e:
            log("render", f"RENDER ERROR: {type(e).__name__}: {e}")
            import traceback
            log("render", traceback.format_exc())
            # Try to recover: show cursor, flush partial output
            try:
                self._writer.show_cursor()
                self._writer.flush()
            except Exception:
                pass
            self._dirty = True  # retry next tick

    def full_redraw(self) -> None:
        """Force full redraw on next render."""
        self._prev_frame = None
        self._dirty = True

    def render_status_line(
        self,
        chars: list[Char],
        y: int,
        frame: list[list[Char]] | None = None,
    ) -> list[list[Char]]:
        """Overlay a status line onto a frame.

        If `frame` is None, creates a blank frame of compositor size first.
        """
        target = frame or [[EMPTY_CHAR] * self._width for _ in range(self._height)]
        if not (0 <= y < self._height):
            return target

        row = target[y]
        limit = min(self._width, len(chars))
        for x in range(limit):
            row[x] = chars[x]
        return target

    def _build_border_grid(self, panes: list[Pane]) -> list[list[MaskCell]]:
        mask_grid = [[0 for _ in range(self._width)] for _ in range(self._height)]
        owner_grid = [[set() for _ in range(self._width)] for _ in range(self._height)]
        if not panes:
            return [
                [MaskCell(mask_grid[y][x], frozenset(owner_grid[y][x])) for x in range(self._width)]
                for y in range(self._height)
            ]

        root_left = min(pane.frame_rect.x for pane in panes)
        root_top = min(pane.frame_rect.y for pane in panes)
        root_right = max(pane.frame_rect.right for pane in panes)
        root_bottom = max(pane.frame_rect.bottom for pane in panes)

        for pane in panes:
            frame = pane.frame_rect
            if self._should_draw_edge(pane, panes, "top", root_left, root_top, root_right, root_bottom):
                self._add_h_segment(mask_grid, owner_grid, frame.y, frame.x, frame.right, pane.pane_id)
            if self._should_draw_edge(pane, panes, "bottom", root_left, root_top, root_right, root_bottom):
                self._add_h_segment(mask_grid, owner_grid, frame.bottom, frame.x, frame.right, pane.pane_id)
            if self._should_draw_edge(pane, panes, "left", root_left, root_top, root_right, root_bottom):
                self._add_v_segment(mask_grid, owner_grid, frame.x, frame.y, frame.bottom, pane.pane_id)
            if self._should_draw_edge(pane, panes, "right", root_left, root_top, root_right, root_bottom):
                self._add_v_segment(mask_grid, owner_grid, frame.right, frame.y, frame.bottom, pane.pane_id)

        return [
            [MaskCell(mask_grid[y][x], frozenset(owner_grid[y][x])) for x in range(self._width)]
            for y in range(self._height)
        ]

    def _should_draw_edge(
        self,
        pane: Pane,
        panes: list[Pane],
        side: str,
        root_left: int,
        root_top: int,
        root_right: int,
        root_bottom: int,
    ) -> bool:
        frame = pane.frame_rect
        if side == "left":
            shared = any(
                other is not pane
                and other.frame_rect.right == frame.x
                and _range_overlap(frame.y, frame.bottom, other.frame_rect.y, other.frame_rect.bottom) > 0
                for other in panes
            )
            return shared or (self._show_root_border and frame.x == root_left)
        if side == "right":
            shared = any(
                other is not pane
                and other.frame_rect.x == frame.right
                and _range_overlap(frame.y, frame.bottom, other.frame_rect.y, other.frame_rect.bottom) > 0
                for other in panes
            )
            return shared or (self._show_root_border and frame.right == root_right)
        if side == "top":
            shared = any(
                other is not pane
                and other.frame_rect.bottom == frame.y
                and _range_overlap(frame.x, frame.right, other.frame_rect.x, other.frame_rect.right) > 0
                for other in panes
            )
            return shared or (self._show_root_border and frame.y == root_top)

        shared = any(
            other is not pane
            and other.frame_rect.y == frame.bottom
            and _range_overlap(frame.x, frame.right, other.frame_rect.x, other.frame_rect.right) > 0
            for other in panes
        )
        return shared or (self._show_root_border and frame.bottom == root_bottom)

    @staticmethod
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

    @staticmethod
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


def _range_overlap(a1: int, a2: int, b1: int, b2: int) -> int:
    start = max(a1, b1)
    end = min(a2, b2)
    return max(0, end - start + 1)


def _glyph_for_mask(mask: int) -> str:
    mapping = {
        L | R: "─",
        U | D: "│",
        U: "│",
        D: "│",
        L: "─",
        R: "─",
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
