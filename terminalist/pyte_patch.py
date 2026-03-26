"""Pyte patches — color fixes + PreservingScreen.

1. Color names: Rich-compatible patches for pyte.graphics
2. PreservingScreen: HistoryScreen subclass that preserves content on resize

Call apply() once at startup, before any pyte Screen is created.
"""

from __future__ import annotations

import pyte


def apply() -> None:
    """Patch pyte.graphics color tables in-place."""
    import pyte.graphics as g

    # Fix ANSI basic: "brown" → "yellow" (color index 33/43)
    for table in (g.FG_ANSI, g.FG):
        if 33 in table:
            table[33] = "yellow"
    for table in (g.BG_ANSI, g.BG):
        if 43 in table:
            table[43] = "yellow"

    # Fix AIXTERM bright colors: add underscores for Rich compatibility
    # Also fixes pyte's "bfightmagenta" typo
    _BRIGHT_FG = {
        90: "bright_black",
        91: "bright_red",
        92: "bright_green",
        93: "bright_yellow",  # was "brightbrown"
        94: "bright_blue",
        95: "bright_magenta",  # was "bfightmagenta" (typo!)
        96: "bright_cyan",
        97: "bright_white",
    }
    _BRIGHT_BG = {k + 10: v for k, v in _BRIGHT_FG.items()}

    g.FG_AIXTERM.update(_BRIGHT_FG)
    g.BG_AIXTERM.update(_BRIGHT_BG)

    # Also patch the merged FG/BG dicts if they exist
    if hasattr(g, "FG"):
        g.FG.update(_BRIGHT_FG)
    if hasattr(g, "BG"):
        g.BG.update(_BRIGHT_BG)


import re

# Strip xterm private mode sequences that pyte misparses as SGR.
# e.g. \x1b[>4;2m (progressive enhancement) → pyte reads "4" as underscore.
_PRIVATE_MODE_RE = re.compile(r"\x1b\[>[0-9;]*m")


def filter_private_modes(data: str) -> str:
    """Remove xterm private mode sequences that confuse pyte's SGR parser."""
    return _PRIVATE_MODE_RE.sub("", data)


class PreservingScreen(pyte.HistoryScreen):
    """HistoryScreen that preserves content on vertical resize.

    pyte's HistoryScreen.resize() discards lines when shrinking vertically
    (pyte issue #31, open since 2015). This subclass pushes deleted top
    lines into history.top on shrink, and restores them on expand.

    Horizontal reflow is NOT handled — the PTY re-renders on SIGWINCH.
    """

    def resize(self, lines: int | None = None, columns: int | None = None) -> None:
        lines = lines or self.lines
        columns = columns or self.columns
        if lines == self.lines and columns == self.columns:
            return

        old_lines = self.lines

        # Shrink: save top lines that will be deleted
        if lines < old_lines:
            n_deleted = old_lines - lines
            for y in range(n_deleted):
                if y in self.buffer:
                    self.history.top.append(self.buffer[y])

        # Call base Screen.resize (skip HistoryScreen's version)
        pyte.Screen.resize(self, lines, columns)

        # Expand: restore lines from history
        if lines > old_lines and self.history.top:
            n_restore = min(lines - old_lines, len(self.history.top))
            if n_restore > 0:
                # Shift existing content down
                for y in range(lines - 1, n_restore - 1, -1):
                    src = y - n_restore
                    if src in self.buffer:
                        self.buffer[y] = self.buffer.pop(src)
                    else:
                        self.buffer.pop(y, None)
                # Fill top rows from history
                for y in range(n_restore - 1, -1, -1):
                    self.buffer[y] = self.history.top.pop()
                self.cursor.y = min(self.cursor.y + n_restore, lines - 1)
                self.dirty.update(range(lines))

        self.cursor.y = min(self.cursor.y, lines - 1)
        self.cursor.x = min(self.cursor.x, columns - 1)
