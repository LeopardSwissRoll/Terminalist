"""Keymap — Single source of truth for Terminalist action bindings.

Defines WHAT actions exist and WHICH keys trigger them.
For raw key translation (VK → ANSI), see input/keymap_vk.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KeyDef:
    """A single keybinding definition."""
    key: str            # Textual key name (e.g. "n", "ctrl+q")
    action: str         # Action method name (e.g. "new_session", "quit")
    label: str          # Human-readable label for UI display
    show_footer: bool = False  # Show in Footer bar


# ── Global keys (always active, even when pane is focused) ──

GLOBAL_KEYS: list[KeyDef] = [
    KeyDef("ctrl+shift+c", "copy_selected_text", "Copy"),
]

# ── Prefix keys (Ctrl+B → next key) ──
# These are the tmux-style commands after pressing the prefix.

# tmux-compatible prefix key.
# Windows input backend selection tries to preserve this inside VS Code too.
PREFIX_KEY = "ctrl+b"

PREFIX_KEYS: list[KeyDef] = [
    KeyDef("c", "new_claude", "New Claude"),
    KeyDef("o", "new_codex", "New Codex"),
    KeyDef("s", "new_shell", "New Shell"),
    KeyDef("v", "split_vertical", "VSplit"),
    KeyDef("h", "split_horizontal", "HSplit"),
    KeyDef("x", "close_pane", "Close Pane"),
    # Pane navigation (tmux: arrow keys to select pane)
    KeyDef("up", "focus_pane_up", "Pane Up"),
    KeyDef("down", "focus_pane_down", "Pane Down"),
    KeyDef("left", "focus_pane_left", "Pane Left"),
    KeyDef("right", "focus_pane_right", "Pane Right"),
    # Tab navigation (tmux: n/p for next/prev window, 0-9 for window number)
    KeyDef("n", "next_tab", "Next Tab"),
    KeyDef("p", "prev_tab", "Prev Tab"),
    KeyDef("1", "goto_tab_1", "Tab 1"),
    KeyDef("2", "goto_tab_2", "Tab 2"),
    KeyDef("3", "goto_tab_3", "Tab 3"),
    KeyDef("4", "goto_tab_4", "Tab 4"),
    KeyDef("5", "goto_tab_5", "Tab 5"),
    # Pane zoom (toggle fullscreen)
    KeyDef("z", "zoom_pane", "Zoom"),
    # Session management
    KeyDef("d", "detach", "Detach"),
    # Ctrl+B → Ctrl+C = quit
    KeyDef("ctrl+c", "confirm_quit", "Quit"),
    # Prefix twice → send literal prefix char to PTY
    KeyDef("ctrl+b", "send_prefix_char", "Send ^B"),
]

# ── Pane-local keys (only when pane is focused) ──

DETACH_KEY = "ctrl+right_square_bracket"  # Ctrl+] → blur/detach

# ── Derived helpers ──

def prefix_action_map() -> dict[str, str]:
    """Build key → action name mapping for handle_global_key."""
    return {k.key: k.action for k in PREFIX_KEYS}


def prefix_hints_string() -> str:
    """Build the hint string shown in sub_title during prefix mode."""
    seen: set[str] = set()
    parts: list[str] = []
    for k in PREFIX_KEYS:
        if k.action not in seen:
            seen.add(k.action)
            display_key = k.key.replace("ctrl+", "^")
            parts.append(f"{display_key}:{k.label}")
    return "  ".join(parts)


def defined_keys() -> tuple[str, ...]:
    """Return every key name declared by Terminalist."""
    return (
        *(k.key for k in GLOBAL_KEYS),
        PREFIX_KEY,
        *(k.key for k in PREFIX_KEYS),
        DETACH_KEY,
    )
