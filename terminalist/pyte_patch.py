"""Patch pyte.graphics color names to be Rich-compatible.

pyte uses non-standard color names that Rich's Color.parse() doesn't understand:
  - "brown" → Rich expects "yellow"
  - "brightbrown" → Rich expects "bright_yellow"
  - "bfightmagenta" → typo in pyte, should be "bright_magenta"

This monkey-patches pyte.graphics at import time so all color names
are Rich-compatible from the source, eliminating the need for a
runtime translation table in terminal_pane.py.

Call apply() once at startup, before any pyte Screen is created.
"""

from __future__ import annotations


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
