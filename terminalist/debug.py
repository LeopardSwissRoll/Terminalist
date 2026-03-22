"""Debug logging for Terminalist.

When --debug is passed, logs to terminalist_debug.log with detailed
tracing of every layer: Textual events, session state, PTY I/O, TES events.

Usage:
    python -m terminalist.app --debug
"""

from __future__ import annotations

import locale
import logging
import os
import platform
import sys
from pathlib import Path
from shutil import get_terminal_size

try:
    import ctypes
except Exception:  # pragma: no cover
    ctypes = None

_logger: logging.Logger | None = None
_CONTEXT_ENV_KEYS = [
    "TERM",
    "COLORTERM",
    "TERM_PROGRAM",
    "TERM_PROGRAM_VERSION",
    "WT_SESSION",
    "WT_PROFILE_ID",
    "VSCODE_PID",
    "VSCODE_CWD",
    "VSCODE_IPC_HOOK_CLI",
    "VSCODE_INJECTION",
    "PROMPT",
    "ComSpec",
]


def init_debug(enabled: bool = False) -> None:
    """Initialize debug logging. Call once at startup."""
    global _logger
    if not enabled:
        _logger = None
        return

    _logger = logging.getLogger("terminalist")
    _logger.setLevel(logging.DEBUG)
    _logger.handlers.clear()

    log_path = Path("terminalist_debug.log")
    fh = logging.FileHandler(str(log_path), mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    fh.setFormatter(fmt)
    _logger.addHandler(fh)

    _logger.info("=== Terminalist debug logging started ===")
    _logger.info(f"Python {sys.version}")
    _logger.info(f"Log file: {log_path.resolve()}")
    log_runtime_context()


def log(layer: str, msg: str) -> None:
    """Log a debug message from a specific layer.

    Layers:
        app      — Textual App level (mount, compose, actions)
        ctx      — Host terminal / runtime context
        focus    — Focus/blur events on widgets
        key      — Key events (which widget, what key, forwarded?)
        click    — Mouse click events
        mouse    — Mouse drag / copy interactions
        session  — Session state transitions
        pty      — PTY spawn/read/write/kill
        pyte     — pyte screen feed/dirty
        screen   — Visible screen snapshots after PTY feeds
        tes      — TES event publish/consume/dispatch
        render   — render_line calls
    """
    if _logger is not None:
        _logger.debug(f"[{layer:8s}] {msg}")


def is_enabled() -> bool:
    return _logger is not None


def _console_code_pages() -> str:
    if ctypes is None or os.name != "nt":
        return "n/a"
    kernel32 = ctypes.windll.kernel32
    return (
        f"input_cp={kernel32.GetConsoleCP()} "
        f"output_cp={kernel32.GetConsoleOutputCP()}"
    )


def _stdio_description(name: str, stream, fd: int) -> str:
    isatty = getattr(stream, "isatty", lambda: False)()
    encoding = getattr(stream, "encoding", None)
    errors = getattr(stream, "errors", None)
    device_encoding = os.device_encoding(fd)
    return (
        f"{name}: isatty={isatty} encoding={encoding!r} errors={errors!r} "
        f"device_encoding={device_encoding!r}"
    )


def log_runtime_context() -> None:
    """Log startup/runtime context useful for host-terminal debugging."""
    log("ctx", f"argv={sys.argv!r}")
    log("ctx", f"cwd={Path.cwd()}")
    log("ctx", f"platform={platform.platform()}")
    log(
        "ctx",
        "locale="
        f"preferred={locale.getpreferredencoding(False)!r} "
        f"fs={sys.getfilesystemencoding()!r} "
        f"stdout={sys.stdout.encoding!r}",
    )
    log("ctx", _stdio_description("stdin", sys.stdin, 0))
    log("ctx", _stdio_description("stdout", sys.stdout, 1))
    log("ctx", _stdio_description("stderr", sys.stderr, 2))
    log("ctx", f"console_cp={_console_code_pages()}")
    width, height = get_terminal_size(fallback=(0, 0))
    log("ctx", f"host_terminal_size={width}x{height}")
    for key in _CONTEXT_ENV_KEYS:
        if key in os.environ:
            log("ctx", f"env[{key}]={os.environ[key]!r}")


def log_screen_snapshot(
    session_id: str,
    lines: list[str],
    *,
    cursor: tuple[int, int] | None = None,
    tail: int = 6,
) -> None:
    """Log the visible tail of a terminal screen."""
    if _logger is None:
        return
    if cursor is not None:
        log("screen", f"[{session_id}] cursor={cursor[0]},{cursor[1]}")
    start = max(0, len(lines) - tail)
    for index, line in enumerate(lines[start:], start=start):
        log("screen", f"[{session_id}] {index:03}: {line!r}")
