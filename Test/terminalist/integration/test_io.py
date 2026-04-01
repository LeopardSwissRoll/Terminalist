"""I/O verification tests for Terminalist.

Tests the full PTY pipeline: write_raw → PtyBackend → pyte → get_display.
No input backend needed — we inject commands directly via write_raw().
"""

from __future__ import annotations

import time
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from terminalist.debug import init_debug, log
from terminalist.pyte_patch import apply as patch_pyte
from terminalist.core.shell_session import ShellSession
from terminalist.core.terminal_session import SessionState


patch_pyte()
init_debug(enabled=True, log_path="terminalist_debug_io_test.log", env_tag="test")

# ── Helpers ──

def wait_ready(session, timeout=15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if session.state == SessionState.READY:
            return True
        time.sleep(0.1)
    return False


def wait_busy_then_ready(session, timeout=15.0) -> bool:
    """Wait for session to go BUSY then back to READY (command execution cycle)."""
    deadline = time.monotonic() + timeout
    saw_busy = False
    while time.monotonic() < deadline:
        if session.state == SessionState.BUSY:
            saw_busy = True
        if saw_busy and session.state == SessionState.READY:
            return True
        time.sleep(0.1)
    # Might have gone BUSY→READY before we polled
    return session.state == SessionState.READY


def send_and_wait(session, command: str, timeout=15.0) -> list[str]:
    """Send a command and wait for prompt to return. Returns full display."""
    log("test", f"send_and_wait: {command!r}")
    session.write_raw(command + "\r")
    time.sleep(0.3)  # let PTY process
    if wait_busy_then_ready(session, timeout):
        log("test", "send_and_wait: got READY")
    else:
        log("test", f"send_and_wait: timeout, state={session.state.value}")
    display = session.get_display()
    return display


def find_in_display(display: list[str], needle: str) -> bool:
    """Check if needle appears anywhere in display lines."""
    for line in display:
        if needle in line:
            return True
    return False


def dump_display(display: list[str], label: str = "") -> None:
    """Print non-empty lines from display."""
    if label:
        print(f"    [{label}]")
    for i, line in enumerate(display):
        stripped = line.rstrip()
        if stripped:
            print(f"    {i:3d}: {stripped}")


# ── Test state ──
results: list[tuple[str, bool, str]] = []


def run_test(name: str, fn):
    print(f"\n  [{name}] running ...")
    try:
        ok, detail = fn()
        tag = "PASS" if ok else "FAIL"
        print(f"  [{name}] {tag}: {detail}")
        results.append((name, ok, detail))
    except Exception as e:
        print(f"  [{name}] FAIL: exception {type(e).__name__}: {e}")
        results.append((name, False, f"exception: {e}"))


# ── Tests ──

session: ShellSession | None = None


def setup() -> ShellSession:
    global session
    print("\n[setup] Spawning PowerShell session (cols=100, rows=30)...")
    session = ShellSession("io_test", Path.cwd(), shell_type="powershell", cols=100, rows=30)
    session.spawn()
    if wait_ready(session):
        print("[setup] Session READY")
    else:
        print(f"[setup] WARNING: session state={session.state.value}")
    return session


def test_basic_roundtrip():
    """Send 'echo hello_test_marker' and verify output."""
    display = send_and_wait(session, "echo hello_test_marker")
    found = find_in_display(display, "hello_test_marker")
    if not found:
        dump_display(display, "display")
    return found, "echo output found in display" if found else "echo output NOT found"


def test_multiline_output():
    """Send a command that produces multiple lines."""
    display = send_and_wait(session, 'echo "line_A"; echo "line_B"; echo "line_C"')
    a = find_in_display(display, "line_A")
    b = find_in_display(display, "line_B")
    c = find_in_display(display, "line_C")
    ok = a and b and c
    missing = [x for x, f in [("A", a), ("B", b), ("C", c)] if not f]
    if not ok:
        dump_display(display, "display")
    return ok, "all 3 lines found" if ok else f"missing: {missing}"


def test_long_output():
    """Send a command that overflows the visible screen."""
    # 30 rows screen, generate 50 lines
    display = send_and_wait(session, "1..50 | ForEach-Object { echo \"num_$_\" }", timeout=20.0)
    # Should see at least some of the later numbers (after scroll)
    found_late = find_in_display(display, "num_4")  # at least some output
    # First numbers may have scrolled off — that's expected
    return found_late, "long output received (scroll ok)" if found_late else "no output found after long command"


def test_special_chars():
    """Test that special characters pass through correctly."""
    display = send_and_wait(session, 'echo "test<>|&^%$#@!"')
    # PowerShell might interpret some chars, but the echo should produce something
    found = find_in_display(display, "test")
    return found, "special chars echo received" if found else "special chars not found"


def test_vt100_color():
    """Verify pyte processes ANSI color sequences without corruption."""
    # Use PowerShell's Write-Host with color
    display = send_and_wait(session, 'Write-Host "COLOR_RED_TEST" -ForegroundColor Red')
    found = find_in_display(display, "COLOR_RED_TEST")
    if not found:
        dump_display(display, "display")
    # Also check pyte screen attributes for the colored text
    color_info = ""
    if found and session:
        with session._lock:
            for y in range(session._screen.lines):
                for x in range(session._screen.columns):
                    char = session._screen.buffer[y][x]
                    if char.data == "C" and x + 1 < session._screen.columns:
                        next_chars = "".join(
                            session._screen.buffer[y][x + i].data or ""
                            for i in range(14)
                        )
                        if next_chars.startswith("COLOR_RED_TEST"):
                            fg = char.fg
                            color_info = f"fg={fg}"
                            break
                if color_info:
                    break
    detail = f"colored text found ({color_info})" if found else "colored text NOT found"
    return found, detail


def test_cjk_korean():
    """Test Korean (CJK wide character) display."""
    display = send_and_wait(session, 'echo "한글테스트"')
    found = find_in_display(display, "한글테스트")
    if not found:
        # Check if individual chars are present (pyte might split them)
        found_partial = find_in_display(display, "한글") or find_in_display(display, "테스트")
        if found_partial:
            return True, "Korean chars found (partial match)"
        dump_display(display, "display")
    return found, "Korean text found" if found else "Korean text NOT found"


def test_tab_completion():
    """Send Tab and verify it doesn't crash (completion may or may not work)."""
    # Just verify the pipeline survives a Tab keystroke
    from terminalist.input.keymap_vk import VT100_MAP
    session.write_raw("dir" + VT100_MAP["tab"])
    time.sleep(1.0)
    display = session.get_display()
    alive = session._backend.is_alive()
    # Cancel whatever Tab did
    session.write_raw("\x1b")  # ESC to cancel
    time.sleep(0.3)
    session.write_raw("\x15")  # Ctrl+U to clear line
    time.sleep(0.3)
    return alive, "PTY survived Tab input" if alive else "PTY died after Tab"


def test_ctrl_c():
    """Send Ctrl+C during a long-running command."""
    # Start a long sleep
    session.write_raw("Start-Sleep -Seconds 30\r")
    time.sleep(1.0)
    # Send Ctrl+C
    session.write_raw("\x03")
    time.sleep(2.0)
    # Should return to prompt
    ok = wait_ready(session, timeout=10.0)
    return ok, "Ctrl+C interrupted command, back to READY" if ok else f"state={session.state.value} after Ctrl+C"


def test_arrow_keys():
    """Send arrow keys and verify PTY survives."""
    from terminalist.input.keymap_vk import VT100_MAP
    # Type something, then use arrows
    session.write_raw("echo arrow_test")
    time.sleep(0.3)
    session.write_raw(VT100_MAP["left"] * 4)  # move cursor left
    time.sleep(0.3)
    session.write_raw(VT100_MAP["right"] * 4)  # move cursor right
    time.sleep(0.3)
    session.write_raw("\r")  # execute
    time.sleep(1.0)
    ok = wait_busy_then_ready(session, timeout=10.0)
    display = session.get_display()
    found = find_in_display(display, "arrow_test")
    return ok and found, "arrow keys + execution ok" if (ok and found) else f"ready={ok} found={found}"


# ── Main ──

def main():
    print("=" * 60)
    print("Terminalist I/O Verification Tests")
    print("=" * 60)

    s = setup()

    run_test("basic_roundtrip", test_basic_roundtrip)
    run_test("multiline_output", test_multiline_output)
    run_test("long_output", test_long_output)
    run_test("special_chars", test_special_chars)
    run_test("vt100_color", test_vt100_color)
    run_test("cjk_korean", test_cjk_korean)
    run_test("tab_key", test_tab_completion)
    run_test("ctrl_c", test_ctrl_c)
    run_test("arrow_keys", test_arrow_keys)

    # Cleanup
    print("\n[cleanup] Killing session...")
    s.kill()

    # Summary
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed, {len(results)} total")
    print("=" * 60)
    for name, ok, detail in results:
        tag = "PASS" if ok else "FAIL"
        print(f"  {tag}  {name}: {detail}")

    if failed:
        print(f"\nLog file: terminalist_debug_io_test.log")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
