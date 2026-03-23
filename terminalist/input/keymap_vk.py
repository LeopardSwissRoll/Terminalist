"""VK code → ANSI/action mapping tables.

Single source of truth for Windows virtual key code translations.
Merges the old vt100.py (key name → ANSI) with VK code mappings.

For key *action* definitions (prefix commands, app bindings),
see terminalist/keymap.py instead.
"""

from __future__ import annotations

# ── VK code → ANSI escape sequence ──
# Used by win32.py to translate special keys for PTY write.

SPECIAL_VK: dict[int, str] = {
    0x26: "\x1b[A",   # VK_UP
    0x28: "\x1b[B",   # VK_DOWN
    0x27: "\x1b[C",   # VK_RIGHT
    0x25: "\x1b[D",   # VK_LEFT
    0x24: "\x1b[H",   # VK_HOME
    0x23: "\x1b[F",   # VK_END
    0x21: "\x1b[5~",  # VK_PRIOR (Page Up)
    0x22: "\x1b[6~",  # VK_NEXT (Page Down)
    0x2E: "\x1b[3~",  # VK_DELETE
    0x2D: "\x1b[2~",  # VK_INSERT
    # Function keys
    0x70: "\x1bOP",   # VK_F1
    0x71: "\x1bOQ",   # VK_F2
    0x72: "\x1bOR",   # VK_F3
    0x73: "\x1bOS",   # VK_F4
    0x74: "\x1b[15~", # VK_F5
    0x75: "\x1b[17~", # VK_F6
    0x76: "\x1b[18~", # VK_F7
    0x77: "\x1b[19~", # VK_F8
    0x78: "\x1b[20~", # VK_F9
    0x79: "\x1b[21~", # VK_F10
    0x7A: "\x1b[23~", # VK_F11
    0x7B: "\x1b[24~", # VK_F12
}

# ── Modifier-only VK codes (no character, just state change) ──
# These appear in paste batches and must be skipped in paste detection.

MODIFIER_VKS: frozenset[int] = frozenset({
    0x10,  # VK_SHIFT
    0x11,  # VK_CONTROL
    0x12,  # VK_MENU (Alt)
    0xA0,  # VK_LSHIFT
    0xA1,  # VK_RSHIFT
    0xA2,  # VK_LCONTROL
    0xA3,  # VK_RCONTROL
    0xA4,  # VK_LMENU
    0xA5,  # VK_RMENU
})

# ── Well-known VK codes ──

VK_PROCESSKEY = 0xE5  # IME intercepted this key
VK_SHIFT = 0x10
VK_BACK = 0x08
VK_RETURN = 0x0D
VK_TAB = 0x09
VK_ESCAPE = 0x1B

# ── Key name → ANSI (for tests and future platform-agnostic input) ──
# Preserved from the old vt100.py for backward compatibility.

VT100_MAP: dict[str, str] = {
    "up": "\x1b[A",
    "down": "\x1b[B",
    "right": "\x1b[C",
    "left": "\x1b[D",
    "home": "\x1b[H",
    "end": "\x1b[F",
    "insert": "\x1b[2~",
    "delete": "\x1b[3~",
    "pageup": "\x1b[5~",
    "pagedown": "\x1b[6~",
    "f1": "\x1bOP", "f2": "\x1bOQ", "f3": "\x1bOR", "f4": "\x1bOS",
    "f5": "\x1b[15~", "f6": "\x1b[17~", "f7": "\x1b[18~", "f8": "\x1b[19~",
    "f9": "\x1b[20~", "f10": "\x1b[21~", "f11": "\x1b[23~", "f12": "\x1b[24~",
    "enter": "\r",
    "tab": "\t",
    "escape": "\x1b",
    "backspace": "\x7f",
}
