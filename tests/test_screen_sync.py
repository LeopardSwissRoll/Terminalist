"""Screen sync tests — extract_grid / extract_cursor specific behavior.

Content extraction correctness (ASCII, color, bold, CJK) is covered
by test_roundtrip.py. These tests focus on screen_sync-specific logic
that roundtrip can't catch: cursor tracking, multiline, edge cases.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from terminalist.frontend.screen_sync import extract_grid, extract_cursor, EMPTY_CHAR

from conftest import make_screen as _make_screen

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


def test_empty_screen():
    s, st, lock = _make_screen()
    grid = extract_grid(s, lock)
    assert len(grid) == 5
    assert len(grid[0]) == 20
    assert grid[0][0].data == " "


def test_cursor_position():
    s, st, lock = _make_screen()
    st.feed("abc")
    x, y = extract_cursor(s)
    assert x == 3 and y == 0, f"cursor=({x},{y})"


def test_cursor_after_newline():
    s, st, lock = _make_screen()
    st.feed("abc\r\ndef")
    x, y = extract_cursor(s)
    assert x == 3 and y == 1


def test_multiline():
    s, st, lock = _make_screen(10, 3)
    st.feed("AAA\r\nBBB\r\nCCC")
    grid = extract_grid(s, lock)
    assert grid[0][0].data == "A"
    assert grid[1][0].data == "B"
    assert grid[2][0].data == "C"


def test_24bit_color():
    s, st, lock = _make_screen()
    st.feed("\x1b[38;2;255;128;0mcolor\x1b[0m")
    grid = extract_grid(s, lock)
    fg = grid[0][0].fg
    assert fg != "default", f"Expected non-default fg, got {fg!r}"


def test_empty_char_sentinel():
    assert EMPTY_CHAR.data == " "
    assert EMPTY_CHAR.fg == "default"
    assert EMPTY_CHAR.bg == "default"


def main():
    print("=" * 60)
    print("Screen Sync Tests")
    print("=" * 60)

    run_test("empty_screen", test_empty_screen)
    run_test("cursor_position", test_cursor_position)
    run_test("cursor_after_newline", test_cursor_after_newline)
    run_test("multiline", test_multiline)
    run_test("24bit_color", test_24bit_color)
    run_test("empty_char_sentinel", test_empty_char_sentinel)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed, {len(results)} total")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
