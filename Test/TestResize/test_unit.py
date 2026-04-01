"""PreservingScreen resize — core verification tests.

Verifies:
1. Shrink preserves cursor-adjacent content (no stale rows)
2. Shrink + expand round-trip recovers all lines
3. Various cursor positions (top, middle, bottom)
4. Sparse screen (partially filled)
5. Real PTY with PSReadLine profile (the original bug scenario)

Run: python Test/TestResize/test_unit.py
"""

from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pyte
import terminalist.pyte_patch as pyte_patch
pyte_patch.apply()

from terminalist.pyte_patch import PreservingScreen

results: list[tuple[str, bool, str]] = []


def feed(screen, data):
    pyte.Stream(screen).feed(data)


def get_lines(screen) -> list[str]:
    lines = []
    for y in range(screen.lines):
        row = screen.buffer.get(y, {})
        chars = []
        for x in range(screen.columns):
            try:
                ch = row[x].data
            except (KeyError, IndexError):
                ch = " "
            chars.append(ch if ch else " ")
        lines.append("".join(chars).rstrip())
    return lines


def non_empty(lines: list[str]) -> int:
    return sum(1 for l in lines if l.strip())


def run_test(name, fn):
    try:
        fn()
        print(f"  PASS  {name}")
        results.append((name, True, ""))
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        results.append((name, False, str(e)))
    except Exception as e:
        print(f"  ERROR {name}: {type(e).__name__}: {e}")
        results.append((name, False, str(e)))


# ═══════════════════════════════════════
#  Pure pyte tests (no PTY)
# ═══════════════════════════════════════

def test_shrink_cursor_bottom():
    """Cursor at bottom: keep bottom rows, save top to history."""
    s = PreservingScreen(20, 10, history=100)
    for i in range(8):
        feed(s, f"Line {i:02d}\r\n")
    feed(s, "Line 08")
    assert s.cursor.y == 8

    s.resize(5, 20)

    lines = get_lines(s)
    assert s.cursor.y == 4, f"cursor.y={s.cursor.y}, expected 4"
    assert "Line 08" in lines[4], f"cursor row should have Line 08, got {lines[4]!r}"
    assert "Line 04" in lines[0], f"first visible should be Line 04, got {lines[0]!r}"
    assert len(s.history.top) == 4  # Lines 00-03 saved
    # No stale data
    assert "Line 03" not in lines[4], f"stale data at last row"


def test_shrink_cursor_top():
    """Cursor at top: keep top rows (cursor area)."""
    s = PreservingScreen(20, 10, history=100)
    for i in range(8):
        feed(s, f"Line {i:02d}\r\n")
    feed(s, "Line 08")
    feed(s, "\x1b[H")  # cursor home
    assert s.cursor.y == 0

    s.resize(5, 20)

    lines = get_lines(s)
    assert s.cursor.y == 0
    assert "Line 00" in lines[0], f"expected Line 00, got {lines[0]!r}"
    assert "Line 04" in lines[4], f"expected Line 04, got {lines[4]!r}"
    assert len(s.history.top) == 0  # nothing above cursor window


def test_shrink_cursor_middle():
    """Cursor in middle: window includes cursor row."""
    s = PreservingScreen(20, 10, history=100)
    for i in range(8):
        feed(s, f"Line {i:02d}\r\n")
    feed(s, "Line 08")
    feed(s, "\x1b[5;1H")  # cursor to row 4 (1-indexed=5)
    assert s.cursor.y == 4

    s.resize(5, 20)

    lines = get_lines(s)
    assert s.cursor.y == 4, f"cursor.y={s.cursor.y}"
    assert "Line 04" in lines[4], f"cursor row should have Line 04"


def test_shrink_sparse_screen():
    """Partially filled screen: no content loss for visible lines."""
    s = PreservingScreen(20, 10, history=100)
    feed(s, "Line 00\r\nLine 01\r\nLine 02")
    assert s.cursor.y == 2

    s.resize(5, 20)

    lines = get_lines(s)
    assert s.cursor.y == 2
    assert "Line 00" in lines[0]
    assert "Line 01" in lines[1]
    assert "Line 02" in lines[2]


def test_shrink_expand_roundtrip():
    """Shrink then expand recovers content from history."""
    s = PreservingScreen(20, 10, history=100)
    for i in range(8):
        feed(s, f"Line {i:02d}\r\n")
    feed(s, "Line 08")

    s.resize(5, 20)
    assert len(s.history.top) == 4  # Lines 00-03

    s.resize(10, 20)

    lines = get_lines(s)
    # All original lines should be recoverable
    for i in range(4):
        assert any(f"Line {i:02d}" in l for l in lines), f"Line {i:02d} not recovered"


def test_no_stale_rows():
    """After shrink, no row should contain stale data from pre-shrink buffer."""
    s = PreservingScreen(20, 10, history=100)
    for i in range(8):
        feed(s, f"Line {i:02d}\r\n")
    feed(s, "Line 08")
    # cursor at y=8

    s.resize(5, 20)

    lines = get_lines(s)
    # Lines 00-03 should NOT appear in the visible area (they're in history)
    for y in range(5):
        for i in range(4):
            assert f"Line {i:02d}" not in lines[y], \
                f"Stale Line {i:02d} at row {y}: {lines[y]!r}"


def test_columns_only_change():
    """Changing only columns should not affect rows."""
    s = PreservingScreen(20, 10, history=100)
    feed(s, "Hello World")

    s.resize(10, 15)  # same lines, fewer columns

    assert s.lines == 10
    assert s.columns == 15
    lines = get_lines(s)
    assert "Hello World" in lines[0]


def test_buffer_with_all_keys():
    """Simulate the ConPTY scenario: all rows have buffer entries."""
    s = PreservingScreen(40, 20, history=100)
    # Write content to top rows
    for i in range(8):
        feed(s, f"Content {i:02d}\r\n")
    feed(s, "PS prompt> ")

    # Manually create buffer entries for ALL rows (simulating ConPTY)
    for y in range(20):
        _ = s.buffer[y]  # defaultdict creates entry

    assert len(s.buffer) == 20, "All 20 rows should be in buffer"

    s.resize(10, 40)

    lines = get_lines(s)
    ne = non_empty(lines)
    assert ne > 0, f"All content lost! (ConPTY buffer entry bug)"
    assert any("PS prompt" in l for l in lines), "Prompt should be visible"


# ═══════════════════════════════════════
#  Real PTY test (PSReadLine — the original bug)
# ═══════════════════════════════════════

def test_real_pty_psreadline():
    """Real PTY with PSReadLine profile — the scenario that triggered the bug."""
    from terminalist.core.terminal_session import TerminalSession

    session = TerminalSession(
        session_id="test-psrl",
        cmd=["powershell.exe"],  # WITH profile = PSReadLine
        workspace=Path.cwd(),
        cols=60, rows=20,
    )
    session.spawn()
    time.sleep(4.0)

    session.write_raw("echo 'resize test'\r")
    time.sleep(1.0)

    grid_before, _, _, _, rows_before = session.get_screen_snapshot()
    ne_before = sum(1 for y in range(rows_before)
                    if any(grid_before[y][x].data.strip() for x in range(60)))

    session.resize(cols=60, rows=10)
    time.sleep(1.0)

    grid_after, cx, cy, _, rows_after = session.get_screen_snapshot()
    ne_after = sum(1 for y in range(rows_after)
                   if any(grid_after[y][x].data.strip() for x in range(60)))

    session.kill()

    assert ne_before > 0, "Precondition: should have content before resize"
    assert ne_after > 0, (
        f"Content disappeared after resize! "
        f"{ne_before} rows before, {ne_after} after. "
        f"This is the original PSReadLine h-split bug."
    )


def test_real_pty_noprofile():
    """Real PTY without profile — baseline comparison."""
    from terminalist.core.terminal_session import TerminalSession

    session = TerminalSession(
        session_id="test-noprof",
        cmd=["powershell.exe", "-NoProfile", "-NoLogo"],
        workspace=Path.cwd(),
        cols=60, rows=20,
    )
    session.spawn()
    time.sleep(2.0)

    for i in range(6):
        session.write_raw(f"echo 'line {i}'\r")
        time.sleep(0.3)
    time.sleep(1.0)

    grid, _, _, _, rows = session.get_screen_snapshot()
    ne_before = sum(1 for y in range(rows)
                    if any(grid[y][x].data.strip() for x in range(60)))

    session.resize(cols=60, rows=10)
    time.sleep(0.5)

    grid2, _, _, _, rows2 = session.get_screen_snapshot()
    ne_after = sum(1 for y in range(rows2)
                   if any(grid2[y][x].data.strip() for x in range(60)))

    session.kill()

    assert ne_before > 0, "Precondition"
    assert ne_after > 0, f"Content lost: {ne_before} → {ne_after}"


# ═══════════════════════════════════════
#  Runner
# ═══════════════════════════════════════

def main():
    print("=" * 60)
    print("  PreservingScreen Resize Tests")
    print("=" * 60)

    # Pure pyte (fast)
    run_test("shrink_cursor_bottom", test_shrink_cursor_bottom)
    run_test("shrink_cursor_top", test_shrink_cursor_top)
    run_test("shrink_cursor_middle", test_shrink_cursor_middle)
    run_test("shrink_sparse_screen", test_shrink_sparse_screen)
    run_test("shrink_expand_roundtrip", test_shrink_expand_roundtrip)
    run_test("no_stale_rows", test_no_stale_rows)
    run_test("columns_only_change", test_columns_only_change)
    run_test("buffer_with_all_keys", test_buffer_with_all_keys)

    # Real PTY (slow)
    if "--no-pty" not in sys.argv:
        run_test("real_pty_psreadline", test_real_pty_psreadline)
        run_test("real_pty_noprofile", test_real_pty_noprofile)
    else:
        print("  SKIP  real_pty_psreadline (--no-pty)")
        print("  SKIP  real_pty_noprofile (--no-pty)")

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed, {len(results)} total")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
