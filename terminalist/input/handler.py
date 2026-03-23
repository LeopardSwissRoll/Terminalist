"""Input event handler — platform-agnostic event processing.

Processes batches of KeyEvents and produces PTY write actions.
Responsibilities:
- Paste detection (prompt-toolkit heuristic)
- DA response filter (ESC sequence accumulation)
- Key translation (backspace → DEL, Shift+Enter → \\n)
- Prefix key FSM (Ctrl+B → next key)
- Bracketed paste wrapping

Does NOT touch console APIs — that's win32.py's job.
"""

from __future__ import annotations

import signal
import sys
import time
import traceback
from collections.abc import Callable

from terminalist.debug import log
from .keymap_vk import SPECIAL_VK, MODIFIER_VKS, VK_PROCESSKEY
from .win32 import (
    KeyEvent,
    has_events,
    is_shift_pressed,
    read_batch,
    read_key_blocking,
    terminal_size,
)


def run_input_loop(
    h_in: int,
    write: Callable[[str], None],
    is_alive: Callable[[], bool],
    resize: Callable[[int, int], None] | None = None,
    initial_size: tuple[int, int] = (30, 120),
) -> None:
    """Main input loop: read console events → translate → write to PTY.

    Args:
        h_in: Console input handle (from RawConsoleInput).
        write: Function to write data to PTY (e.g. session.write_raw).
        is_alive: Function returning True if PTY process is alive.
        resize: Optional (cols, rows) resize callback.
        initial_size: Starting (rows, cols) for resize tracking.
    """
    stop = False
    last_size = initial_size
    da_buf: str | None = None
    bracketed_paste = False
    input_count = 0

    # ── Ctrl+C: forward to PTY via SIGINT handler ──
    prev_handler = signal.getsignal(signal.SIGINT)

    def on_sigint(_s, _f):
        log("key", "SIGINT → forwarding \\x03 to PTY")
        try:
            write("\x03")
        except Exception:
            pass

    signal.signal(signal.SIGINT, on_sigint)

    # ── Bracketed paste tracker (called externally on PTY output) ──
    def track_bracketed_paste(data: str) -> None:
        nonlocal bracketed_paste
        if "\x1b[?2004h" in data:
            bracketed_paste = True
            log("input", "Bracketed paste mode ON")
        if "\x1b[?2004l" in data:
            bracketed_paste = False
            log("input", "Bracketed paste mode OFF")

    # Expose for caller to hook into raw output
    run_input_loop.track_bracketed_paste = track_bracketed_paste  # type: ignore[attr-defined]

    log("input", "Entering input loop (ReadConsoleInputW)")
    log("input", "Exit: Ctrl+B → Ctrl+C (tmux style)")

    try:
        while not stop and is_alive():
            # ── Resize check ──
            if resize:
                new = terminal_size()
                if new != last_size:
                    last_size = new
                    resize(new[1], new[0])  # cols, rows
                    log("app", f"Resize detected: {new[1]}x{new[0]}")

            # ── Read batch ──
            if not has_events(h_in):
                time.sleep(0.01)
                continue

            events = read_batch(h_in)
            if not events:
                continue

            # ── Paste detection ──
            paste_text = _detect_paste(events)
            if paste_text is not None:
                paste_text = paste_text.replace("\r\n", "\r").replace("\n", "\r")
                if bracketed_paste:
                    write(f"\x1b[200~{paste_text}\x1b[201~")
                    log("key", f"PASTE bracketed ({len(paste_text)} chars)")
                else:
                    write(paste_text)
                    log("key", f"PASTE ({len(paste_text)} chars)")
                input_count += len(events)
                continue

            # ── Process events one by one ──
            for ch, vk, ctrl, repeat in events:
                input_count += 1

                # IME processed key — skip
                if vk == VK_PROCESSKEY:
                    log("key", f"#{input_count} VK_PROCESSKEY ch={ch!r} (skip)")
                    continue

                # IME confirmed (vk=0x0000) — DA filter + Korean
                if ch and vk == 0x0000:
                    da_buf = _da_filter(ch, da_buf, input_count)
                    if da_buf is not None or da_buf == "":
                        # Still accumulating or just cleared — either way, consumed
                        continue
                    # da_buf is None means _da_filter returned None = forwarded char
                    write(ch)
                    log("key", f"#{input_count} IME confirmed: {ch!r} (U+{ord(ch):04X})")
                    continue

                # Ctrl+C → forward to PTY
                if ch == "\x03":
                    write("\x03")
                    log("key", f"#{input_count} Ctrl+C → PTY")
                    continue

                # Ctrl+B → prefix key (exit sequence)
                if ch == "\x02":
                    should_exit = _handle_prefix(h_in, write, input_count)
                    if should_exit:
                        stop = True
                        break
                    continue

                # Special keys (arrows, F-keys, etc.)
                if ch is None and vk in SPECIAL_VK:
                    write(SPECIAL_VK[vk])
                    log("key", f"#{input_count} special: vk=0x{vk:04X}")
                    continue

                # Regular character
                if ch:
                    _handle_char(ch, write, input_count)
                    continue

                log("key", f"#{input_count} unhandled: ch={ch!r} vk=0x{vk:04X}")

            if stop:
                break

    except Exception as e:
        log("app", f"INPUT LOOP CRASHED: {type(e).__name__}: {e}")
        log("app", traceback.format_exc())
        print(f"\n[terminalist] Input loop error: {e}", file=sys.stderr)
    finally:
        signal.signal(signal.SIGINT, prev_handler)

    log("app", f"Input loop ended. Total inputs: {input_count}")


# ── Paste detection ──


def _detect_paste(events: list[KeyEvent]) -> str | None:
    """Detect paste using prompt-toolkit heuristic.

    Returns joined text if paste detected, None otherwise.
    """
    text_chars: list[str] = []
    has_newline = False
    has_text = False
    is_pure_text = True

    for ch, vk, ctrl, repeat in events:
        if vk == VK_PROCESSKEY:
            continue
        if ch is None and vk in MODIFIER_VKS:
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
        return "".join(text_chars)
    return None


# ── DA response filter ──

# Module-level DA buffer (persists across calls within one input loop)
_da_state: str | None = None


def _da_filter(ch: str, da_buf: str | None, input_count: int) -> str | None:
    """Filter DA responses arriving as vk=0x0000 chars.

    Returns updated da_buf (non-None = still accumulating).
    Returns None = char should be forwarded to PTY.
    """
    if ch == "\x1b" or da_buf is not None:
        if ch == "\x1b":
            da_buf = ch
        else:
            da_buf += ch
        if len(da_buf) >= 3 and da_buf[1] == "[" and "\x40" <= da_buf[-1] <= "\x7e":
            log("input", f"#{input_count} DA response filtered: {da_buf!r}")
            return ""  # empty string = "consumed, reset buffer"
        elif len(da_buf) > 50:
            log("input", f"#{input_count} DA buffer overflow, discarding")
            return ""
        return da_buf  # still accumulating
    return None  # not a DA sequence — forward the char


# ── Prefix key (Ctrl+B) ──


def _handle_prefix(h_in: int, write: Callable[[str], None], input_count: int) -> bool:
    """Handle Ctrl+B prefix key. Returns True if should exit."""
    log("key", f"#{input_count} PREFIX (Ctrl+B) — waiting for next key...")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if has_events(h_in):
            break
        time.sleep(0.01)
    else:
        write("\x02")
        log("key", f"#{input_count} PREFIX timeout → send literal Ctrl+B")
        return False

    ch2, vk2, ctrl2, repeat2 = read_key_blocking(h_in)
    if ch2 == "\x03":
        log("app", "PREFIX → Ctrl+C → exiting")
        return True
    elif ch2 == "\x02":
        write("\x02")
        log("key", f"#{input_count} PREFIX → Ctrl+B → send literal")
    else:
        log("key", f"#{input_count} PREFIX → {ch2!r} vk=0x{vk2:04X} (unbound)")
    return False


# ── Regular character handling ──


def _handle_char(ch: str, write: Callable[[str], None], input_count: int) -> None:
    """Translate and forward a regular character."""
    if ch in ("\r", "\n"):
        if is_shift_pressed():
            write("\n")
            log("key", f"#{input_count} Shift+Enter → \\n")
        else:
            write("\r")
            log("key", f"#{input_count} Enter")
    elif ch == "\t":
        write("\t")
        log("key", f"#{input_count} Tab")
    elif ch == "\x1b":
        write("\x1b")
        log("key", f"#{input_count} Escape")
    elif ch == "\x08":
        write("\x7f")  # Backspace → DEL
        log("key", f"#{input_count} Backspace")
    elif ord(ch) < 0x20:
        write(ch)
        log("key", f"#{input_count} control: 0x{ord(ch):02X}")
    else:
        write(ch)
        if input_count % 20 == 0:
            log("key", f"#{input_count} char: {ch!r}")
