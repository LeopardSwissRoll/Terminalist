"""Thin TestPane adapter over terminalist.input.win32."""

from __future__ import annotations

from terminalist.input.win32 import (
    KeyEvent,
    MouseEvent,
    RawConsoleInput,
    enable_vt as enable_vt_output,
    read_one_record,
)


FROM_LEFT_1ST_BUTTON_PRESSED = 0x0001


def read_event(h_in: int) -> tuple[str, str] | tuple[str, int, int] | None:
    while True:
        record = read_one_record(h_in)
        if record is None:
            continue

        if isinstance(record, KeyEvent):
            translated = _translate_key(record)
            if translated is not None:
                return ("key", translated)
            continue

        if isinstance(record, MouseEvent):
            if record.flags == 0 and (record.buttons & FROM_LEFT_1ST_BUTTON_PRESSED):
                return ("mouse", record.x, record.y)


def _translate_key(record: KeyEvent) -> str | None:
    special = {
        0x25: "left",
        0x27: "right",
        0x26: "up",
        0x28: "down",
    }.get(record.vk)
    if special is not None:
        return special

    ch = record.char
    if not ch or ch == "\x00":
        return None
    lowered = ch.lower()
    if lowered in {"v", "h", "x", "q"}:
        return lowered
    return None
