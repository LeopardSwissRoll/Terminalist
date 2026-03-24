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
from dataclasses import dataclass, field

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


# ── InputState — mutable state shared across process_events calls ──


@dataclass
class InputState:
    """Mutable state for input processing across ticks."""
    da_buf: str | None = None
    bracketed_paste: bool = False
    input_count: int = 0

    def track_bracketed_paste(self, data: str) -> None:
        """Call from raw PTY output tap to track mode 2004."""
        if "\x1b[?2004h" in data:
            self.bracketed_paste = True
            log("input", "Bracketed paste mode ON")
        if "\x1b[?2004l" in data:
            self.bracketed_paste = False
            log("input", "Bracketed paste mode OFF")


# ── Core event processing (used by both app.py and run_input_loop) ──


def process_events(
    events: list[KeyEvent],
    write: Callable[[str], None],
    state: InputState,
    on_prefix_key: Callable[[str, int], None] | None = None,
    h_in: int | None = None,
) -> str | None:
    """Process a batch of key events. Returns prefix action if Ctrl+B was pressed.

    Args:
        events: Batch of (ch, vk, ctrl, repeat) tuples from read_batch().
        write: Function to write data to active PTY.
        state: Mutable InputState (DA buffer, bracketed paste, counter).
        on_prefix_key: Callback(action_name, input_count) for prefix actions.
            If None, uses legacy _handle_prefix (for run_input_loop compat).
        h_in: Console input handle (needed for legacy prefix handling).

    Returns:
        "exit" if should stop, None otherwise.
    """
    # ── Paste detection ──
    paste_text = _detect_paste(events)
    if paste_text is not None:
        paste_text = paste_text.replace("\r\n", "\r").replace("\n", "\r")
        if state.bracketed_paste:
            write(f"\x1b[200~{paste_text}\x1b[201~")
            log("key", f"PASTE bracketed ({len(paste_text)} chars)")
        else:
            write(paste_text)
            log("key", f"PASTE ({len(paste_text)} chars)")
        state.input_count += len(events)
        return None

    # ── Process events one by one ──
    for ch, vk, ctrl, repeat in events:
        state.input_count += 1
        n = state.input_count

        # IME processed key — skip
        if vk == VK_PROCESSKEY:
            log("key", f"#{n} VK_PROCESSKEY ch={ch!r} (skip)")
            continue

        # IME confirmed (vk=0x0000) — DA filter + Korean
        if ch and vk == 0x0000:
            result = _da_filter(ch, state.da_buf, n)
            if result is None:
                state.da_buf = None
                write(ch)
                log("key", f"#{n} IME confirmed: {ch!r} (U+{ord(ch):04X})")
            elif result == "":
                state.da_buf = None
            else:
                state.da_buf = result
            continue

        # Ctrl+C → forward to PTY
        if ch == "\x03":
            write("\x03")
            log("key", f"#{n} Ctrl+C → PTY")
            continue

        # Ctrl+B → prefix key
        if ch == "\x02":
            if on_prefix_key is not None:
                # App mode: read next key, resolve action, call back
                action = _read_prefix_action(h_in, write, n)
                if action:
                    on_prefix_key(action, n)
            else:
                # Legacy mode (interactive.py)
                if _handle_prefix(h_in, write, n):
                    return "exit"
            continue

        # Special keys (arrows, F-keys, etc.)
        if ch is None and vk in SPECIAL_VK:
            write(SPECIAL_VK[vk])
            log("key", f"#{n} special: vk=0x{vk:04X}")
            continue

        # Regular character
        if ch:
            _handle_char(ch, write, n)
            continue

        log("key", f"#{n} unhandled: ch={ch!r} vk=0x{vk:04X}")

    return None


# ── Prefix key resolution ──

# Import here to avoid circular — keymap is a pure data module
_PREFIX_MAP: dict[str, str] | None = None


def _get_prefix_map() -> dict[str, str]:
    """Lazy-load prefix action map from keymap.py."""
    global _PREFIX_MAP
    if _PREFIX_MAP is None:
        from terminalist.keymap import prefix_action_map
        _PREFIX_MAP = prefix_action_map()
    return _PREFIX_MAP


def _vk_to_key_name(ch: str | None, vk: int) -> str | None:
    """Convert a ReadConsoleInputW event to a keymap key name."""
    if ch == "\x03":
        return "ctrl+c"
    if ch == "\x02":
        return "ctrl+b"
    if ch and ord(ch) >= 0x20:
        return ch
    # Arrow keys
    vk_names = {0x26: "up", 0x28: "down", 0x25: "left", 0x27: "right"}
    if vk in vk_names:
        return vk_names[vk]
    return None


def _read_prefix_action(
    h_in: int, write: Callable[[str], None], input_count: int,
) -> str | None:
    """Wait for next key after Ctrl+B, resolve to action name."""
    log("key", f"#{input_count} PREFIX (Ctrl+B) — waiting...")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if has_events(h_in):
            break
        time.sleep(0.01)
    else:
        write("\x02")
        log("key", f"#{input_count} PREFIX timeout → send literal Ctrl+B")
        return None

    ch2, vk2, ctrl2, repeat2 = read_key_blocking(h_in)
    key_name = _vk_to_key_name(ch2, vk2)
    if key_name is None:
        log("key", f"#{input_count} PREFIX → ch={ch2!r} vk=0x{vk2:04X} (no key name)")
        return None

    prefix_map = _get_prefix_map()
    action = prefix_map.get(key_name)
    if action:
        log("key", f"#{input_count} PREFIX → {key_name!r} → action={action}")
        return action

    log("key", f"#{input_count} PREFIX → {key_name!r} (unbound)")
    return None


# ── Legacy run_input_loop (interactive.py backward compat) ──


def run_input_loop(
    h_in: int,
    write: Callable[[str], None],
    is_alive: Callable[[], bool],
    resize: Callable[[int, int], None] | None = None,
    initial_size: tuple[int, int] = (30, 120),
) -> None:
    """Main input loop for single-session mode (interactive.py).

    For multi-pane app.py, use process_events() directly instead.
    """
    last_size = initial_size
    state = InputState()

    prev_handler = signal.getsignal(signal.SIGINT)

    def on_sigint(_s, _f):
        log("key", "SIGINT → forwarding \\x03 to PTY")
        try:
            write("\x03")
        except Exception:
            pass

    signal.signal(signal.SIGINT, on_sigint)

    # Expose bracketed paste tracker for raw output tap
    run_input_loop.track_bracketed_paste = state.track_bracketed_paste  # type: ignore[attr-defined]

    log("input", "Entering input loop (ReadConsoleInputW)")
    log("input", "Exit: Ctrl+B → Ctrl+C (tmux style)")

    try:
        while is_alive():
            if resize:
                new = terminal_size()
                if new != last_size:
                    last_size = new
                    resize(new[1], new[0])
                    log("app", f"Resize detected: {new[1]}x{new[0]}")

            if not has_events(h_in):
                time.sleep(0.01)
                continue

            keys, _mice = read_batch(h_in)
            if not keys:
                continue

            result = process_events(keys, write, state, on_prefix_key=None, h_in=h_in)
            if result == "exit":
                break

    except Exception as e:
        log("app", f"INPUT LOOP CRASHED: {type(e).__name__}: {e}")
        log("app", traceback.format_exc())
        print(f"\n[terminalist] Input loop error: {e}", file=sys.stderr)
    finally:
        signal.signal(signal.SIGINT, prev_handler)

    log("app", f"Input loop ended. Total inputs: {state.input_count}")


# ── Paste detection ──


def _detect_paste(events: list[KeyEvent]) -> str | None:
    """Detect paste using prompt-toolkit heuristic."""
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


def _da_filter(ch: str, da_buf: str | None, input_count: int) -> str | None:
    """Filter DA responses arriving as vk=0x0000 chars."""
    if ch == "\x1b" or da_buf is not None:
        if ch == "\x1b":
            da_buf = ch
        else:
            da_buf += ch
        if len(da_buf) >= 3 and da_buf[1] == "[" and "\x40" <= da_buf[-1] <= "\x7e":
            log("input", f"#{input_count} DA response filtered: {da_buf!r}")
            return ""
        elif len(da_buf) > 50:
            log("input", f"#{input_count} DA buffer overflow, discarding")
            return ""
        return da_buf
    return None


# ── Legacy prefix handler (for run_input_loop) ──


def _handle_prefix(h_in: int, write: Callable[[str], None], input_count: int) -> bool:
    """Handle Ctrl+B prefix key. Returns True if should exit."""
    action = _read_prefix_action(h_in, write, input_count)
    if action == "confirm_quit":
        log("app", "PREFIX → Ctrl+C → exiting")
        return True
    if action == "send_prefix_char":
        write("\x02")
        log("key", f"#{input_count} PREFIX → Ctrl+B → send literal")
    # Other actions ignored in single-session mode
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
