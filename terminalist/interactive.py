"""Single-session interactive shell — I/O verification via dualrun.

Spawns one ShellSession and bridges it to the current terminal.
All input handling is in terminalist.input.handler.

Usage:
    python -m terminalist.interactive [--debug]
    python -m terminalist.dualrun -m terminalist.interactive

Exit: Ctrl+B then Ctrl+C.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from terminalist.debug import init_debug, log, detect_env
from terminalist.pyte_patch import apply as patch_pyte
from terminalist.core.shell_session import ShellSession
from terminalist.input.win32 import enable_vt, enter_alt_screen, exit_alt_screen, terminal_size, RawConsoleInput
from terminalist.input.handler import run_input_loop


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Terminalist interactive shell")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    p.add_argument("--debug-log", type=str, default=None, help="Debug log file path")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    init_debug(enabled=args.debug, log_path=args.debug_log)
    patch_pyte()
    enable_vt()

    env = detect_env()
    rows, cols = terminal_size()
    log("app", f"=== Interactive shell starting (env={env}, {cols}x{rows}) ===")

    enter_alt_screen()

    session = ShellSession("interactive", Path.cwd(), shell_type="powershell", cols=cols, rows=rows)

    # Raw output → stdout + bracketed paste tracking
    def on_raw_output(data: str) -> None:
        if hasattr(run_input_loop, "track_bracketed_paste"):
            run_input_loop.track_bracketed_paste(data)
        try:
            sys.stdout.write(data)
            sys.stdout.flush()
        except Exception:
            pass

    session._on_raw_output.append(on_raw_output)
    session.spawn()
    log("app", f"Session spawned pid={session._backend.pid}")

    # Run input loop with raw console mode
    with RawConsoleInput() as h_in:
        run_input_loop(
            h_in=h_in,
            write=session.write_raw,
            is_alive=session._backend.is_alive,
            resize=lambda c, r: session.resize(cols=c, rows=r),
            initial_size=(rows, cols),
        )

    # Cleanup
    log("app", f"Exiting. Session state={session.state.value}")
    try:
        session.kill()
    except Exception as e:
        log("app", f"Kill error (ignored): {e}")
    exit_alt_screen()
    log("app", "=== Interactive shell ended ===")
    print("[terminalist] Session ended.")


if __name__ == "__main__":
    main()
