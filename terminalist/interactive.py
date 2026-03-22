"""Single-session interactive shell — I/O verification via dualrun.

Spawns one ShellSession and bridges it to the current terminal:
  PTY output → stdout (raw passthrough via _on_raw_output tap)
  stdin → PTY (msvcrt input, same pattern as fakeTerm.py)
  pyte + state machine run in the background (for state tracking)

Usage:
    python -m terminalist.interactive [--debug]
    python -m terminalist.dualrun -m terminalist.interactive

Detach: Ctrl+C twice within 1 second.
"""

from __future__ import annotations

import argparse
import msvcrt
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
from terminalist.vt100 import VT100_MAP


# ── Windows terminal setup ──

def _enable_vt() -> None:
    """Enable ANSI escape processing on Windows stdout."""
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    mode = ctypes.c_ulong()
    k32.GetConsoleMode(h, ctypes.byref(mode))
    k32.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING


def _enter_alt_screen() -> None:
    """Enter alternate screen buffer + hide cursor."""
    sys.stdout.write("\x1b[?1049h")  # alt screen
    sys.stdout.write("\x1b[H")       # cursor home
    sys.stdout.write("\x1b[2J")      # clear screen
    sys.stdout.flush()
    log("app", "Entered alt screen")


def _exit_alt_screen() -> None:
    """Exit alternate screen buffer + show cursor."""
    sys.stdout.write("\x1b[?1049l")  # exit alt screen
    sys.stdout.flush()
    log("app", "Exited alt screen")


# ── Special key mapping (msvcrt → ANSI, same as fakeTerm.py) ──

_SPECIAL_KEYS = {
    "H": "\x1b[A",   # Up
    "P": "\x1b[B",   # Down
    "M": "\x1b[C",   # Right
    "K": "\x1b[D",   # Left
    "G": "\x1b[H",   # Home
    "O": "\x1b[F",   # End
    "I": "\x1b[5~",  # Page Up
    "Q": "\x1b[6~",  # Page Down
    "S": "\x1b[3~",  # Delete
    "R": "\x1b[2~",  # Insert
}


# ── DA drain (terminal response filter, from fakeTerm.py) ──

def _drain_escape(first_after_esc: str) -> str | None:
    """Consume terminal response sequences. Returns None if consumed."""
    buf = first_after_esc

    if first_after_esc == "[":
        while msvcrt.kbhit():
            ch = msvcrt.getwch()
            buf += ch
            if "\x40" <= ch <= "\x7e":
                break
        if buf.endswith("c") or buf.endswith("y") or buf.endswith("n"):
            log("input", f"DA response consumed: ESC{buf!r}")
            return None
        log("input", f"ESC sequence forwarded: ESC{buf!r}")
        return "\x1b" + buf

    elif first_after_esc == "P":
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                buf += ch
                if len(buf) >= 2 and buf[-2] == "\x1b" and buf[-1] == "\\":
                    log("input", f"DCS response consumed ({len(buf)} chars)")
                    return None
            else:
                time.sleep(0.005)
        log("input", f"DCS response timeout ({len(buf)} chars)")
        return None

    elif first_after_esc == "]":
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                buf += ch
                if ch == "\x07":
                    log("input", f"OSC response consumed (BEL)")
                    return None
                if len(buf) >= 2 and buf[-2] == "\x1b" and buf[-1] == "\\":
                    log("input", f"OSC response consumed (ST)")
                    return None
            else:
                time.sleep(0.005)
        log("input", f"OSC response timeout ({len(buf)} chars)")
        return None

    else:
        log("input", f"Unknown ESC+{first_after_esc!r} forwarded")
        return "\x1b" + buf


def _terminal_size() -> tuple[int, int]:
    """Return (rows, cols)."""
    try:
        cols, rows = os.get_terminal_size()
        return max(rows, 10), max(cols, 40)
    except OSError:
        return 30, 120


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

    # ── Alt screen (prevent overwriting host terminal content) ──
    _enter_alt_screen()

    # ── Spawn session ──
    session = ShellSession(
        "interactive",
        Path.cwd(),
        shell_type="powershell",
        cols=cols,
        rows=rows,
    )

    # Raw output tap → stdout
    def on_raw_output(data: str) -> None:
        try:
            sys.stdout.write(data)
            sys.stdout.flush()
        except Exception:
            pass

    session._on_raw_output.append(on_raw_output)
    session.spawn()

    log("app", f"Session spawned pid={session._backend.pid}")

    # ── Ctrl+C: single → forward, double (< 1s) → exit ──
    stop = threading.Event()
    last_sigint = [0.0]
    prev_handler = signal.getsignal(signal.SIGINT)

    def on_sigint(_s, _f):
        now = time.monotonic()
        if now - last_sigint[0] < 1.0:
            log("app", "Double Ctrl+C → exiting")
            stop.set()
            return
        last_sigint[0] = now
        log("key", "Ctrl+C → forwarding \\x03 to PTY")
        session.write_raw("\x03")

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

    # ── Initial DA drain ──
    log("input", "Draining initial terminal responses (2s)...")
    drain_end = time.monotonic() + 2.0
    drain_count = 0
    while time.monotonic() < drain_end:
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            drain_count += 1
            if ch == "\x1b" and msvcrt.kbhit():
                _drain_escape(msvcrt.getwch())
            else:
                log("input", f"Drain: discarded char {ch!r} (0x{ord(ch):04x})")
        time.sleep(0.02)
    log("input", f"DA drain complete ({drain_count} chars consumed)")

    # ── Input loop: stdin → PTY ──
    log("input", "Entering input loop")
    input_count = 0
    try:
        while not stop.is_set() and session._backend.is_alive():
            check_resize()

            if not msvcrt.kbhit():
                time.sleep(0.01)
                continue

            ch = msvcrt.getwch()
            input_count += 1

            if ch in ("\r", "\n"):
                session.write_raw("\r")
                log("key", f"#{input_count} Enter")

            elif ch in ("\x00", "\xe0"):
                # Special key prefix — read the scan code
                key = msvcrt.getwch()
                ansi = _SPECIAL_KEYS.get(key, "")
                if ansi:
                    session.write_raw(ansi)
                    log("key", f"#{input_count} special: prefix={ch!r} scan={key!r} → {ansi!r}")
                else:
                    log("key", f"#{input_count} special: prefix={ch!r} scan={key!r} → UNMAPPED (dropped)")

            elif ch == "\t":
                session.write_raw("\t")
                log("key", f"#{input_count} Tab")

            elif ch == "\x1b":
                # ESC — could be terminal response or user-pressed Escape
                if msvcrt.kbhit():
                    next_ch = msvcrt.getwch()
                    result = _drain_escape(next_ch)
                    if result is not None:
                        session.write_raw(result)
                        log("key", f"#{input_count} ESC sequence forwarded: {result!r:.40}")
                    else:
                        log("key", f"#{input_count} ESC sequence consumed (DA response)")
                else:
                    session.write_raw("\x1b")
                    log("key", f"#{input_count} bare Escape")

            elif ord(ch) < 0x20:
                # Control character
                session.write_raw(ch)
                log("key", f"#{input_count} control: {ch!r} (0x{ord(ch):02x})")

            elif ord(ch) >= 0xAC00:
                # Korean syllable block (완성형 한글 U+AC00~U+D7A3)
                session.write_raw(ch)
                log("key", f"#{input_count} korean: {ch!r} (U+{ord(ch):04X})")

            elif ord(ch) > 0x7F:
                # Non-ASCII (CJK, emoji, etc.)
                session.write_raw(ch)
                log("key", f"#{input_count} unicode: {ch!r} (U+{ord(ch):04X})")

            else:
                # Printable ASCII
                session.write_raw(ch)
                # Log printable chars at lower frequency (every 10th, or if debug is very verbose)
                if input_count % 10 == 0:
                    log("key", f"#{input_count} char: {ch!r}")

    except Exception as e:
        log("app", f"INPUT LOOP CRASHED: {type(e).__name__}: {e}")
        log("app", traceback.format_exc())
        print(f"\n[terminalist] Input loop error: {e}", file=sys.stderr)
    finally:
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
