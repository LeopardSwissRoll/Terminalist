"""Investigation trail — how the resize bug was found.

This file documents the debugging process. Not for CI — for humans
who want to understand WHY the fix works.

Run: python TestResize/test_investigation.py

Discovery order:
1. Pure pyte resize → stale row found (delete_lines gap)
2. Real PTY capture → ConPTY sends 0 bytes after resize
3. PSReadLine profile → 100% content loss reproduced
4. Buffer key inspection → all 20 rows in buffer (ConPTY creates entries)
5. Traced delete_lines → shifts empty rows over content
6. Fix: bypass pyte.Screen.resize, build buffer directly
"""

from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pyte
import terminalist.pyte_patch as pyte_patch
pyte_patch.apply()

from terminalist.pyte_patch import PreservingScreen


def feed(screen, data):
    pyte.Stream(screen).feed(data)


def dump(screen, label):
    print(f"\n  [{label}] ({screen.columns}x{screen.lines}, cursor=({screen.cursor.x},{screen.cursor.y}))")
    for y in range(screen.lines):
        row = screen.buffer.get(y, {})
        chars = []
        for x in range(screen.columns):
            try:
                ch = row[x].data
            except (KeyError, IndexError):
                ch = " "
            chars.append(ch if ch else " ")
        line = "".join(chars).rstrip()
        marker = " <cursor" if y == screen.cursor.y else ""
        if line.strip() or y == screen.cursor.y:
            print(f"    {y:03d} |{line}|{marker}")


# ═══════════════════════════════════════
#  Step 1: The delete_lines bug (pyte internals)
# ═══════════════════════════════════════

def step1_delete_lines_bug():
    """Show that pyte.Screen.delete_lines has a gap when source row
    is in-range but missing from buffer (no-op instead of clearing target)."""
    print("\n" + "=" * 60)
    print("  Step 1: pyte.Screen.delete_lines gap")
    print("=" * 60)

    s = pyte.Screen(20, 10)
    for i in range(8):
        feed(s, f"Line {i:02d}\r\n")
    feed(s, "Line 08")

    print(f"\n  Key 9 in buffer: {9 in s.buffer}")
    dump(s, "Before resize")

    s.resize(5, 20)
    dump(s, "After stock pyte resize")

    row4 = s.buffer.get(4, {})
    chars = "".join(row4[x].data for x in sorted(row4.keys())[:10]) if row4 else ""
    print(f"\n  Row 4 content: {chars!r}")
    if "Line 04" in chars:
        print("  ^ STALE DATA — pyte bug confirmed")


# ═══════════════════════════════════════
#  Step 2: ConPTY creates buffer entries for all rows
# ═══════════════════════════════════════

def step2_conpty_buffer_entries():
    """Demonstrate: when PTY output touches all rows, buffer has all keys.
    This turns the delete_lines gap into total content loss."""
    print("\n" + "=" * 60)
    print("  Step 2: ConPTY buffer entries → total content loss")
    print("=" * 60)

    # Simulate: content in top 10, empty buffer entries for all 20
    s = pyte.Screen(40, 20)
    for i in range(8):
        feed(s, f"Content {i:02d}\r\n")
    feed(s, "PS prompt> ")

    # ConPTY creates entries for all rows
    for y in range(20):
        _ = s.buffer[y]

    print(f"\n  Buffer keys: {len(s.buffer)} (all 20 present)")
    print(f"  Content in rows 0-9, empty in 10-19")

    dump(s, "Before resize")

    s.resize(10, 40)
    dump(s, "After stock pyte resize")

    ne = sum(1 for y in range(10)
             if any(x in s.buffer.get(y, {}) and s.buffer[y][x].data.strip()
                    for x in range(40)))
    print(f"\n  Non-empty rows after resize: {ne}")
    if ne == 0:
        print("  ^ ALL CONTENT LOST — this is the bug")


# ═══════════════════════════════════════
#  Step 3: Fixed PreservingScreen works
# ═══════════════════════════════════════

def step3_fix_works():
    """Same scenario with fixed PreservingScreen — content preserved."""
    print("\n" + "=" * 60)
    print("  Step 3: Fixed PreservingScreen preserves content")
    print("=" * 60)

    s = PreservingScreen(40, 20, history=100)
    for i in range(8):
        feed(s, f"Content {i:02d}\r\n")
    feed(s, "PS prompt> ")

    # Simulate ConPTY entries
    for y in range(20):
        _ = s.buffer[y]

    dump(s, "Before resize (all buffer keys present)")

    s.resize(10, 40)
    dump(s, "After fixed resize")

    ne = sum(1 for y in range(10)
             if any(x in s.buffer.get(y, {}) and s.buffer[y][x].data.strip()
                    for x in range(40)))
    print(f"\n  Non-empty rows: {ne}")
    print(f"  History: {len(s.history.top)} lines")
    if ne > 0:
        print("  ^ FIX WORKS")


# ═══════════════════════════════════════
#  Step 4: Real PTY reproduction (slow)
# ═══════════════════════════════════════

def step4_real_pty():
    """Reproduce with real PowerShell + PSReadLine."""
    print("\n" + "=" * 60)
    print("  Step 4: Real PTY reproduction (PowerShell + PSReadLine)")
    print("=" * 60)

    from terminalist.core.terminal_session import TerminalSession

    session = TerminalSession(
        session_id="investigation",
        cmd=["powershell.exe"],
        workspace=Path.cwd(),
        cols=60, rows=20,
    )
    session.spawn()
    time.sleep(4.0)

    session.write_raw("echo 'investigation'\r")
    time.sleep(1.0)

    grid, cx, cy, cols, rows = session.get_screen_snapshot()
    ne_before = sum(1 for y in range(rows)
                    if any(grid[y][x].data.strip() for x in range(cols)))
    buf_keys = len(session._screen.buffer)

    print(f"\n  Before resize: {ne_before} content rows, {buf_keys} buffer keys")

    session.resize(cols=60, rows=10)
    time.sleep(1.0)

    grid2, cx2, cy2, cols2, rows2 = session.get_screen_snapshot()
    ne_after = sum(1 for y in range(rows2)
                   if any(grid2[y][x].data.strip() for x in range(cols2)))

    print(f"  After resize:  {ne_after} content rows")
    if ne_after > 0:
        print(f"  FIX CONFIRMED with real PTY")
    else:
        print(f"  BUG STILL PRESENT!")

    session.kill()


def main():
    print("=" * 60)
    print("  Resize Bug Investigation Trail")
    print("=" * 60)

    step1_delete_lines_bug()
    step2_conpty_buffer_entries()
    step3_fix_works()

    if "--pty" in sys.argv:
        step4_real_pty()
    else:
        print("\n  Step 4: SKIPPED (run with --pty)")

    print("\n" + "=" * 60)
    print("  Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
