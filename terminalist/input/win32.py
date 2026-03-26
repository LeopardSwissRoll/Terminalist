"""Windows console input backend — ReadConsoleInputW.

Handles all Windows-specific console API:
- ctypes struct definitions
- Console mode management (save/restore/raw)
- VT processing enable
- Non-blocking record reading
- Batch event reading
- Console mode flag logging

Platform-agnostic event processing (paste detection, DA filter,
key translation) lives in handler.py instead.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import sys

from terminalist.debug import log

# ── Constants ──

STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
KEY_EVENT = 0x0001
MOUSE_EVENT = 0x0002
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
ENABLE_MOUSE_INPUT = 0x0010

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

# ── Console input structures ──


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", wt.BOOL),
        ("wRepeatCount", wt.WORD),
        ("wVirtualKeyCode", wt.WORD),
        ("wVirtualScanCode", wt.WORD),
        ("uChar", wt.WCHAR),
        ("dwControlKeyState", wt.DWORD),
    ]


class COORD(ctypes.Structure):
    _fields_ = [("X", wt.SHORT), ("Y", wt.SHORT)]


class MOUSE_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("dwMousePosition", COORD),
        ("dwButtonState", wt.DWORD),
        ("dwControlKeyState", wt.DWORD),
        ("dwEventFlags", wt.DWORD),
    ]


# Mouse event flags
MOUSE_WHEELED = 0x0004
MOUSE_HWHEELED = 0x0008


class INPUT_RECORD_UNION(ctypes.Union):
    _fields_ = [
        ("KeyEvent", KEY_EVENT_RECORD),
        ("MouseEvent", MOUSE_EVENT_RECORD),
    ]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [
        ("EventType", wt.WORD),
        ("Event", INPUT_RECORD_UNION),
    ]


# ── Console mode flag names (for logging) ──

_INPUT_MODE_FLAGS = {
    0x0001: "PROCESSED_INPUT",
    0x0002: "LINE_INPUT",
    0x0004: "ECHO_INPUT",
    0x0008: "WINDOW_INPUT",
    0x0010: "MOUSE_INPUT",
    0x0020: "INSERT_MODE",
    0x0040: "QUICK_EDIT",
    0x0080: "EXTENDED_FLAGS",
    0x0200: "VT_INPUT",
}
_OUTPUT_MODE_FLAGS = {
    0x0001: "PROCESSED_OUTPUT",
    0x0002: "WRAP_AT_EOL",
    0x0004: "VT_PROCESSING",
    0x0008: "DISABLE_NEWLINE_AUTO_RETURN",
}


def _decode_flags(value: int, table: dict[int, str]) -> str:
    names = [name for bit, name in sorted(table.items()) if value & bit]
    return f"0x{value:04x} ({' | '.join(names)})" if names else f"0x{value:04x}"


# ── Event types (tagged for type-safe dispatch) ──

from typing import NamedTuple


class KeyEvent(NamedTuple):
    """KEY_DOWN event from ReadConsoleInputW."""
    char: str | None  # None for special keys (arrows, F-keys)
    vk: int           # Virtual key code
    ctrl: int         # dwControlKeyState
    repeat: int       # wRepeatCount


class MouseEvent(NamedTuple):
    """MOUSE_EVENT from ReadConsoleInputW."""
    x: int            # Column (0-indexed)
    y: int            # Row (0-indexed)
    buttons: int      # dwButtonState
    flags: int        # dwEventFlags (MOUSE_WHEELED etc.)


# ── Console setup ──


def enable_vt() -> None:
    """Enable ANSI escape processing on stdout. Log console modes."""
    h_in = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    in_mode = ctypes.c_ulong()
    kernel32.GetConsoleMode(h_in, ctypes.byref(in_mode))
    log("ctx", f"stdin console mode: {_decode_flags(in_mode.value, _INPUT_MODE_FLAGS)}")

    h_out = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
    out_mode = ctypes.c_ulong()
    kernel32.GetConsoleMode(h_out, ctypes.byref(out_mode))
    log("ctx", f"stdout console mode BEFORE: {_decode_flags(out_mode.value, _OUTPUT_MODE_FLAGS)}")
    kernel32.SetConsoleMode(h_out, out_mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    kernel32.GetConsoleMode(h_out, ctypes.byref(out_mode))
    log("ctx", f"stdout console mode AFTER: {_decode_flags(out_mode.value, _OUTPUT_MODE_FLAGS)}")


def enter_alt_screen() -> None:
    sys.stdout.write(
        "\x1b[?1049h"   # alt screen
        "\x1b[H"        # cursor home
        "\x1b[2J"       # clear
        # Enable basic xterm mouse reporting too.
        # Some hosts translate wheel → arrow keys unless mouse mode is active.
        "\x1b[?1000h"   # normal mouse tracking (click/wheel)
        "\x1b[?1006h"   # SGR extended coordinates
    )
    sys.stdout.flush()
    log("app", "Entered alt screen")


def exit_alt_screen() -> None:
    sys.stdout.write(
        "\x1b[?1006l"
        "\x1b[?1000l"
        "\x1b[?1049l"
    )
    sys.stdout.flush()
    log("app", "Exited alt screen")


def terminal_size() -> tuple[int, int]:
    """Return (rows, cols)."""
    try:
        cols, rows = os.get_terminal_size()
        return max(rows, 10), max(cols, 40)
    except OSError:
        return 30, 120


def is_shift_pressed() -> bool:
    """Check hardware Shift state via GetAsyncKeyState (user32)."""
    return bool(user32.GetAsyncKeyState(0x10) & 0x8000)


# ── Console mode context manager ──


class RawConsoleInput:
    """Context manager for raw console input mode.

    Saves the current console mode, sets raw mode (0),
    and restores on exit.
    """

    def __init__(self) -> None:
        self.h_in = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        self._old_mode = wt.DWORD()

    def __enter__(self) -> int:
        kernel32.GetConsoleMode(self.h_in, ctypes.byref(self._old_mode))
        # Raw mode + mouse input enabled
        # 0x0010 = ENABLE_MOUSE_INPUT (receive MOUSE_EVENT records)
        kernel32.SetConsoleMode(self.h_in, 0x0010)
        log("input", f"Console raw mode + mouse set (old=0x{self._old_mode.value:04x})")
        return self.h_in

    def __exit__(self, *exc) -> None:
        kernel32.SetConsoleMode(self.h_in, self._old_mode)
        log("input", f"Console mode restored (0x{self._old_mode.value:04x})")


# ── Record reading ──


def read_one_record(h_in: int) -> KeyEvent | MouseEvent | None:
    """Read one console input record. Non-blocking per record.

    Returns:
        KeyEvent for KEY_DOWN
        MouseEvent for MOUSE_EVENT
        None for other events (KEY_UP, focus, etc.)
    """
    record = INPUT_RECORD()
    read_count = wt.DWORD()
    kernel32.ReadConsoleInputW(h_in, ctypes.byref(record), 1, ctypes.byref(read_count))

    if record.EventType == MOUSE_EVENT:
        me = record.Event.MouseEvent
        return MouseEvent(me.dwMousePosition.X, me.dwMousePosition.Y,
                          me.dwButtonState, me.dwEventFlags)

    if record.EventType != KEY_EVENT:
        return None
    ke = record.Event.KeyEvent
    if not ke.bKeyDown:
        return None
    ch = ke.uChar
    vk = ke.wVirtualKeyCode
    ctrl = ke.dwControlKeyState
    repeat = ke.wRepeatCount
    return KeyEvent(ch if ch and ch != "\x00" else None, vk, ctrl, repeat)


def read_key_blocking(h_in: int) -> KeyEvent:
    """Read one KEY_DOWN event. Blocks until one arrives.

    Silently consumes MouseEvent and other non-key records.
    """
    while True:
        result = read_one_record(h_in)
        if result is None:
            continue
        if isinstance(result, MouseEvent):
            continue
        return result


def has_events(h_in: int) -> bool:
    """Non-blocking check for pending console input events."""
    avail = wt.DWORD()
    kernel32.GetNumberOfConsoleInputEvents(h_in, ctypes.byref(avail))
    return avail.value > 0


def read_batch(h_in: int, limit: int = 4096) -> tuple[list[KeyEvent], list[MouseEvent]]:
    """Read all available events. Non-blocking.

    Returns (key_events, mouse_events).
    KeyEvent: 4-tuple (char, vk, ctrl, repeat)
    MouseEvent: 4-tuple (x, y, buttons, flags)
    """
    keys: list[KeyEvent] = []
    mice: list[MouseEvent] = []
    while has_events(h_in):
        result = read_one_record(h_in)
        if result is None:
            continue
        if isinstance(result, MouseEvent):
            mice.append(result)
        elif isinstance(result, KeyEvent):
            keys.append(result)
        if len(keys) + len(mice) >= limit:
            break
    return keys, mice
