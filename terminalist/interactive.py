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
from pathlib import Path

from terminalist.debug import init_debug, log, detect_env
from terminalist.pyte_patch import apply as patch_pyte
from terminalist.core.shell_session import ShellSession
from terminalist.core.terminal_session import SessionState
from terminalist.vt100 import VT100_MAP


# ── Windows VT processing ──

def _enable_vt() -> None:
    """Enable ANSI escape processing on Windows stdout."""
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    mode = ctypes.c_ulong()
    k32.GetConsoleMode(h, ctypes.byref(mode))
    k32.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING


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
            return None
        return "\x1b" + buf

    elif first_after_esc == "P":
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                buf += ch
                if len(buf) >= 2 and buf[-2] == "\x1b" and buf[-1] == "\\":
                    return None
            else:
                time.sleep(0.005)
        return None

    elif first_after_esc == "]":
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                buf += ch
                if ch == "\x07":
                    return None
                if len(buf) >= 2 and buf[-2] == "\x1b" and buf[-1] == "\\":
                    return None
            else:
                time.sleep(0.005)
        return None

    else:
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
    log("app", "Draining initial terminal responses...")
    drain_end = time.monotonic() + 2.0
    while time.monotonic() < drain_end:
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch == "\x1b" and msvcrt.kbhit():
                _drain_escape(msvcrt.getwch())
        time.sleep(0.02)

    log("app", "DA drain complete, entering input loop")

    # ── Input loop: stdin → PTY ──
    try:
        while not stop.is_set() and session._backend.is_alive():
            check_resize()

            if not msvcrt.kbhit():
                time.sleep(0.01)
                continue

            ch = msvcrt.getwch()

            if ch in ("\r", "\n"):
                session.write_raw("\r")
            elif ch in ("\x00", "\xe0"):
                key = msvcrt.getwch()
                ansi = _SPECIAL_KEYS.get(key, "")
                if ansi:
                    session.write_raw(ansi)
                    log("key", f"special key: {key!r} → {ansi!r}")
            elif ch == "\t":
                session.write_raw("\t")
            elif ch == "\x1b":
                if msvcrt.kbhit():
                    next_ch = msvcrt.getwch()
                    result = _drain_escape(next_ch)
                    if result is not None:
                        session.write_raw(result)
                else:
                    session.write_raw("\x1b")
            else:
                session.write_raw(ch)
                if ord(ch) < 0x20:
                    log("key", f"control: {ch!r} (0x{ord(ch):02x})")

    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, prev_handler)
        stop.set()

    # ── Cleanup ──
    log("app", f"Exiting. Session state={session.state.value}")
    session.kill()
    log("app", "=== Interactive shell ended ===")


if __name__ == "__main__":
    main()
