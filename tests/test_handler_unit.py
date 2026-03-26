"""Tier 1: Pure function unit tests for input handler logic.

No Windows API needed — tests handler functions with synthetic KeyEvent tuples.
Catches logic bugs like DA filter poisoning Korean input.

Run: python tests/test_handler_unit.py
     python -m pytest tests/test_handler_unit.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from terminalist.input.handler import InputState, _detect_paste, _da_filter, _handle_char, process_events
from terminalist.input.keymap_vk import VK_PROCESSKEY, MODIFIER_VKS, SPECIAL_VK
from terminalist.input.win32 import MOUSE_WHEELED

# KeyEvent = (char|None, vk, ctrl, repeat)

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


# ══════════════════════════════════════════════
#  _da_filter tests
# ══════════════════════════════════════════════

def test_da_filter_korean_passthrough():
    """Korean char (not ESC) should return None = forward to PTY."""
    result = _da_filter("한", None, 1)
    assert result is None, f"Expected None, got {result!r}"


def test_da_filter_esc_starts_accumulation():
    """ESC should start DA accumulation."""
    result = _da_filter("\x1b", None, 1)
    assert result == "\x1b", f"Expected '\\x1b', got {result!r}"


def test_da_filter_csi_accumulation():
    """ESC[ should continue accumulating."""
    result = _da_filter("[", "\x1b", 2)
    assert result == "\x1b[", f"Expected '\\x1b[', got {result!r}"


def test_da_filter_complete_response():
    """ESC[...c should complete and return empty string."""
    result = _da_filter("c", "\x1b[?61", 5)
    assert result == "", f"Expected '', got {result!r}"


def test_da_filter_overflow():
    """Buffer > 50 chars should be discarded."""
    long_buf = "\x1b[" + "x" * 49
    result = _da_filter("y", long_buf, 99)
    assert result == "", f"Expected '', got {result!r}"


def test_da_filter_korean_after_da_completion():
    """CRITICAL: Korean char after DA completion must NOT be swallowed.

    This was the bug: _da_filter returned '' for DA completion,
    caller set da_buf='', next Korean char hit da_buf='' (not None)
    → _da_filter treated it as accumulating → Korean silently eaten.
    """
    # Simulate: DA response completes, then Korean char arrives
    buf = None

    # DA sequence: ESC [ ? 6 1 c
    buf = _da_filter("\x1b", buf, 1)
    assert buf == "\x1b"
    buf = _da_filter("[", buf, 2)
    assert buf == "\x1b["
    buf = _da_filter("?", buf, 3)
    buf = _da_filter("6", buf, 4)
    buf = _da_filter("1", buf, 5)
    buf = _da_filter("c", buf, 6)
    assert buf == "", "DA should complete with empty string"

    # Caller must reset buf to None after ""
    buf = None  # This is what the fix does

    # Now Korean char arrives
    result = _da_filter("한", buf, 7)
    assert result is None, f"Korean after DA must return None (forward), got {result!r}"


def test_da_filter_korean_after_da_BUG_simulation():
    """Simulate the OLD bug: if caller forgets to reset buf after ''."""
    buf = ""  # Bug: caller didn't reset to None

    # Korean char hits buf="" (not None) → _da_filter treats as accumulating
    result = _da_filter("한", buf, 1)
    # With the bug, this returns "한" (accumulating) instead of None (forward)
    # The fix ensures caller always resets to None, so this case shouldn't happen
    # But if it does, at least document what _da_filter does
    assert result is not None, "With buf='', _da_filter accumulates (this is the bug scenario)"


# ══════════════════════════════════════════════
#  _detect_paste tests
# ══════════════════════════════════════════════

def test_paste_text_with_newline():
    """Text + newline = paste."""
    events = [
        ("h", 0x48, 0, 1),
        ("e", 0x45, 0, 1),
        ("l", 0x4C, 0, 1),
        ("l", 0x4C, 0, 1),
        ("o", 0x4F, 0, 1),
        ("\r", 0x0D, 0, 1),
        ("w", 0x57, 0, 1),
    ]
    result = _detect_paste(events)
    assert result is not None, "Should detect paste"
    assert "hello" in result
    assert "w" in result


def test_paste_single_char_not_paste():
    """Single char is not paste."""
    events = [("a", 0x41, 0, 1)]
    assert _detect_paste(events) is None


def test_paste_text_only_no_newline():
    """Text without newline is not paste."""
    events = [("a", 0x41, 0, 1), ("b", 0x42, 0, 1), ("c", 0x43, 0, 1)]
    assert _detect_paste(events) is None


def test_paste_newline_only():
    """Newline only is not paste."""
    events = [("\r", 0x0D, 0, 1)]
    assert _detect_paste(events) is None


def test_paste_with_special_keys_not_paste():
    """Batch with special keys (arrows etc.) is not paste."""
    events = [
        ("h", 0x48, 0, 1),
        ("\r", 0x0D, 0, 1),
        (None, 0x26, 0, 1),  # VK_UP — breaks is_pure_text
    ]
    assert _detect_paste(events) is None


def test_paste_ignores_modifier_keys():
    """Shift/Ctrl/Alt events should not break paste detection."""
    events = [
        (None, 0x10, 0x10, 1),  # Shift down
        ("H", 0x48, 0x10, 1),
        ("i", 0x49, 0, 1),
        ("\r", 0x0D, 0, 1),
    ]
    result = _detect_paste(events)
    assert result is not None, "Modifier keys should not break paste detection"


def test_paste_ignores_vk_processkey():
    """VK_PROCESSKEY events should be skipped in paste detection."""
    events = [
        (None, VK_PROCESSKEY, 0, 1),
        ("한", 0x0000, 0, 1),
        ("\r", 0x0D, 0, 1),
        ("글", 0x0000, 0, 1),
    ]
    result = _detect_paste(events)
    assert result is not None, "VK_PROCESSKEY should be skipped"
    assert "한" in result and "글" in result


def test_paste_ime_confirmed_as_text():
    """IME confirmed chars (vk=0x0000) should be treated as text."""
    events = [
        ("가", 0x0000, 0, 1),
        ("나", 0x0000, 0, 1),
        ("다", 0x0000, 0, 1),
        ("\r", 0x0D, 0, 1),
    ]
    result = _detect_paste(events)
    assert result is not None
    assert "가나다" in result


# ══════════════════════════════════════════════
#  _handle_char tests
# ══════════════════════════════════════════════

def test_handle_char_enter():
    """Enter → \\r"""
    output = []
    with patch("terminalist.input.handler.is_shift_pressed", return_value=False):
        _handle_char("\r", output.append, 1)
    assert output == ["\r"], f"Expected ['\\r'], got {output}"


def test_handle_char_shift_enter():
    """Shift+Enter → \\n"""
    output = []
    with patch("terminalist.input.handler.is_shift_pressed", return_value=True):
        _handle_char("\r", output.append, 1)
    assert output == ["\n"], f"Expected ['\\n'], got {output}"


def test_handle_char_backspace_to_del():
    """Backspace (0x08) → DEL (0x7F)"""
    output = []
    _handle_char("\x08", output.append, 1)
    assert output == ["\x7f"], f"Expected ['\\x7f'], got {output}"


def test_handle_char_tab():
    output = []
    _handle_char("\t", output.append, 1)
    assert output == ["\t"]


def test_handle_char_escape():
    output = []
    _handle_char("\x1b", output.append, 1)
    assert output == ["\x1b"]


def test_handle_char_printable():
    output = []
    _handle_char("a", output.append, 1)
    assert output == ["a"]


def test_handle_char_control():
    """Control chars (< 0x20, not special-cased) pass through."""
    output = []
    _handle_char("\x04", output.append, 1)  # Ctrl+D
    assert output == ["\x04"]


def test_process_events_sgr_mouse_wheel_up():
    """SGR mouse wheel should route to mouse callback, not PTY."""
    output = []
    mouse = []
    state = InputState()
    events = [
        ("\x1b", 0x1B, 0, 1),
        ("[", ord("["), 0, 1),
        ("<", ord("<"), 0, 1),
        ("6", ord("6"), 0, 1),
        ("4", ord("4"), 0, 1),
        (";", ord(";"), 0, 1),
        ("1", ord("1"), 0, 1),
        ("0", ord("0"), 0, 1),
        (";", ord(";"), 0, 1),
        ("5", ord("5"), 0, 1),
        ("M", ord("M"), 0, 1),
    ]
    result = process_events(events, output.append, state, on_mouse_event=mouse.append)
    assert result is None
    assert output == [], f"SGR mouse must not reach PTY, got {output!r}"
    assert len(mouse) == 1
    assert mouse[0].x == 9 and mouse[0].y == 4
    assert mouse[0].flags == MOUSE_WHEELED
    assert mouse[0].buttons & 0x80000000, "wheel-up should keep Windows sign bit convention"


def test_process_events_sgr_mouse_left_click():
    """SGR left click should decode to a left-button MouseEvent."""
    output = []
    mouse = []
    state = InputState()
    events = [
        ("\x1b", 0x1B, 0, 1),
        ("[", ord("["), 0, 1),
        ("<", ord("<"), 0, 1),
        ("0", ord("0"), 0, 1),
        (";", ord(";"), 0, 1),
        ("7", ord("7"), 0, 1),
        (";", ord(";"), 0, 1),
        ("3", ord("3"), 0, 1),
        ("M", ord("M"), 0, 1),
    ]
    process_events(events, output.append, state, on_mouse_event=mouse.append)
    assert output == []
    assert len(mouse) == 1
    assert mouse[0].x == 6 and mouse[0].y == 2
    assert mouse[0].buttons == 0x0001


# ══════════════════════════════════════════════
#  Keymap VK tests
# ══════════════════════════════════════════════

def test_special_vk_has_arrows():
    assert 0x26 in SPECIAL_VK  # UP
    assert 0x28 in SPECIAL_VK  # DOWN
    assert 0x27 in SPECIAL_VK  # RIGHT
    assert 0x25 in SPECIAL_VK  # LEFT


def test_special_vk_values_are_ansi():
    assert SPECIAL_VK[0x26] == "\x1b[A"
    assert SPECIAL_VK[0x25] == "\x1b[D"


def test_modifier_vks_complete():
    assert 0x10 in MODIFIER_VKS  # Shift
    assert 0x11 in MODIFIER_VKS  # Ctrl
    assert 0x12 in MODIFIER_VKS  # Alt


def test_vk_processkey_value():
    assert VK_PROCESSKEY == 0xE5


# ══════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Tier 1: Handler Unit Tests")
    print("=" * 60)

    print("\n── DA filter ──")
    run_test("da_filter_korean_passthrough", test_da_filter_korean_passthrough)
    run_test("da_filter_esc_starts_accumulation", test_da_filter_esc_starts_accumulation)
    run_test("da_filter_csi_accumulation", test_da_filter_csi_accumulation)
    run_test("da_filter_complete_response", test_da_filter_complete_response)
    run_test("da_filter_overflow", test_da_filter_overflow)
    run_test("da_filter_korean_after_da_completion", test_da_filter_korean_after_da_completion)
    run_test("da_filter_korean_after_da_BUG_simulation", test_da_filter_korean_after_da_BUG_simulation)

    print("\n── Paste detection ──")
    run_test("paste_text_with_newline", test_paste_text_with_newline)
    run_test("paste_single_char_not_paste", test_paste_single_char_not_paste)
    run_test("paste_text_only_no_newline", test_paste_text_only_no_newline)
    run_test("paste_newline_only", test_paste_newline_only)
    run_test("paste_with_special_keys_not_paste", test_paste_with_special_keys_not_paste)
    run_test("paste_ignores_modifier_keys", test_paste_ignores_modifier_keys)
    run_test("paste_ignores_vk_processkey", test_paste_ignores_vk_processkey)
    run_test("paste_ime_confirmed_as_text", test_paste_ime_confirmed_as_text)

    print("\n── Key translation ──")
    run_test("handle_char_enter", test_handle_char_enter)
    run_test("handle_char_shift_enter", test_handle_char_shift_enter)
    run_test("handle_char_backspace_to_del", test_handle_char_backspace_to_del)
    run_test("handle_char_tab", test_handle_char_tab)
    run_test("handle_char_escape", test_handle_char_escape)
    run_test("handle_char_printable", test_handle_char_printable)
    run_test("handle_char_control", test_handle_char_control)
    run_test("process_events_sgr_mouse_wheel_up", test_process_events_sgr_mouse_wheel_up)
    run_test("process_events_sgr_mouse_left_click", test_process_events_sgr_mouse_left_click)

    print("\n── Keymap VK ──")
    run_test("special_vk_has_arrows", test_special_vk_has_arrows)
    run_test("special_vk_values_are_ansi", test_special_vk_values_are_ansi)
    run_test("modifier_vks_complete", test_modifier_vks_complete)
    run_test("vk_processkey_value", test_vk_processkey_value)

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
