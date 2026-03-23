"""Screen sync — extract pyte Screen buffer as Char grid.

Converts pyte's internal buffer into a 2D list of pyte.screens.Char
that the compositor can place into a frame at a Rect offset.

CJK wide chars: pyte uses stub cells (data="") for the second column.
These are preserved in the grid (compositor handles them during rendering).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from pyte.screens import Char

if TYPE_CHECKING:
    import pyte


# Default empty char (matches pyte's default)
EMPTY_CHAR = Char(" ", "default", "default", False, False, False, False, False, False)


def extract_grid(screen: pyte.Screen, lock: threading.Lock) -> list[list[Char]]:
    """Extract full pyte screen → 2D Char grid.

    Acquires lock to read buffer atomically.
    Returns list[row][col] of Char objects.
    """
    with lock:
        rows = screen.lines
        cols = screen.columns
        grid: list[list[Char]] = []
        for y in range(rows):
            row: list[Char] = []
            buf_row = screen.buffer[y]
            for x in range(cols):
                try:
                    row.append(buf_row[x])
                except (IndexError, KeyError):
                    row.append(EMPTY_CHAR)
            grid.append(row)
        return grid


def extract_cursor(screen: pyte.Screen) -> tuple[int, int]:
    """Return cursor position (x, y) from pyte screen."""
    return (screen.cursor.x, screen.cursor.y)
