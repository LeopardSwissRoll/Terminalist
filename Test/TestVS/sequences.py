"""Catalog of escape sequences seen from VSCode/Claude/Codex PTY output.

- SHOULD_IGNORE entries: (sequence, source, description)
- NORMAL entries: (sequence, description)
"""

from __future__ import annotations

from typing import TypeAlias

IgnoreSequence: TypeAlias = tuple[str, str, str]
NormalSequence: TypeAlias = tuple[str, str]

# Sequences that pyte should IGNORE (private modes, kitty protocol, etc.)
# These are the ones that cause phantom characters or attribute contamination.
SHOULD_IGNORE: list[IgnoreSequence] = [
    # Kitty keyboard protocol
    ("\x1b[>1u",      "claude",  "kitty: push keyboard mode"),
    ("\x1b[<u",       "claude",  "kitty: pop keyboard mode"),
    ("\x1b[>0q",      "claude",  "kitty: query keyboard mode"),

    # xterm private mode SGR (progressive enhancement)
    ("\x1b[>4;2m",    "claude",  "xterm: set key modifier options (misread as SGR 4=underscore)"),
    ("\x1b[>4m",      "claude",  "xterm: reset key modifier options"),

    # Synchronized update (DEC private)
    ("\x1b[?2026h",   "claude",  "synchronized update: begin"),
    ("\x1b[?2026l",   "claude",  "synchronized update: end"),

    # Focus reporting
    ("\x1b[?1004h",   "all",     "focus: enable focus reporting"),
    ("\x1b[?1004l",   "claude",  "focus: disable focus reporting"),

    # Win32 input mode
    ("\x1b[?9001h",   "powershell", "win32: enable win32 input mode"),

    # Mouse mode (host manages these, child shouldn't override)
    ("\x1b[?1000l",   "claude",  "mouse: disable normal tracking"),
    ("\x1b[?1002l",   "claude",  "mouse: disable button tracking"),
    ("\x1b[?1003l",   "claude",  "mouse: disable all-motion tracking"),
    ("\x1b[?1006l",   "claude",  "mouse: disable SGR mode"),

    # Device attributes request (causes DA response pollution)
    ("\x1b[c",        "all",     "DA: primary device attributes request"),

    # xterm window ops
    ("\x1b[1t",       "powershell", "xterm: de-iconify window"),

    # OSC title set (should be consumed by pyte, not displayed)
    ("\x1b]9;4;0;\x07", "powershell", "ConEmu: progress notification"),
]

# Sequences that pyte handles correctly (no filtering needed)
NORMAL: list[NormalSequence] = [
    # Cursor movement
    ("\x1b[H",       "cursor home"),
    ("\x1b[2J",      "clear screen"),
    ("\x1b[K",       "clear to end of line"),
    ("\x1b[J",       "clear to end of screen"),

    # SGR (colors, attributes)
    ("\x1b[0m",      "reset attributes"),
    ("\x1b[1m",      "bold"),
    ("\x1b[39m",     "default fg"),
    ("\x1b[49m",     "default bg"),
    ("\x1b[39;49m",  "default fg+bg"),
    ("\x1b[91m",     "bright red"),
    ("\x1b[93m",     "bright yellow"),

    # Cursor visibility
    ("\x1b[?25h",    "show cursor"),
    ("\x1b[?25l",    "hide cursor"),

    # Bracketed paste
    ("\x1b[?2004h",  "bracketed paste on"),
    ("\x1b[?2004l",  "bracketed paste off"),
]
