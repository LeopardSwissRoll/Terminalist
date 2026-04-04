"""Thin TestCopy adapter over terminalist.input.win32."""

from __future__ import annotations

from terminalist.input.win32 import (
    MOUSE_WHEELED,
    KeyEvent,
    MouseEvent,
    RawConsoleInput,
    enable_vt as enable_vt_output,
    read_one_record,
)


ConsoleEvent = tuple[str, str]


def read_event(h_in: int) -> ConsoleEvent:
    while True:
        record = read_one_record(h_in)
        if record is None:
            continue

        if isinstance(record, KeyEvent):
            translated = translate_key(record)
            if translated is not None:
                return translated
            continue

        if isinstance(record, MouseEvent) and record.flags & MOUSE_WHEELED:
            direction = "up" if record.buttons & 0x80000000 else "down"
            return ("wheel", direction)


def translate_key(record: KeyEvent) -> ConsoleEvent | None:
    special = {
        0x25: ("key", "left"),
        0x27: ("key", "right"),
        0x26: ("key", "up"),
        0x28: ("key", "down"),
        0x21: ("key", "page_up"),
        0x22: ("key", "page_down"),
        0x24: ("key", "home"),
        0x23: ("key", "end"),
        0x0D: ("key", "enter"),
        0x1B: ("key", "esc"),
        0x08: ("key", "backspace"),
    }.get(record.vk)
    if special is not None:
        return special

    ch = record.char
    if not ch or ch == "\x00":
        return None

    if ch == "[":
        return ("key", "copy_mode")
    if ch == "/":
        return ("key", "search")
    if ch == " ":
        return ("key", "space")
    if ch == "q":
        return ("key", "quit")
    if ch == "n":
        return ("key", "next_match")
    if ch == "N":
        return ("key", "prev_match")
    if ch.isprintable():
        return ("text", ch)
    return None

