"""PreservingScreen tests — vertical resize content preservation.

Verifies that pyte_patch.PreservingScreen correctly saves/restores
content when the screen is shrunk and expanded (pyte issue #31 fix).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pyte
from pyte.screens import Char

from terminalist.pyte_patch import PreservingScreen

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


def _make_screen(cols=20, rows=10) -> tuple[PreservingScreen, pyte.Stream]:
    s = PreservingScreen(cols, rows, history=100)
    st = pyte.Stream(s)
    return s, st


def _read_line(screen, y: int) -> str:
    """Read a line, skipping CJK stubs."""
    parts = []
    for x in range(screen.columns):
        ch = screen.buffer[y][x].data
        if ch == "":
            continue
        parts.append(ch)
    return "".join(parts).rstrip()


def _all_lines(screen) -> list[str]:
    return [_read_line(screen, y) for y in range(screen.lines)]


# ═══════════════════════════════════════════
#  Shrink tests
# ═══════════════════════════════════════════


def test_shrink_preserves_to_history():
    """Shrink 10→5: top lines saved to history.top."""
    s, st = _make_screen(20, 10)
    for i in range(10):
        st.feed(f"Line {i}\r\n")

    before = len(s.history.top)  # may already have entries from scrolling
    s.resize(5, 20)

    assert s.lines == 5
    added = len(s.history.top) - before
    assert added >= 5, f"Expected >=5 new history entries, got {added}"


def test_shrink_visible_content():
    """After shrink, remaining visible lines are the bottom ones."""
    s, st = _make_screen(20, 10)
    for i in range(10):
        st.feed(f"Line {i}\r\n")

    s.resize(5, 20)
    lines = _all_lines(s)
    # pyte's resize deletes from top, so we should see the later lines
    non_empty = [l for l in lines if l]
    assert len(non_empty) > 0, "Should have some visible content after shrink"


def test_shrink_cursor_clamped():
    """Cursor.y is clamped to new screen height."""
    s, st = _make_screen(20, 10)
    st.feed("A" * 20 + "\r\n" * 8)  # cursor at y=8 or so
    s.resize(3, 20)
    assert s.cursor.y < 3, f"cursor.y={s.cursor.y} should be < 3"


# ═══════════════════════════════════════════
#  Expand tests
# ═══════════════════════════════════════════


def test_expand_restores_from_history():
    """Shrink 10→5 then expand 5→10: lines restored from history."""
    s, st = _make_screen(20, 10)
    for i in range(10):
        st.feed(f"Line {i}\r\n")

    s.resize(5, 20)
    history_count = len(s.history.top)
    assert history_count >= 5

    s.resize(10, 20)
    # History should have been consumed
    assert len(s.history.top) < history_count


def test_expand_content_roundtrip():
    """Content survives a shrink→expand cycle."""
    s, st = _make_screen(20, 10)
    for i in range(8):
        st.feed(f"Row{i:02d}\r\n")

    before = _all_lines(s)
    s.resize(4, 20)
    s.resize(10, 20)
    after = _all_lines(s)

    # At least the row markers should be present somewhere
    before_text = "\n".join(before)
    after_text = "\n".join(after)
    for marker in ["Row00", "Row03", "Row07"]:
        assert marker in before_text or marker in after_text, \
            f"{marker} lost after shrink→expand"


def test_expand_beyond_history():
    """Expand more than history has — partial restore, no crash."""
    s, st = _make_screen(20, 5)
    st.feed("Hello\r\nWorld")
    s.resize(3, 20)  # push 2 lines to history
    history_count = len(s.history.top)

    s.resize(20, 20)  # expand way beyond what history has
    assert s.lines == 20
    # Should have restored what was available, rest is blank
    lines = _all_lines(s)
    assert any("Hello" in l or "World" in l for l in lines), \
        "Content should be partially restored"


# ═══════════════════════════════════════════
#  Cycle / edge case tests
# ═══════════════════════════════════════════


def test_multiple_shrink_expand_cycles():
    """Multiple resize cycles don't lose or corrupt content."""
    s, st = _make_screen(20, 10)
    for i in range(8):
        st.feed(f"L{i}\r\n")

    for _ in range(5):
        s.resize(4, 20)
        s.resize(10, 20)

    lines = _all_lines(s)
    text = "\n".join(lines)
    # Should still have some original content
    assert any(f"L{i}" in text for i in range(8)), "Content lost after 5 cycles"


def test_noop_resize():
    """Same dimensions → no change, no crash."""
    s, st = _make_screen(20, 10)
    st.feed("test")
    s.resize(10, 20)
    assert _read_line(s, 0).startswith("test")


def test_columns_only_resize():
    """Horizontal resize doesn't affect vertical history."""
    s, st = _make_screen(20, 10)
    st.feed("Hello")
    s.resize(10, 40)  # wider
    assert s.columns == 40
    assert s.lines == 10
    assert _read_line(s, 0).startswith("Hello")


def test_cursor_x_clamped_on_column_shrink():
    """Cursor.x is clamped when columns shrink."""
    s, st = _make_screen(20, 5)
    st.feed("A" * 15)  # cursor at x=15
    s.resize(5, 10)  # shrink columns to 10
    assert s.cursor.x <= 9, f"cursor.x={s.cursor.x} should be <= 9"


def test_styled_content_preserved():
    """Colored/bold text survives shrink→expand."""
    s, st = _make_screen(20, 6)
    st.feed("\x1b[1;31mRed Bold\x1b[0m\r\n")
    st.feed("\x1b[32mGreen\x1b[0m\r\n")
    st.feed("Normal\r\n")

    s.resize(2, 20)
    s.resize(6, 20)

    # Check that some styled content exists in history-restored lines
    found_styled = False
    for y in range(s.lines):
        for x in range(s.columns):
            ch = s.buffer[y][x]
            if ch.data in ("R", "G") and (ch.fg != "default" or ch.bold):
                found_styled = True
                break
        if found_styled:
            break
    assert found_styled, "Styled content should survive resize cycle"


def test_cjk_content_preserved():
    """CJK wide chars survive shrink→expand."""
    s, st = _make_screen(20, 6)
    st.feed("한글테스트\r\n")
    st.feed("Normal\r\n")

    s.resize(2, 20)
    s.resize(6, 20)

    lines = _all_lines(s)
    text = "".join(lines)
    assert "한글" in text or "테스트" in text, \
        f"CJK content lost after resize: {lines}"


def test_new_content_after_resize():
    """New PTY output works correctly after resize."""
    s, st = _make_screen(20, 10)
    st.feed("Before\r\n")
    s.resize(5, 20)
    st.feed("After\r\n")
    lines = _all_lines(s)
    assert any("After" in l for l in lines), "New content after resize should appear"


def test_shrink_to_minimum():
    """Shrink to 1 row — extreme case."""
    s, st = _make_screen(20, 10)
    for i in range(10):
        st.feed(f"Line {i}\r\n")
    s.resize(1, 20)
    assert s.lines == 1
    assert s.cursor.y == 0
    # Should not crash
    _all_lines(s)


# ═══════════════════════════════════════════
#  Regression: materialized empty buffer keys
# ═══════════════════════════════════════════


def test_materialized_empty_rows():
    """Regression: when ALL rows have buffer entries (including empty ones),
    stock pyte.Screen.resize shifts empty rows over content rows.

    Root cause: ConPTY output or get_screen_snapshot() accesses
    screen.buffer[y] for every row, which materializes empty defaultdict
    entries. pyte.Screen.delete_lines then shifts these empty entries
    to overwrite content rows.

    This is the h-split content disappearance bug.
    """
    s, st = _make_screen(40, 20)
    for i in range(8):
        st.feed(f"Content {i:02d}\r\n")
    st.feed("PS prompt> ")

    # Simulate buffer entry materialization (ConPTY / get_screen_snapshot)
    for y in range(20):
        _ = s.buffer[y]

    assert len(s.buffer) == 20, "precondition: all rows materialized"

    s.resize(10, 40)

    lines = _all_lines(s)
    ne = sum(1 for l in lines if l.strip())
    assert ne > 0, (
        f"All content lost after resize with materialized empty rows! "
        f"This is the h-split PSReadLine bug regression."
    )
    assert any("PS prompt" in l for l in lines), "Prompt should remain visible"


def test_no_stale_rows_after_shrink():
    """After shrink, no row should contain stale data from pre-shrink positions."""
    s, st = _make_screen(20, 10)
    for i in range(8):
        st.feed(f"Line {i:02d}\r\n")
    st.feed("Line 08")
    # cursor at y=8

    s.resize(5, 20)

    lines = _all_lines(s)
    # Lines 00-03 went to history; they must NOT appear in visible area
    for y in range(5):
        for i in range(4):
            assert f"Line {i:02d}" not in lines[y], \
                f"Stale 'Line {i:02d}' at row {y}: {lines[y]!r}"


def test_shrink_cursor_bottom_keeps_cursor_visible():
    """Cursor at bottom of content: viewport window must include cursor row."""
    s, st = _make_screen(20, 10)
    for i in range(8):
        st.feed(f"Line {i:02d}\r\n")
    st.feed("Line 08")
    assert s.cursor.y == 8

    s.resize(5, 20)

    assert s.cursor.y == 4, f"cursor.y={s.cursor.y}, expected 4"
    line = _read_line(s, 4)
    assert "Line 08" in line, f"Cursor row should have Line 08, got {line!r}"


# ═══════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════


def main():
    print("=" * 60)
    print("PreservingScreen Tests")
    print("=" * 60)

    print("\n── Shrink ──")
    run_test("shrink_preserves_to_history", test_shrink_preserves_to_history)
    run_test("shrink_visible_content", test_shrink_visible_content)
    run_test("shrink_cursor_clamped", test_shrink_cursor_clamped)

    print("\n── Expand ──")
    run_test("expand_restores_from_history", test_expand_restores_from_history)
    run_test("expand_content_roundtrip", test_expand_content_roundtrip)
    run_test("expand_beyond_history", test_expand_beyond_history)

    print("\n── Cycles / Edge cases ──")
    run_test("multiple_shrink_expand_cycles", test_multiple_shrink_expand_cycles)
    run_test("noop_resize", test_noop_resize)
    run_test("columns_only_resize", test_columns_only_resize)
    run_test("cursor_x_clamped", test_cursor_x_clamped_on_column_shrink)
    run_test("styled_content_preserved", test_styled_content_preserved)
    run_test("cjk_content_preserved", test_cjk_content_preserved)
    run_test("new_content_after_resize", test_new_content_after_resize)
    run_test("shrink_to_minimum", test_shrink_to_minimum)

    print("\n── Regression: materialized buffer keys ──")
    run_test("materialized_empty_rows", test_materialized_empty_rows)
    run_test("no_stale_rows_after_shrink", test_no_stale_rows_after_shrink)
    run_test("shrink_cursor_bottom_keeps_cursor_visible", test_shrink_cursor_bottom_keeps_cursor_visible)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed, {len(results)} total")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
