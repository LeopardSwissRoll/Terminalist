"""fakeTerm — Minimal PTY virtual terminal passthrough.

Spawns a CLI process inside a PTY and bridges it to the current terminal.
User sees and interacts with the process as if running it directly.

Usage:
    python fakeTerm.py                          # default: claude --verbose
    python fakeTerm.py "codex --no-alt-screen"  # custom command
    python fakeTerm.py "python"                 # any CLI
    python fakeTerm.py "claude" --cwd ~/myproject

Detach: Ctrl+C twice within 1 second.
"""
from __future__ import annotations

import os
import signal
import sys
import threading
import time

# ── Windows: Enable ANSI escape processing ──
# Without this, PTY output containing ANSI codes (colors, cursor movement)
# renders as garbage text instead of being interpreted by the terminal.
def _enable_vt():
    if os.name != "nt":
        return
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    mode = ctypes.c_ulong()
    k32.GetConsoleMode(h, ctypes.byref(mode))
    k32.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING


# ── Windows special key → ANSI escape sequence ──
# msvcrt.getwch() returns a two-character sequence for special keys:
# first char is \x00 or \xe0 (prefix), second is the key code.
# We map these to standard ANSI sequences the PTY process expects.
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


def _terminal_size() -> tuple[int, int]:
    try:
        cols, rows = os.get_terminal_size()
        return max(rows, 10), max(cols, 40)
    except OSError:
        return 30, 120


def run(command: str, cwd: str | None = None) -> None:
    import msvcrt
    from winpty import PtyProcess

    _enable_vt()
    rows, cols = _terminal_size()
    proc = PtyProcess.spawn(command, cwd=cwd or ".", dimensions=(rows, cols))

    stop = threading.Event()
    last_size = (rows, cols)

    # ── Ctrl+C: single → forward to PTY, double (< 1s) → exit ──
    last_sigint = [0.0]
    prev_handler = signal.getsignal(signal.SIGINT)

    def on_sigint(_s, _f):
        now = time.monotonic()
        if now - last_sigint[0] < 1.0:
            stop.set()
            return
        last_sigint[0] = now
        try:
            proc.write("\x03")
        except Exception:
            pass

    signal.signal(signal.SIGINT, on_sigint)

    # ── Reader thread: PTY → stdout ──
    def reader():
        nonlocal last_size
        while not stop.is_set():
            try:
                data = proc.read(4096)
                if data:
                    sys.stdout.write(data)
                    sys.stdout.flush()
                # Resize detection
                new = _terminal_size()
                if new != last_size:
                    last_size = new
                    try:
                        proc.setwinsize(*new)
                    except Exception:
                        pass
            except EOFError:
                break
            except Exception:
                if not stop.is_set():
                    time.sleep(0.05)
        stop.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    # ── Terminal response filter ──
    # CLI apps (Claude, etc.) send terminal queries:
    #   \x1b[c        Primary DA
    #   \x1b[>c       Secondary DA
    #   \x1b[>q       XTVERSION
    #   \x1b[?...n    DECRPM
    # The host terminal (VSCode xterm.js) responds via stdin:
    #   \x1b[?61;...c       Primary DA response
    #   \x1b[>...c          Secondary DA response
    #   \x1bP>|...\x1b\\    XTVERSION DCS response
    #   \x1b[?...;...$y     DECRPM response
    # We must parse and discard these, NOT forward to PTY.

    def _drain_escape(first_after_esc: str) -> str | None:
        """After reading ESC + one char, consume the full terminal response
        sequence if it matches known patterns. Returns None if consumed
        (terminal response), or the raw string to forward if it's a
        user-initiated ESC sequence we don't recognize as a response."""

        buf = first_after_esc

        if first_after_esc == "[":
            # CSI sequence: \x1b[ ... <letter>
            # Read until we get a final byte (0x40-0x7E)
            while msvcrt.kbhit():
                ch = msvcrt.getwch()
                buf += ch
                if "\x40" <= ch <= "\x7e":  # @ through ~
                    break
            # Check if this is a terminal response
            # DA response: ends with 'c'  (\x1b[?...c or \x1b[>...c)
            # DECRPM: ends with 'y' and contains '$'  (\x1b[?...;...$y)
            # DSR: ends with 'n'
            if buf.endswith("c") or buf.endswith("y") or buf.endswith("n"):
                return None  # Terminal response → discard
            # Not a response — could be user pressing Alt+[ or similar
            return "\x1b" + buf

        elif first_after_esc == "P":
            # DCS sequence: \x1bP ... \x1b\\  (ST = String Terminator)
            # This is XTVERSION response: \x1bP>|xterm.js(...)\x1b\\
            # Read until ST (\x1b\\) or timeout
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    buf += ch
                    # Check for ST: the char before this was \x1b and this is \\
                    if len(buf) >= 2 and buf[-2] == "\x1b" and buf[-1] == "\\":
                        return None  # DCS response complete → discard
                else:
                    time.sleep(0.005)
            # Timeout — discard partial DCS anyway (it's not user input)
            return None

        elif first_after_esc == "]":
            # OSC sequence: \x1b] ... (BEL or ST)
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    buf += ch
                    if ch == "\x07":  # BEL terminator
                        return None
                    if len(buf) >= 2 and buf[-2] == "\x1b" and buf[-1] == "\\":
                        return None  # ST terminator
                else:
                    time.sleep(0.005)
            return None

        else:
            # Unknown ESC + char — probably user pressing Alt+key
            return "\x1b" + buf

    # ── Initial drain (brief, for early responses) ──
    drain_end = time.monotonic() + 2.0
    while time.monotonic() < drain_end:
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch == "\x1b" and msvcrt.kbhit():
                _drain_escape(msvcrt.getwch())  # Consume response
            # else: discard stray chars during startup
        time.sleep(0.02)

    # ── stdin → PTY ──
    try:
        while not stop.is_set() and proc.isalive():
            if not msvcrt.kbhit():
                time.sleep(0.01)
                continue

            ch = msvcrt.getwch()

            if ch in ("\r", "\n"):
                proc.write("\r")
            elif ch in ("\x00", "\xe0"):
                key = msvcrt.getwch()
                ansi = _SPECIAL_KEYS.get(key, "")
                if ansi:
                    proc.write(ansi)
            elif ch == "\t":
                proc.write("\t")
            elif ch == "\x1b":
                # ESC received — is this a terminal response or user input?
                if msvcrt.kbhit():
                    next_ch = msvcrt.getwch()
                    result = _drain_escape(next_ch)
                    if result is not None:
                        # Not a terminal response — forward to PTY
                        proc.write(result)
                    # else: terminal response consumed and discarded
                else:
                    # Bare ESC with nothing following — user pressed Escape
                    proc.write("\x1b")
            else:
                proc.write(ch)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, prev_handler)
        stop.set()
        if proc.isalive():
            proc.terminate()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Minimal PTY terminal passthrough")
    p.add_argument("command", nargs="?", default="claude --verbose",
                   help="Command to run (default: claude --verbose)")
    p.add_argument("--cwd", default=".", help="Working directory")
    args = p.parse_args()
    run(args.command, args.cwd)
