"""Terminalist — Main entry point.

Currently a minimal skeleton for debug/smoke testing.
Full implementation (input loop, compositor, chrome) is pending.

Usage:
    python -m terminalist.app [--debug]
    terminalist [--debug]               (after pip install -e .)
"""

from __future__ import annotations

import argparse
import sys
import time

from terminalist.debug import init_debug, log, detect_env
from terminalist.pyte_patch import apply as patch_pyte
from terminalist.events.tes import EventStreamManager
from terminalist.core.session_manager import SessionManager


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Terminalist — LLM CLI terminal multiplexer")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    p.add_argument("--debug-log", type=str, default=None, help="Debug log file path")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # ── Init ──
    init_debug(enabled=args.debug, log_path=args.debug_log)
    patch_pyte()
    log("app", "=== Terminalist starting ===")
    log("app", f"env={detect_env()}")

    # ── TES ──
    tes = EventStreamManager(
        event_log_path=None  # TODO: enable when needed
    )
    log("app", "TES initialized")

    # ── SessionManager ──
    sm = SessionManager(tes)
    log("app", "SessionManager initialized")

    # ── Smoke: spawn a PowerShell session ──
    print(f"[terminalist] env={detect_env()}, debug={'ON' if args.debug else 'OFF'}")
    print("[terminalist] Spawning PowerShell session...")

    session = sm.create("powershell", workspace=".")
    log("app", f"Session created: {session.session_id}")

    # Wait for ready
    print("[terminalist] Waiting for shell ready...")
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if session.state.value == "ready":
            break
        time.sleep(0.1)

    state = session.state.value
    log("app", f"Session state after wait: {state}")
    print(f"[terminalist] Session state: {state}")

    # Show display
    tail = session.get_display_tail(5)
    log("app", f"Display tail ({len(tail)} lines):")
    for i, line in enumerate(tail):
        stripped = line.rstrip()
        if stripped:
            log("app", f"  {i}: {stripped!r}")
            print(f"  [{i}] {stripped}")

    # ── Cleanup ──
    print("[terminalist] Cleaning up...")
    sm.destroy(session.session_id)
    tes.close()
    log("app", "=== Terminalist exiting ===")
    print("[terminalist] Done.")


if __name__ == "__main__":
    main()
