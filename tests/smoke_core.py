"""Smoke tests for Terminalist core modules.

Verifies: WinPtyBackend, TerminalSession, ShellSession, TES EventStreamManager, Pane+Rect.
Run from project root: python tests/smoke_core.py
"""

from __future__ import annotations

import gc
import sys
import time
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root on sys.path so `terminalist` package resolves
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from terminalist.core.pty_backend import PtyBackend
from terminalist.core.winpty_backend import WinPtyBackend
from terminalist.core.terminal_session import TerminalSession, SessionState
from terminalist.core.shell_session import ShellSession
from terminalist.core.pane import Pane, Rect
from terminalist.core.session_manager import SessionManager
from terminalist.events.tes import EventStreamManager
from terminalist.events.event import Channel, Event

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_results: list[tuple[str, bool, str]] = []

WORKSPACE = Path.cwd()


def run_test(name: str, fn):
    """Run *fn*, capture pass/fail, print immediately."""
    print(f"  [{name}] running ...", end=" ", flush=True)
    try:
        fn()
        _results.append((name, True, ""))
        print("PASS")
    except Exception as exc:
        tb = traceback.format_exc()
        _results.append((name, False, tb))
        print(f"FAIL\n    {exc}")


def summary():
    """Print final summary and exit with appropriate code."""
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    print(f"Results: {passed} passed, {failed} failed, {len(_results)} total")
    print("=" * 60)
    for name, ok, tb in _results:
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {name}")
        if not ok:
            for line in tb.strip().splitlines():
                print(f"        {line}")
    print()
    return 0 if failed == 0 else 1


# ===================================================================
# 1. WinPtyBackend
# ===================================================================
def test_winpty_backend_spawn_read_terminate():
    backend = WinPtyBackend()
    backend.spawn("powershell.exe -NoLogo -NoProfile", str(WORKSPACE), 24, 80)
    assert backend.is_alive(), "Backend should be alive after spawn"
    assert backend.pid is not None, "PID should be set"

    # Accumulate output for up to 5 seconds
    output = ""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            chunk = backend.read(4096)
            if chunk:
                output += chunk
        except EOFError:
            break
        time.sleep(0.1)
        # Stop early once we have some output
        if output.strip():
            break

    assert len(output) > 0, f"Expected some PTY output, got empty string"

    backend.terminate()
    # Give it a moment to die
    time.sleep(0.5)
    assert not backend.is_alive(), "Backend should be dead after terminate"


# ===================================================================
# 2. TerminalSession — get_display / get_display_tail
# ===================================================================
def test_terminal_session_display():
    sess = TerminalSession(
        session_id="test_ts",
        cmd=["powershell.exe", "-NoLogo", "-NoProfile"],
        workspace=WORKSPACE,
        cols=80,
        rows=24,
    )
    sess.spawn()
    assert sess.state == SessionState.STARTING, f"Expected STARTING, got {sess.state}"

    # Poll for non-empty display (PowerShell can take several seconds to start)
    non_empty = []
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        display = sess.get_display()
        non_empty = [l for l in display if l.strip()]
        if non_empty:
            break
        time.sleep(0.5)

    display = sess.get_display()
    assert isinstance(display, list), "get_display should return a list"
    assert len(display) == 24, f"Expected 24 lines, got {len(display)}"
    assert len(non_empty) > 0, "Expected at least one non-empty display line"

    tail = sess.get_display_tail(5)
    assert isinstance(tail, list), "get_display_tail should return a list"
    assert 1 <= len(tail) <= 5, (
        f"Expected 1-5 tail lines (cursor-anchored), got {len(tail)}"
    )
    # At least one tail line should contain the prompt or some content
    tail_has_content = any(l.strip() for l in tail)
    assert tail_has_content, "Expected at least one non-empty line in display tail"

    sess.kill()
    # Wait for kill to propagate
    time.sleep(1)
    assert sess.state == SessionState.DEAD, f"Expected DEAD, got {sess.state}"


# ===================================================================
# 3. ShellSession — prompt detection → READY
# ===================================================================
def test_shell_session_ready():
    sess = ShellSession(
        session_id="test_shell",
        workspace=WORKSPACE,
        shell_type="powershell",
        cols=120,
        rows=40,
    )
    sess.spawn()

    # Poll for READY state for up to 20 seconds (PowerShell startup can be slow)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if sess.state == SessionState.READY:
            break
        time.sleep(0.25)

    assert sess.state == SessionState.READY, (
        f"ShellSession did not reach READY within 20 s (state={sess.state.value})"
    )
    sess.kill()
    time.sleep(1)


# ===================================================================
# 4. TES EventStreamManager
# ===================================================================
def test_tes_publish_data_and_consume():
    """publish_data → next_data_for → event returned."""
    es = EventStreamManager()
    es.register_consumer("sess_a")

    ev = es.publish_data(source="user", target="session:sess_a", text="hello")
    assert ev.id == 1, f"Expected first event id=1, got {ev.id}"
    assert ev.channel == Channel.DATA

    fetched = es.next_data_for("sess_a", after_id=0)
    assert fetched is not None, "next_data_for should return the event"
    assert fetched.id == ev.id
    assert fetched.data["text"] == "hello"

    # No more events
    fetched2 = es.next_data_for("sess_a", after_id=fetched.id)
    assert fetched2 is None, "No second event should be available"

    es.close()


def test_tes_gc_pruning():
    """register_consumer → consume → gc → events pruned."""
    es = EventStreamManager()
    es.register_consumer("c1")
    es.register_consumer("c2")

    # Publish 5 data events to c1
    for i in range(5):
        es.publish_data("user", "session:c1", f"msg_{i}")
    assert es.event_count == 5

    # c1 consumes up to event 3
    cursor = 0
    for _ in range(3):
        ev = es.next_data_for("c1", cursor)
        assert ev is not None
        cursor = ev.id

    # c2 has cursor=0 (hasn't consumed anything) → gc should prune nothing because
    # min cursor across consumers is 0
    pruned = es.gc()
    # c2 cursor is 0, min is 0, so nothing can be pruned (all events have id >= 0)
    assert es.event_count == 5, f"Expected 5 events (c2 cursor=0), got {es.event_count}"

    # c2 consumes all 5 (targeted to c1, but let's test with a different target)
    # Actually c2 has no events targeted at it. Let's just advance its cursor manually.
    es._consumer_cursors["c2"] = 3
    pruned = es.gc()
    # min cursor is 3 (both c1 and c2 at 3), events with id < 3 are pruned
    # Events have ids 1,2,3,4,5 — keep those with id >= 3 → keep 3,4,5
    assert es.event_count == 3, f"After GC expected 3 events, got {es.event_count}"
    assert pruned == 2, f"Expected 2 pruned, got {pruned}"

    # Unregister c2, advance c1 past all events, gc should prune more
    es.unregister_consumer("c2")
    es._consumer_cursors["c1"] = 5
    pruned = es.gc()
    # min cursor is 5, keep id >= 5 → only event #5 remains
    assert es.event_count == 1, f"After second GC expected 1 event, got {es.event_count}"

    es.close()


def test_tes_control_state_not_accumulated():
    """Control/State events should NOT be stored in _events list."""
    es = EventStreamManager()

    # Track dispatched events
    control_received = []
    state_received = []
    es.on_control("session:x", lambda e: control_received.append(e))
    es.subscribe_state(lambda e: state_received.append(e))

    es.publish_control("kill", "session:x", {"reason": "test"})
    es.publish_state("x", "starting", "ready")
    es.publish_control("resize", "session:x", {"cols": 80, "rows": 24})
    es.publish_state("x", "ready", "busy")

    # _events should be empty — only Data events are stored
    assert es.event_count == 0, (
        f"Control/State events should NOT accumulate in _events, got {es.event_count}"
    )

    # But they were dispatched
    assert len(control_received) == 2, f"Expected 2 control dispatches, got {len(control_received)}"
    assert len(state_received) == 2, f"Expected 2 state dispatches, got {len(state_received)}"

    es.close()


# ===================================================================
# 5. Pane + Rect
# ===================================================================
def test_pane_focus_blur_manual():
    """focus() → enter_manual, blur() → exit_manual."""
    sess = TerminalSession(
        session_id="test_pane_sess",
        cmd=["powershell.exe", "-NoLogo", "-NoProfile"],
        workspace=WORKSPACE,
        cols=80,
        rows=24,
    )
    sess.spawn()
    time.sleep(1)

    pane = Pane("p1", sess)
    assert not pane.focused, "Pane should start unfocused"

    # Focus → MANUAL
    pane.focus()
    assert pane.focused
    assert sess.state == SessionState.MANUAL, f"Expected MANUAL after focus, got {sess.state}"

    # Blur → restore previous state
    pane.blur()
    assert not pane.focused
    assert sess.state != SessionState.MANUAL, (
        f"Expected non-MANUAL after blur, got {sess.state}"
    )

    sess.kill()
    time.sleep(0.5)


def test_pane_set_rect_resize():
    """set_rect propagates resize to session."""
    sess = TerminalSession(
        session_id="test_pane_resize",
        cmd=["powershell.exe", "-NoLogo", "-NoProfile"],
        workspace=WORKSPACE,
        cols=80,
        rows=24,
    )
    sess.spawn()
    time.sleep(1)

    pane = Pane("p2", sess, Rect(0, 0, 80, 24))

    # Resize pane
    pane.set_rect(Rect(0, 0, 120, 40))
    assert pane.rect.w == 120
    assert pane.rect.h == 40
    assert sess._screen.columns == 120, f"Expected screen cols=120, got {sess._screen.columns}"
    assert sess._screen.lines == 40, f"Expected screen rows=40, got {sess._screen.lines}"

    # Move pane without size change → no resize call (just position update)
    pane.set_rect(Rect(5, 5, 120, 40))
    assert pane.rect.x == 5
    assert pane.rect.y == 5

    sess.kill()
    time.sleep(0.5)


# ===================================================================
# Main
# ===================================================================
def main():
    print("=" * 60)
    print("Terminalist Smoke Tests")
    print("=" * 60)
    print()

    print("[1] WinPtyBackend: spawn / read / terminate")
    run_test("winpty_backend_spawn_read_terminate", test_winpty_backend_spawn_read_terminate)
    print()

    print("[2] TerminalSession: display")
    run_test("terminal_session_display", test_terminal_session_display)
    print()

    print("[3] ShellSession: READY state")
    run_test("shell_session_ready", test_shell_session_ready)
    print()

    print("[4] TES EventStreamManager")
    run_test("tes_publish_data_and_consume", test_tes_publish_data_and_consume)
    run_test("tes_gc_pruning", test_tes_gc_pruning)
    run_test("tes_control_state_not_accumulated", test_tes_control_state_not_accumulated)
    print()

    print("[5] Pane + Rect")
    run_test("pane_focus_blur_manual", test_pane_focus_blur_manual)
    run_test("pane_set_rect_resize", test_pane_set_rect_resize)
    print()

    code = summary()
    sys.exit(code)


if __name__ == "__main__":
    main()
