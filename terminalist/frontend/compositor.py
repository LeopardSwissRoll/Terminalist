"""Compositor — merge pane screens into a frame and render via VT100 diff.

1. Extracts each pane's pyte screen → Char grid (via screen_sync)
2. Places cells into a full-screen frame at each pane's Rect offset
3. Draws border characters between splits
4. Diffs against prev_frame — emits VT100 only for changed cells
5. Positions hardware cursor at focused pane's cursor location
"""

from __future__ import annotations

from pyte.screens import Char

from terminalist.core.pane import Pane, Rect
from terminalist.debug import log
from terminalist.frontend.screen_sync import EMPTY_CHAR
from terminalist.frontend.split_tree import (
    BorderSegment,
    Direction,
    Leaf,
    Split,
    SplitNode,
    all_panes,
    borders,
)
from terminalist.frontend.vt100_writer import VT100Writer

# ── Border characters ──

BORDER_V_CHAR = Char("│", "white", "default", False, False, False, False, False, False)
BORDER_H_CHAR = Char("─", "white", "default", False, False, False, False, False, False)
BORDER_CROSS = Char("┼", "white", "default", False, False, False, False, False, False)

# Active pane border (brighter)
BORDER_V_ACTIVE = Char("│", "bright_white", "default", True, False, False, False, False, False)
BORDER_H_ACTIVE = Char("─", "bright_white", "default", True, False, False, False, False, False)


class Compositor:
    """Merge pane screens into a frame, diff render to terminal."""

    def __init__(self, width: int, height: int, writer: VT100Writer) -> None:
        self._width = width
        self._height = height
        self._writer = writer
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
    ) -> list[list[Char]]:
        """Build the full frame from split tree.

        1. Fill with EMPTY_CHAR
        2. For each Leaf, copy pyte grid at Rect offset
        3. Draw borders
        """
        # Initialize frame
        frame = [[EMPTY_CHAR] * self._width for _ in range(self._height)]

        # Copy pane contents (clipped to Rect bounds)
        # pyte screen size may temporarily differ from Rect after resize,
        # so we clip to min(grid_size, rect_size) to prevent leaking.
        for pane in all_panes(root):
            r = pane.rect
            grid, _, _, _, _ = pane.session.get_screen_snapshot()

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

        # Draw borders
        border_segs = borders(root, rect)
        for seg in border_segs:
            if seg.direction == Direction.VERTICAL:
                char = BORDER_V_CHAR
                for i in range(seg.length):
                    y = seg.y + i
                    if 0 <= y < self._height and 0 <= seg.x < self._width:
                        frame[y][seg.x] = char
            else:  # HORIZONTAL
                char = BORDER_H_CHAR
                for i in range(seg.length):
                    x = seg.x + i
                    if 0 <= x < self._width and 0 <= seg.y < self._height:
                        frame[seg.y][x] = char

        return frame

    def render(
        self,
        root: SplitNode,
        rect: Rect,
        focused_pane: Pane | None = None,
    ) -> None:
        """Full render cycle: compose → diff → VT100 output."""
        try:
            curr_frame = self.compose(root, rect, focused_pane)
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
            if focused_pane:
                cx, cy = focused_pane.get_cursor()
                r = focused_pane.rect
                self._writer.move_to(r.x + cx, r.y + cy)

            self._writer.reset_attrs()
            self._writer.show_cursor()
            self._writer.flush()
            self._prev_frame = curr_frame
            self._dirty = False

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
