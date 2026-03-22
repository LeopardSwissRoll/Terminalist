"""Dual-environment test runner for Terminalist.

Runs the same command in TWO environments simultaneously:
  1. Current terminal (assumed VSCode integrated terminal)
  2. New external PowerShell window

Both instances get --debug automatically and write separate log files:
  - terminalist_debug_vscode.log   (current terminal)
  - terminalist_debug_external.log (spawned PowerShell window)

Usage (from VSCode terminal):
    python -m terminalist.dualrun <command> [args...]

Examples:
    python -m terminalist.dualrun -m terminalist.app
    python -m terminalist.dualrun tests/smoke_core.py
    python -m terminalist.dualrun -c "from terminalist.core.winpty_backend import WinPtyBackend; print('ok')"

The external window stays open after the command finishes (for inspection).
Press Ctrl+C in VSCode terminal to stop the local instance.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _build_python_cmd(args: list[str]) -> str:
    """Build a python command string from args."""
    # Use the same Python interpreter
    python = sys.executable
    escaped_args = []
    for a in args:
        # Escape for PowerShell
        if " " in a or "'" in a or '"' in a:
            escaped = a.replace("'", "''")
            escaped_args.append(f"'{escaped}'")
        else:
            escaped_args.append(a)
    return f'"{python}" {" ".join(escaped_args)}'


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    user_args = sys.argv[1:]
    cwd = Path.cwd()
    python = sys.executable

    # ── Detect if --debug is already in args ──
    has_debug = "--debug" in user_args
    local_args = list(user_args)
    external_args = list(user_args)
    if not has_debug:
        local_args.append("--debug")
        external_args.append("--debug")

    # ── Build commands ──
    local_cmd = [python] + local_args
    external_cmd_str = _build_python_cmd(external_args)

    # ── Spawn external PowerShell window ──
    # Write a temp .ps1 script to avoid quoting hell with Start-Process
    import tempfile
    script_content = (
        f"$env:TERMINALIST_ENV='external'\n"
        f"Set-Location '{cwd}'\n"
        f"& '{python}' {' '.join(external_args)}\n"
        f"Write-Host ''\n"
        f"Write-Host '=== External instance finished. Press Enter to close ===' -ForegroundColor Yellow\n"
        f"Read-Host\n"
    )
    script_file = Path(tempfile.gettempdir()) / "terminalist_dualrun_external.ps1"
    script_file.write_text(script_content, encoding="utf-8")

    print(f"[dualrun] Spawning external PowerShell window...")
    print(f"[dualrun] Command: {' '.join(local_cmd)}")
    print(f"[dualrun] Logs: terminalist_debug_vscode.log / terminalist_debug_external.log")
    print()

    subprocess.Popen(
        ["powershell", "-Command",
         f"Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File','{script_file}'"],
        cwd=str(cwd),
    )

    # ── Run locally (VSCode) ──
    local_env = os.environ.copy()
    local_env["TERMINALIST_ENV"] = "vscode"

    try:
        result = subprocess.run(
            local_cmd,
            cwd=str(cwd),
            env=local_env,
        )
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\n[dualrun] Stopped (Ctrl+C). External window may still be running.")
        sys.exit(130)


if __name__ == "__main__":
    main()
