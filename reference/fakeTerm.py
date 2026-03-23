"""fakeTerm — PTY virtual terminal passthrough.

Spawns a CLI process inside a PTY and bridges it to the current terminal.
User sees and interacts with the process as if running it directly.

Input: ReadConsoleInputW (Korean IME, paste detection, all modifiers)
Output: PTY → stdout (raw passthrough)

Usage:
    python fakeTerm.py                          # default: powershell
    python fakeTerm.py "claude --verbose"
    python fakeTerm.py "codex --no-alt-screen"
    python fakeTerm.py "python"
    python fakeTerm.py "claude" --cwd ~/myproject

Exit: Ctrl+B then Ctrl+C (tmux style).
      Ctrl+B twice → send literal Ctrl+B to PTY.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import signal
import sys
import threading
import time

# ── Windows Console API ──

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
KEY_EVENT = 0x0001
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
VK_PROCESSKEY = 0xE5
VK_SHIFT = 0x10

# Modifier-only VK codes (no character, just modifier state)
_MODIFIER_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}


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


def _enable_vt():
    """Enable ANSI escape processing on Windows console."""
    h = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
    mode = ctypes.c_ulong()
    kernel32.GetConsoleMode(h, ctypes.byref(mode))
    kernel32.SetConsoleMode(h, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)


# ── Special key VK → ANSI escape sequence ──

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


def _terminal_size() -> tuple[int, int]:
    """Return (rows, cols)."""
    try:
        cols, rows = os.get_terminal_size()
        return max(rows, 10), max(cols, 40)
    except OSError:
        return 30, 120


# ── Console input reading ──

def _read_one_record(h_in: int) -> tuple[str | None, int, int, int] | None:
    """Read one console input record. Non-blocking per record.

    Returns (char_or_none, vk, ctrl, repeat) for KEY_DOWN, None otherwise.
    Caller must check avail > 0 before calling.
    """
    record = INPUT_RECORD()
    read_count = wt.DWORD()
    kernel32.ReadConsoleInputW(h_in, ctypes.byref(record), 1, ctypes.byref(read_count))
    if record.EventType != KEY_EVENT:
        return None
    ke = record.Event.KeyEvent
    if not ke.bKeyDown:
        return None
    ch = ke.uChar
    vk = ke.wVirtualKeyCode
    ctrl = ke.dwControlKeyState
    repeat = ke.wRepeatCount
    return (ch if ch and ch != "\x00" else None, vk, ctrl, repeat)


def _read_console_input(h_in: int) -> tuple[str | None, int, int, int]:
    """Read one KEY_DOWN event. Blocks until one arrives."""
    while True:
        result = _read_one_record(h_in)
        if result is not None:
            return result


def run(command: str, cwd: str | None = None) -> None:
    from winpty import PtyProcess

    _enable_vt()
    rows, cols = _terminal_size()

    # ── Alt screen ──
    sys.stdout.write("\x1b[?1049h\x1b[H\x1b[2J")
    sys.stdout.flush()

    proc = PtyProcess.spawn(command, cwd=cwd or ".", dimensions=(rows, cols))
    stop = threading.Event()
    last_size = (rows, cols)

    # ── Ctrl+C → always forward to PTY ──
    prev_handler = signal.getsignal(signal.SIGINT)

    def on_sigint(_s, _f):
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

    # ── Console raw mode ──
    h_in = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    old_mode = wt.DWORD()
    kernel32.GetConsoleMode(h_in, ctypes.byref(old_mode))
    kernel32.SetConsoleMode(h_in, 0)

    # ── DA response filter state ──
    # DA responses arrive as vk=0x0000 chars one at a time:
    #   \x1b [ ? 6 1 ; ... c
    # We accumulate and discard them instead of forwarding to PTY.
    da_buf: str | None = None

    # ── Input loop ──
    try:
        while not stop.is_set() and proc.isalive():
            avail = wt.DWORD()
            kernel32.GetNumberOfConsoleInputEvents(h_in, ctypes.byref(avail))
            if avail.value == 0:
                time.sleep(0.01)
                continue

            # ── Batch read (non-blocking per record) ──
            events: list[tuple[str | None, int, int, int]] = []
            while True:
                avail2 = wt.DWORD()
                kernel32.GetNumberOfConsoleInputEvents(h_in, ctypes.byref(avail2))
                if avail2.value == 0:
                    break
                result = _read_one_record(h_in)
                if result is not None:
                    events.append(result)
                if len(events) >= 4096:
                    break

            if not events:
                continue

            # ── Paste detection ──
            # Heuristic: batch has text + newlines + no special keys → paste.
            # (prompt-toolkit approach)
            text_chars: list[str] = []
            has_newline = False
            has_text = False
            is_pure_text = True
            for ch, vk, ctrl, repeat in events:
                if vk == VK_PROCESSKEY:
                    continue
                if ch is None and vk in _MODIFIER_VKS:
                    continue
                if ch and vk == 0x0000 and ch != "\x1b":
                    text_chars.append(ch)
                    has_text = True
                elif ch and ch in ("\r", "\n"):
                    text_chars.append(ch)
                    has_newline = True
                elif ch and ord(ch) >= 0x20:
                    text_chars.append(ch)
                    has_text = True
                else:
                    is_pure_text = False

            if has_newline and has_text and is_pure_text and len(text_chars) > 2:
                paste_text = "".join(text_chars)
                paste_text = paste_text.replace("\r\n", "\r").replace("\n", "\r")
                proc.write(paste_text)
                continue

            # ── Process events one by one ──
            for ch, vk, ctrl, repeat in events:
                if vk == VK_PROCESSKEY:
                    continue

                # DA response filter (vk=0x0000 ESC sequences)
                if ch and vk == 0x0000:
                    if ch == "\x1b" or da_buf is not None:
                        if ch == "\x1b":
                            da_buf = ch
                        else:
                            da_buf += ch
                        if len(da_buf) >= 3 and da_buf[1] == "[" and "\x40" <= da_buf[-1] <= "\x7e":
                            da_buf = None  # complete DA response — discard
                        elif len(da_buf) > 50:
                            da_buf = None  # overflow — discard
                        continue
                    # IME confirmed character (Korean etc.)
                    proc.write(ch)
                    continue

                # Ctrl+C → forward to PTY
                if ch == "\x03":
                    proc.write("\x03")
                    continue

                # Ctrl+B → prefix key (exit: Ctrl+B then Ctrl+C)
                if ch == "\x02":
                    deadline = time.monotonic() + 2.0
                    while time.monotonic() < deadline:
                        a = wt.DWORD()
                        kernel32.GetNumberOfConsoleInputEvents(h_in, ctypes.byref(a))
                        if a.value > 0:
                            break
                        time.sleep(0.01)
                    else:
                        proc.write("\x02")  # timeout → send literal
                        continue
                    ch2, vk2, ctrl2, repeat2 = _read_console_input(h_in)
                    if ch2 == "\x03":
                        stop.set()
                        break  # exit
                    elif ch2 == "\x02":
                        proc.write("\x02")  # Ctrl+B twice → literal
                    continue

                # Special keys (arrows, home, end, etc.)
                if ch is None and vk in _SPECIAL_VK:
                    proc.write(_SPECIAL_VK[vk])
                    continue

                # Regular characters
                if ch:
                    if ch in ("\r", "\n"):
                        # Shift+Enter → \n (newline without execute)
                        if user32.GetAsyncKeyState(VK_SHIFT) & 0x8000:
                            proc.write("\n")
                        else:
                            proc.write("\r")
                    elif ch == "\t":
                        proc.write("\t")
                    elif ch == "\x1b":
                        proc.write("\x1b")
                    elif ch == "\x08":
                        proc.write("\x7f")  # Backspace → DEL (PSReadLine compat)
                    else:
                        proc.write(ch)

    except KeyboardInterrupt:
        pass
    finally:
        kernel32.SetConsoleMode(h_in, old_mode)
        signal.signal(signal.SIGINT, prev_handler)
        stop.set()
        # ── Exit alt screen ──
        sys.stdout.write("\x1b[?1049l")
        sys.stdout.flush()
        if proc.isalive():
            try:
                proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="PTY virtual terminal passthrough")
    p.add_argument("command", nargs="?", default="powershell",
                   help="Command to run (default: powershell)")
    p.add_argument("--cwd", default=".", help="Working directory")
    args = p.parse_args()
    run(args.command, args.cwd)
