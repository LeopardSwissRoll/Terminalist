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

# Strip private/extended CSI sequences that pyte misparses.
# Covers:
#   \x1b[>4;2m  — xterm key modifier (pyte reads "4" as SGR underscore)
#   \x1b[>1u    — kitty push keyboard mode (pyte ignores ">", "u" becomes phantom char)
#   \x1b[<u     — kitty pop keyboard mode (pyte prints literal "u")
#   \x1b[>0q    — kitty query keyboard mode
# Pattern: CSI followed by private prefix (> < = !) then params then final byte.
_PRIVATE_CSI_RE = re.compile(r"\x1b\[[><=!][0-9;]*[A-Za-z~]")


def filter_private_modes(data: str) -> str:
    """Remove private CSI sequences that confuse pyte's parser."""
    return _PRIVATE_CSI_RE.sub("", data)


class PreservingScreen(pyte.HistoryScreen):
    """HistoryScreen that preserves content on vertical resize.

    pyte's HistoryScreen.resize() discards lines when shrinking vertically
    (pyte issue #31, open since 2015). This subclass handles shrink/expand
    without calling pyte.Screen.resize (which uses delete_lines and fails
    when the PTY has created empty buffer entries for all rows).

    Shrink strategy: keep the viewport window that includes the cursor row.
    Lines above the window go to history.top. Lines below are discarded.

    Horizontal reflow is NOT handled — the PTY re-renders on SIGWINCH.
    """

    def resize(self, lines: int | None = None, columns: int | None = None) -> None:
        lines = lines or self.lines
        columns = columns or self.columns
        if lines == self.lines and columns == self.columns:
            return

        old_lines = self.lines

        if lines < old_lines:
            self._resize_shrink(lines, columns, old_lines)
        elif lines > old_lines:
            self._resize_expand(lines, columns, old_lines)
        else:
            # Only columns changed — trim wider columns
            if columns < self.columns:
                for line in self.buffer.values():
                    for x in range(columns, self.columns):
                        line.pop(x, None)
            self.columns = columns

        self.cursor.y = min(self.cursor.y, lines - 1)
        self.cursor.x = min(self.cursor.x, columns - 1)
        self.dirty.update(range(lines))

    def _resize_shrink(self, lines: int, columns: int, old_lines: int) -> None:
        """Shrink: keep a window of `lines` rows centered on the cursor."""
        # Determine which rows to keep: a window of size `lines` that
        # includes cursor.y. Prefer keeping content ABOVE the cursor
        # (scrollback context) while ensuring cursor stays visible.
        cursor_y = self.cursor.y

        # Window end: at least cursor_y, at most old_lines - 1
        window_end = min(max(cursor_y, lines - 1), old_lines - 1)
        # Window start: window_end - lines + 1, at least 0
        window_start = max(window_end - lines + 1, 0)
        # Adjust end if start was clamped
        window_end = window_start + lines - 1

        # Save rows above the window to history
        for y in range(window_start):
            if y in self.buffer:
                self.history.top.append(self.buffer[y])

        # Build new buffer with only the window rows
        new_buf = type(self.buffer)(self.buffer.default_factory)
        for y in range(lines):
            src = window_start + y
            if src in self.buffer:
                new_buf[y] = self.buffer[src]
            # else: leave as default empty row

        # Trim columns if needed
        if columns < self.columns:
            for line in new_buf.values():
                for x in range(columns, self.columns):
                    line.pop(x, None)

        self.buffer = new_buf
        self.lines = lines
        self.columns = columns
        self.set_margins()

        # Adjust cursor position relative to the new window
        self.cursor.y = cursor_y - window_start

    def _resize_expand(self, lines: int, columns: int, old_lines: int) -> None:
        """Expand: restore lines from history into the top."""
        # Handle column changes via base resize
        pyte.Screen.resize(self, lines, columns)

        if self.history.top:
            n_restore = min(lines - old_lines, len(self.history.top))
            if n_restore > 0:
                # Shift existing content down to make room at top
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
