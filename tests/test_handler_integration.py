"""Tier 2: Integration tests — WriteConsoleInputW injection.

Injects fake KEY_EVENT_RECORD into the real console input buffer,
reads back via read_batch(), verifies round-trip correctness.

Windows-only. Requires a real console (not piped stdin).

Run: python tests/test_handler_integration.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from terminalist.input.win32 import (
    INPUT_RECORD,
    KEY_EVENT,
    RawConsoleInput,
    kernel32,
    read_batch,
    has_events,
)
from terminalist.input.keymap_vk import VK_PROCESSKEY

results: list[tuple[str, bool, str]] = []


def run_test(name, fn):
    try:
        fn()
        print(f"  PASS  {name}")
        results.append((name, True, ""))
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        results.append((name, False, str(e)))
    except Exception as e:
        print(f"  FAIL  {name}: {type(e).__name__}: {e}")
        results.append((name, False, str(e)))


def _write_events(h_in: int, events: list[tuple[str | None, int, int, int]]) -> int:
    """Inject KEY_EVENT_RECORD into console input buffer via WriteConsoleInputW."""
    # Each event generates a KEY_DOWN record
    records = (INPUT_RECORD * len(events))()
    for i, (ch, vk, ctrl, repeat) in enumerate(events):
        records[i].EventType = KEY_EVENT
        ke = records[i].Event.KeyEvent
        ke.bKeyDown = True
        ke.wRepeatCount = repeat
        ke.wVirtualKeyCode = vk
        ke.wVirtualScanCode = 0
        ke.uChar = ch if ch else "\x00"
        ke.dwControlKeyState = ctrl
    written = wt.DWORD()
    kernel32.WriteConsoleInputW(h_in, records, len(events), ctypes.byref(written))
    return written.value


def _flush_input(h_in: int) -> None:
    """Flush any pending input events."""
    kernel32.FlushConsoleInputBuffer(h_in)


# ══════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════

h_in: int = 0  # set in main


def test_roundtrip_ascii():
    """Inject ASCII chars, read back via read_batch."""
    _flush_input(h_in)
    _write_events(h_in, [
        ("a", 0x41, 0, 1),
        ("b", 0x42, 0, 1),
        ("c", 0x43, 0, 1),
    ])
    events = read_batch(h_in)
    chars = [ch for ch, vk, ctrl, repeat in events if ch]
    assert chars == ["a", "b", "c"], f"Expected ['a','b','c'], got {chars}"


def test_roundtrip_korean():
    """Inject Korean IME confirmed chars (vk=0x0000)."""
    _flush_input(h_in)
    _write_events(h_in, [
        ("한", 0x0000, 0, 1),
        ("글", 0x0000, 0, 1),
    ])
    events = read_batch(h_in)
    chars = [ch for ch, vk, ctrl, repeat in events if ch]
    assert chars == ["한", "글"], f"Expected ['한','글'], got {chars}"


def test_roundtrip_special_key():
    """Inject special key (arrow) — ch=None, vk set."""
    _flush_input(h_in)
    _write_events(h_in, [
        (None, 0x26, 0, 1),  # VK_UP
    ])
    events = read_batch(h_in)
    assert len(events) == 1
    ch, vk, ctrl, repeat = events[0]
    assert ch is None, f"Expected None, got {ch!r}"
    assert vk == 0x26


def test_roundtrip_vk_processkey():
    """Inject VK_PROCESSKEY — should arrive with correct vk."""
    _flush_input(h_in)
    _write_events(h_in, [
        (None, VK_PROCESSKEY, 0, 1),
    ])
    events = read_batch(h_in)
    assert len(events) == 1
    ch, vk, ctrl, repeat = events[0]
    assert vk == VK_PROCESSKEY


def test_roundtrip_da_sequence():
    """Inject DA response as vk=0x0000 chars."""
    _flush_input(h_in)
    da = "\x1b[?61;6;7c"
    _write_events(h_in, [(c, 0x0000, 0, 1) for c in da])
    events = read_batch(h_in)
    chars = [ch for ch, vk, ctrl, repeat in events if ch]
    assert "".join(chars) == da, f"DA roundtrip failed: {''.join(chars)!r}"


def test_roundtrip_mixed_ime_sequence():
    """Inject IME sequence: VK_PROCESSKEY → confirmed Korean."""
    _flush_input(h_in)
    _write_events(h_in, [
        (None, VK_PROCESSKEY, 0, 1),   # IME composing 'g'
        (None, VK_PROCESSKEY, 0, 1),   # IME composing 'k'
        ("가", 0x0000, 0, 1),           # IME confirmed
    ])
    events = read_batch(h_in)
    assert len(events) == 3
    assert events[0][1] == VK_PROCESSKEY
    assert events[1][1] == VK_PROCESSKEY
    assert events[2][0] == "가" and events[2][1] == 0x0000


def test_roundtrip_ctrl_state():
    """Inject event with control key state (Shift pressed)."""
    _flush_input(h_in)
    SHIFT_PRESSED = 0x0010
    _write_events(h_in, [
        ("\r", 0x0D, SHIFT_PRESSED, 1),
    ])
    events = read_batch(h_in)
    assert len(events) == 1
    ch, vk, ctrl, repeat = events[0]
    assert ch == "\r"
    assert ctrl & SHIFT_PRESSED, f"SHIFT bit not preserved: ctrl=0x{ctrl:08X}"


def test_roundtrip_repeat_count():
    """Inject event with repeat > 1."""
    _flush_input(h_in)
    _write_events(h_in, [
        ("x", 0x58, 0, 5),  # 'x' with repeat=5
    ])
    events = read_batch(h_in)
    assert len(events) == 1
    ch, vk, ctrl, repeat = events[0]
    assert ch == "x"
    assert repeat == 5, f"Expected repeat=5, got {repeat}"


def test_batch_empty_after_flush():
    """After flush, read_batch should return empty."""
    _flush_input(h_in)
    events = read_batch(h_in)
    assert events == [], f"Expected [], got {events}"


# ══════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════

def main():
    global h_in

    print("=" * 60)
    print("Tier 2: Handler Integration Tests (WriteConsoleInputW)")
    print("=" * 60)

    # Open CONIN$ directly — GetStdHandle may return a pipe handle
    # when running inside Claude Code or other tools that redirect stdin.
    try:
        conin = kernel32.CreateFileW(
            "CONIN$",
            0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
            0x01 | 0x02,              # FILE_SHARE_READ | FILE_SHARE_WRITE
            None,
            3,                        # OPEN_EXISTING
            0,
            None,
        )
        if conin == -1:
            raise OSError("Cannot open CONIN$")
        h_in = conin
        _flush_input(h_in)

        run_test("roundtrip_ascii", test_roundtrip_ascii)
        run_test("roundtrip_korean", test_roundtrip_korean)
        run_test("roundtrip_special_key", test_roundtrip_special_key)
        run_test("roundtrip_vk_processkey", test_roundtrip_vk_processkey)
        run_test("roundtrip_da_sequence", test_roundtrip_da_sequence)
        run_test("roundtrip_mixed_ime_sequence", test_roundtrip_mixed_ime_sequence)
        run_test("roundtrip_ctrl_state", test_roundtrip_ctrl_state)
        run_test("roundtrip_repeat_count", test_roundtrip_repeat_count)
        run_test("batch_empty_after_flush", test_batch_empty_after_flush)

        _flush_input(h_in)  # cleanup
        kernel32.CloseHandle(conin)

    except OSError as e:
        print(f"\nSKIPPED: No console available ({e})")
        print("Integration tests require a real console (not piped stdin).")
        sys.exit(0)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed, {len(results)} total")
    print("=" * 60)
    if failed:
        for name, ok, detail in results:
            if not ok:
                print(f"  FAIL  {name}: {detail}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
