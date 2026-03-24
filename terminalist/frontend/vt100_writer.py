"""VT100 writer — buffered escape sequence output.

Accumulates VT100 escape sequences into a list, flushes with single write.
Implements attribute batching (skip SGR if unchanged from previous cell).
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyte.screens import Char

# ── ANSI color name → SGR code ──

_FG_CODES: dict[str, str] = {
    "default": "39",
    "black": "30", "red": "31", "green": "32", "yellow": "33",
    "blue": "34", "magenta": "35", "cyan": "36", "white": "37",
    "bright_black": "90", "bright_red": "91", "bright_green": "92",
    "bright_yellow": "93", "bright_blue": "94", "bright_magenta": "95",
    "bright_cyan": "96", "bright_white": "97",
}

_BG_CODES: dict[str, str] = {
    "default": "49",
    "black": "40", "red": "41", "green": "42", "yellow": "43",
    "blue": "44", "magenta": "45", "cyan": "46", "white": "47",
    "bright_black": "100", "bright_red": "101", "bright_green": "102",
    "bright_yellow": "103", "bright_blue": "104", "bright_magenta": "105",
    "bright_cyan": "106", "bright_white": "107",
}


def _fg_sgr(color: str) -> str:
    """Convert fg color to SGR parameter string.

    pyte stores colors as:
    - "default", "red", "bright_cyan" etc. → named ANSI
    - "ff8000" (6 hex digits, NO #) → 24-bit color
    - "#rrggbb" (with #) → also 24-bit (just in case)
    """
    if color in _FG_CODES:
        return _FG_CODES[color]
    # 24-bit hex: pyte stores as "rrggbb" (no #) or "#rrggbb"
    hex_color = color.lstrip("#")
    if len(hex_color) == 6:
        try:
            r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
            return f"38;2;{r};{g};{b}"
        except ValueError:
            pass
    try:
        return f"38;5;{int(color)}"
    except ValueError:
        return "39"


def _bg_sgr(color: str) -> str:
    """Convert bg color to SGR parameter string."""
    if color in _BG_CODES:
        return _BG_CODES[color]
    hex_color = color.lstrip("#")
    if len(hex_color) == 6:
        try:
            r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
            return f"48;2;{r};{g};{b}"
        except ValueError:
            pass
    try:
        return f"48;5;{int(color)}"
    except ValueError:
        return "49"


class VT100Writer:
    """Buffered VT100 output writer.

    Usage:
        w = VT100Writer()
        w.hide_cursor()
        w.move_to(0, 0)
        w.set_attrs(char)
        w.write_char("A")
        w.show_cursor()
        w.flush()
    """

    def __init__(self, fd: int | None = None) -> None:
        self._fd = fd  # None = use sys.stdout.write
        self._buf: list[str] = []
        self._last_fg: str = ""
        self._last_bg: str = ""
        self._last_bold: bool = False
        self._last_italics: bool = False
        self._last_underscore: bool = False
        self._last_strikethrough: bool = False
        self._last_reverse: bool = False
        self._last_blink: bool = False
        self._cursor_x: int = -1
        self._cursor_y: int = -1

    def move_to(self, x: int, y: int) -> None:
        """Emit cursor positioning (1-indexed for VT100)."""
        if x == self._cursor_x and y == self._cursor_y:
            return
        self._buf.append(f"\x1b[{y + 1};{x + 1}H")
        self._cursor_x = x
        self._cursor_y = y

    def set_attrs(self, char: Char) -> None:
        """Emit SGR sequence if attributes changed from last call."""
        if (char.fg == self._last_fg and char.bg == self._last_bg
                and char.bold == self._last_bold and char.italics == self._last_italics
                and char.underscore == self._last_underscore
                and char.strikethrough == self._last_strikethrough
                and char.reverse == self._last_reverse and char.blink == self._last_blink):
            return

        parts: list[str] = ["0"]  # reset first
        if char.bold:
            parts.append("1")
        if char.italics:
            parts.append("3")
        if char.underscore:
            parts.append("4")
        if char.blink:
            parts.append("5")
        if char.reverse:
            parts.append("7")
        if char.strikethrough:
            parts.append("9")
        parts.append(_fg_sgr(char.fg))
        parts.append(_bg_sgr(char.bg))

        self._buf.append(f"\x1b[{';'.join(parts)}m")

        self._last_fg = char.fg
        self._last_bg = char.bg
        self._last_bold = char.bold
        self._last_italics = char.italics
        self._last_underscore = char.underscore
        self._last_strikethrough = char.strikethrough
        self._last_reverse = char.reverse
        self._last_blink = char.blink

    def write_char(self, ch: str) -> None:
        """Append character. Advances internal cursor tracking."""
        self._buf.append(ch)
        self._cursor_x += 1

    def reset_attrs(self) -> None:
        """Emit SGR reset."""
        self._buf.append("\x1b[0m")
        self._last_fg = ""
        self._last_bg = ""
        self._last_bold = False
        self._last_italics = False
        self._last_underscore = False
        self._last_strikethrough = False
        self._last_reverse = False
        self._last_blink = False

    def hide_cursor(self) -> None:
        self._buf.append("\x1b[?25l")

    def show_cursor(self) -> None:
        self._buf.append("\x1b[?25h")

    def flush(self) -> None:
        """Join buffer and write in one syscall."""
        if not self._buf:
            return
        data = "".join(self._buf)
        self._buf.clear()
        if self._fd is not None:
            os.write(self._fd, data.encode("utf-8"))
        else:
            sys.stdout.write(data)
            sys.stdout.flush()

    def clear(self) -> None:
        """Reset internal state (for testing or full redraw)."""
        self._buf.clear()
        self._last_fg = ""
        self._last_bg = ""
        self._last_bold = False
        self._last_italics = False
        self._last_underscore = False
        self._last_strikethrough = False
        self._last_reverse = False
        self._last_blink = False
        self._cursor_x = -1
        self._cursor_y = -1
