"""Single-session interactive shell — I/O verification via dualrun.

Spawns one ShellSession and bridges it to the current terminal:
  PTY output → stdout (raw passthrough via _on_raw_output tap)
  stdin → PTY (ReadConsoleInputW for proper Korean IME support)
  pyte + state machine run in the background (for state tracking)

Usage:
    python -m terminalist.interactive [--debug]
    python -m terminalist.dualrun -m terminalist.interactive

Detach: Ctrl+C twice within 1 second.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

from terminalist.debug import init_debug, log, detect_env
from terminalist.pyte_patch import apply as patch_pyte
from terminalist.core.shell_session import ShellSession
from terminalist.core.terminal_session import SessionState

# ── Windows Console API ──

kernel32 = ctypes.windll.kernel32

STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
KEY_EVENT = 0x0001
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
VK_PROCESSKEY = 0xE5  # IME intercepted this key


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", wt.BOOL),
        ("wRepeatCount", wt.WORD),
        ("wVirtualKeyCode", wt.WORD),
        ("wVirtualScanCode", wt.WORD),
        ("uChar", wt.WCHAR),
        ("dwControlKeyState", wt.DWORD),
    ]


class INPUT_RECORD_UNION(ctypes.Union):
    _fields_ = [("KeyEvent", KEY_EVENT_RECORD)]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [
        ("EventType", wt.WORD),
        ("Event", INPUT_RECORD_UNION),
    ]


# ── Console mode flag names for logging ──

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


# ── Special key VK → ANSI ──

_SPECIAL_VK = {
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
}


# ── Windows terminal setup ──

def _enable_vt() -> None:
    """Enable ANSI escape processing on Windows stdout. Log all console modes."""
    # ── Log stdin mode ──
    h_in = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    in_mode = ctypes.c_ulong()
    kernel32.GetConsoleMode(h_in, ctypes.byref(in_mode))
    log("ctx", f"stdin console mode: {_decode_flags(in_mode.value, _INPUT_MODE_FLAGS)}")

    # ── Log + set stdout mode ──
    h_out = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
    out_mode = ctypes.c_ulong()
    kernel32.GetConsoleMode(h_out, ctypes.byref(out_mode))
    log("ctx", f"stdout console mode BEFORE: {_decode_flags(out_mode.value, _OUTPUT_MODE_FLAGS)}")
    kernel32.SetConsoleMode(h_out, out_mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    kernel32.GetConsoleMode(h_out, ctypes.byref(out_mode))
    log("ctx", f"stdout console mode AFTER: {_decode_flags(out_mode.value, _OUTPUT_MODE_FLAGS)}")


def _enter_alt_screen() -> None:
    sys.stdout.write("\x1b[?1049h\x1b[H\x1b[2J")
    sys.stdout.flush()
    log("app", "Entered alt screen")


def _exit_alt_screen() -> None:
    sys.stdout.write("\x1b[?1049l")
    sys.stdout.flush()
    log("app", "Exited alt screen")


def _terminal_size() -> tuple[int, int]:
    """Return (rows, cols)."""
    try:
        cols, rows = os.get_terminal_size()
        return max(rows, 10), max(cols, 40)
    except OSError:
        return 30, 120


def _read_console_input(h_in: int) -> tuple[str | None, int, int, int]:
    """Read one key-down event via ReadConsoleInputW.

    Returns (char_or_none, virtual_key_code, control_key_state, repeat_count).
    Blocks until a KEY_DOWN event arrives.
    """
    record = INPUT_RECORD()
    read_count = wt.DWORD()

    while True:
        kernel32.ReadConsoleInputW(
            h_in,
            ctypes.byref(record),
            1,
            ctypes.byref(read_count),
        )
        if record.EventType != KEY_EVENT:
            continue
        ke = record.Event.KeyEvent
        if not ke.bKeyDown:
            continue

        ch = ke.uChar
        vk = ke.wVirtualKeyCode
        ctrl = ke.dwControlKeyState
        repeat = ke.wRepeatCount
        # '\x00' (NUL) means no character — treat as None
        # This happens for special keys (arrows, F-keys, etc.)
        return (ch if ch and ch != "\x00" else None, vk, ctrl, repeat)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Terminalist interactive shell")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    p.add_argument("--debug-log", type=str, default=None, help="Debug log file path")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    init_debug(enabled=args.debug, log_path=args.debug_log)
    patch_pyte()
    _enable_vt()

    env = detect_env()
    rows, cols = _terminal_size()

    log("app", f"=== Interactive shell starting (env={env}, {cols}x{rows}) ===")

    # ── Alt screen ──
    _enter_alt_screen()

    # ── Spawn session ──
    session = ShellSession(
        "interactive",
        Path.cwd(),
        shell_type="powershell",
        cols=cols,
        rows=rows,
    )

    def on_raw_output(data: str) -> None:
        try:
            sys.stdout.write(data)
            sys.stdout.flush()
        except Exception:
            pass

    session._on_raw_output.append(on_raw_output)
    session.spawn()

    log("app", f"Session spawned pid={session._backend.pid}")

    # ── Ctrl+C: always forward to PTY. Exit via Ctrl+B → Ctrl+C only. ──
    stop = threading.Event()
    prev_handler = signal.getsignal(signal.SIGINT)

    def on_sigint(_s, _f):
        # SIGINT from OS — forward to PTY, never exit from here
        log("key", "SIGINT → forwarding \\x03 to PTY")
        try:
            session.write_raw("\x03")
        except Exception:
            pass

    signal.signal(signal.SIGINT, on_sigint)

    # ── Resize tracking ──
    last_size = (rows, cols)

    def check_resize():
        nonlocal last_size
        new = _terminal_size()
        if new != last_size:
            last_size = new
            session.resize(cols=new[1], rows=new[0])
            log("app", f"Resize detected: {new[1]}x{new[0]}")

    # ── Console input handle + raw mode ──
    h_in = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    old_mode = wt.DWORD()
    kernel32.GetConsoleMode(h_in, ctypes.byref(old_mode))
    # Disable line input + echo (raw mode for ReadConsoleInputW)
    kernel32.SetConsoleMode(h_in, 0)
    log("input", f"Console raw mode set (old=0x{old_mode.value:04x})")

    # ── No time-based drain ──
    # DA responses are filtered in the input loop (vk=0x0000 ESC sequence detection).
    # No drain = no first-keystroke swallowing.
    log("input", "No DA drain — DA filter handles stale responses in input loop")

    # ── Input loop: ReadConsoleInputW → PTY ──
    log("input", "Entering input loop (ReadConsoleInputW)")
    log("input", "Exit: Ctrl+B → Ctrl+C (tmux style)")
    input_count = 0
    _da_buf: str | None = None  # DA response accumulation buffer
    try:
        while not stop.is_set() and session._backend.is_alive():
            check_resize()

            # Non-blocking peek
            avail = wt.DWORD()
            kernel32.GetNumberOfConsoleInputEvents(h_in, ctypes.byref(avail))
            if avail.value == 0:
                time.sleep(0.01)
                continue

            ch, vk, ctrl, repeat = _read_console_input(h_in)
            input_count += 1

            # ── IME processed key — log detail then skip ──
            if vk == VK_PROCESSKEY:
                log("key", f"#{input_count} VK_PROCESSKEY ch={ch!r} repeat={repeat} (skip)")
                continue

            # ── IME confirmed (vk=0x0000) ──
            # DA responses also arrive as vk=0x0000 one char at a time.
            # Filter: if char is part of an ESC sequence, accumulate and discard.
            if ch and vk == 0x0000:
                if ch == "\x1b" or _da_buf is not None:
                    # Start or continue DA response accumulation
                    if ch == "\x1b":
                        _da_buf = ch
                    else:
                        _da_buf += ch
                    # Check if complete: ends with letter in CSI final range
                    if len(_da_buf) >= 3 and _da_buf[1] == "[" and "\x40" <= _da_buf[-1] <= "\x7e":
                        log("input", f"#{input_count} DA response filtered: {_da_buf!r}")
                        _da_buf = None
                    elif len(_da_buf) > 50:
                        # Safety: discard overlong sequences
                        log("input", f"#{input_count} DA buffer overflow, discarding: {_da_buf!r:.50}")
                        _da_buf = None
                    continue
                # Real IME confirmed character (Korean, etc.)
                session.write_raw(ch)
                log("key", f"#{input_count} IME confirmed: {ch!r} (U+{ord(ch):04X}) repeat={repeat}")
                continue

            # ── Ctrl+C → always forward to PTY (no double-exit) ──
            # Exit is now Ctrl+B → Ctrl+C (tmux style), handled below.
            if ch == "\x03":
                session.write_raw("\x03")
                log("key", f"#{input_count} Ctrl+C → PTY")
                continue

            # ── Ctrl+B (prefix key) → tmux-style exit sequence ──
            if ch == "\x02":
                log("key", f"#{input_count} PREFIX (Ctrl+B) — waiting for next key...")
                # Wait up to 2s for next key
                prefix_deadline = time.monotonic() + 2.0
                while time.monotonic() < prefix_deadline:
                    avail2 = wt.DWORD()
                    kernel32.GetNumberOfConsoleInputEvents(h_in, ctypes.byref(avail2))
                    if avail2.value > 0:
                        break
                    time.sleep(0.01)
                else:
                    # Timeout — send literal Ctrl+B
                    session.write_raw("\x02")
                    log("key", f"#{input_count} PREFIX timeout → send literal Ctrl+B")
                    continue
                ch2, vk2, ctrl2, repeat2 = _read_console_input(h_in)
                if ch2 == "\x03":
                    log("app", "PREFIX → Ctrl+C → exiting")
                    break
                elif ch2 == "\x02":
                    # Ctrl+B twice → send literal Ctrl+B to PTY
                    session.write_raw("\x02")
                    log("key", f"#{input_count} PREFIX → Ctrl+B → send literal")
                else:
                    log("key", f"#{input_count} PREFIX → {ch2!r} vk=0x{vk2:04X} (unbound, dropped)")
                continue
                session.write_raw("\x03")
                log("key", f"#{input_count} Ctrl+C → PTY")
                continue

            # ── Special keys (arrows, home, end, etc.) ──
            if ch is None and vk in _SPECIAL_VK:
                ansi = _SPECIAL_VK[vk]
                session.write_raw(ansi)
                log("key", f"#{input_count} special: vk=0x{vk:04X} → {ansi!r} repeat={repeat}")
                continue

            # ── Regular character ──
            if ch:
                if ch in ("\r", "\n"):
                    # Check Shift via GetAsyncKeyState (dwControlKeyState unreliable in raw mode)
                    # GetAsyncKeyState is in user32, not kernel32
                    VK_SHIFT = 0x10
                    user32 = ctypes.windll.user32
                    shift_held = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
                    if shift_held:
                        # Shift+Enter → CSI u sequence for modern terminals
                        # Claude CLI expects \x1b[13;2u for Shift+Enter
                        session.write_raw("\x1b[13;2u")
                        log("key", f"#{input_count} Shift+Enter → CSI u (\\x1b[13;2u)")
                    else:
                        session.write_raw("\r")
                        log("key", f"#{input_count} Enter")
                elif ch == "\t":
                    session.write_raw("\t")
                    log("key", f"#{input_count} Tab")
                elif ch == "\x1b":
                    session.write_raw("\x1b")
                    log("key", f"#{input_count} Escape")
                elif ch == "\x08":
                    # Backspace: send \x7f (DEL) instead of \x08 (BS).
                    # Most VT100 terminals send DEL for backspace.
                    # PSReadLine treats \x08 as "undo group" but \x7f as "delete char".
                    session.write_raw("\x7f")
                    log("key", f"#{input_count} Backspace (0x08→0x7F) repeat={repeat}")
                elif ord(ch) < 0x20:
                    session.write_raw(ch)
                    log("key", f"#{input_count} control: 0x{ord(ch):02X} vk=0x{vk:04X} repeat={repeat}")
                else:
                    session.write_raw(ch)
                    if input_count % 20 == 0:
                        log("key", f"#{input_count} char: {ch!r}")
                continue

            # ── Unhandled ──
            log("key", f"#{input_count} unhandled: ch={ch!r} vk=0x{vk:04X} ctrl=0x{ctrl:08X} repeat={repeat}")

    except Exception as e:
        log("app", f"INPUT LOOP CRASHED: {type(e).__name__}: {e}")
        log("app", traceback.format_exc())
        print(f"\n[terminalist] Input loop error: {e}", file=sys.stderr)
    finally:
        # Restore console mode
        kernel32.SetConsoleMode(h_in, old_mode)
        log("input", f"Console mode restored (0x{old_mode.value:04x})")
        signal.signal(signal.SIGINT, prev_handler)
        stop.set()

    # ── Cleanup ──
    log("app", f"Exiting. Session state={session.state.value}, inputs={input_count}")
    try:
        session.kill()
    except Exception as e:
        log("app", f"Kill error (ignored): {e}")
    _exit_alt_screen()
    log("app", "=== Interactive shell ended ===")
    print("[terminalist] Session ended.")


if __name__ == "__main__":
    main()
