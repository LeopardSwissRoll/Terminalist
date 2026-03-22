"""VT100 key mapping — Textual key name → VT100 escape sequence."""

# Textual provides parsed key names, not raw codes.
# This table maps them to byte sequences for PTY write.

VT100_MAP: dict[str, str] = {
    # Arrow keys
    "up": "\x1b[A",
    "down": "\x1b[B",
    "right": "\x1b[C",
    "left": "\x1b[D",
    # Editing keys
    "home": "\x1b[H",
    "end": "\x1b[F",
    "insert": "\x1b[2~",
    "delete": "\x1b[3~",
    "pageup": "\x1b[5~",
    "pagedown": "\x1b[6~",
    # Function keys
    "f1": "\x1bOP",
    "f2": "\x1bOQ",
    "f3": "\x1bOR",
    "f4": "\x1bOS",
    "f5": "\x1b[15~",
    "f6": "\x1b[17~",
    "f7": "\x1b[18~",
    "f8": "\x1b[19~",
    "f9": "\x1b[20~",
    "f10": "\x1b[21~",
    "f11": "\x1b[23~",
    "f12": "\x1b[24~",
    # Ctrl combinations
    "ctrl+a": "\x01",
    "ctrl+b": "\x02",
    "ctrl+c": "\x03",
    "ctrl+d": "\x04",
    "ctrl+e": "\x05",
    "ctrl+f": "\x06",
    "ctrl+g": "\x07",
    "ctrl+h": "\x08",
    "ctrl+k": "\x0b",
    "ctrl+l": "\x0c",
    "ctrl+n": "\x0e",
    "ctrl+o": "\x0f",
    "ctrl+p": "\x10",
    "ctrl+r": "\x12",
    "ctrl+s": "\x13",
    "ctrl+t": "\x14",
    "ctrl+u": "\x15",
    "ctrl+w": "\x17",
    "ctrl+z": "\x1a",
    # Special keys
    "enter": "\r",
    "tab": "\t",
    "escape": "\x1b",
    "backspace": "\x7f",
}

# ctrl+] (\x1d) is intentionally EXCLUDED — used as detach trigger at App level
