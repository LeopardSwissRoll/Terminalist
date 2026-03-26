"""Debug logging for Terminalist.

Provides layer-based logging with automatic environment detection
(VSCode integrated terminal vs. external terminal).

Usage:
    from terminalist.debug import init_debug, log
    init_debug(enabled=True)                     # auto-detect env
    init_debug(enabled=True, log_path="my.log")  # explicit path
    init_debug(enabled=True, env_tag="external")  # explicit tag

Environment detection:
    VSCODE_PID in env → tag="vscode", log="terminalist_debug_vscode.log"
    otherwise         → tag="external", log="terminalist_debug_external.log"
    TERMINALIST_ENV   → override (set by dualrun.py)
"""

from __future__ import annotations

import html
import locale
import logging
import os
import platform
import sys
from pathlib import Path
from shutil import get_terminal_size
from typing import TYPE_CHECKING

try:
    import ctypes
except Exception:  # pragma: no cover
    ctypes = None

if TYPE_CHECKING:
    from pyte.screens import Char

_logger: logging.Logger | None = None
_env_tag: str = "unknown"

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
    "VSCODE_NONCE",
    "TERMINALIST_ENV",
    "CLAUDECODE",
    "CLAUDE_CODE_SSE_PORT",
    "CLAUDE_CODE_ENTRYPOINT",
    "PROMPT",
    "ComSpec",
]


def detect_env() -> str:
    """Detect terminal environment. Returns 'vscode' or 'external'."""
    # Explicit override from dualrun
    explicit = os.environ.get("TERMINALIST_ENV")
    if explicit:
        return explicit
    # VSCode detection
    if os.environ.get("VSCODE_PID") or os.environ.get("VSCODE_INJECTION"):
        return "vscode"
    return "external"


def default_log_path(env_tag: str | None = None) -> Path:
    """Return default log file path based on environment."""
    tag = env_tag or detect_env()
    return Path(f"terminalist_debug_{tag}.log")


def init_debug(
    enabled: bool = False,
    log_path: str | Path | None = None,
    env_tag: str | None = None,
) -> None:
    """Initialize debug logging. Call once at startup.

    Args:
        enabled: Enable debug logging.
        log_path: Explicit log file path. Auto-generated if None.
        env_tag: Environment tag ('vscode', 'external', etc.). Auto-detected if None.
    """
    global _logger, _env_tag
    if not enabled:
        _logger = None
        return

    _env_tag = env_tag or detect_env()

    _logger = logging.getLogger("terminalist")
    _logger.setLevel(logging.DEBUG)
    _logger.handlers.clear()

    path = Path(log_path) if log_path else default_log_path(_env_tag)
    fh = logging.FileHandler(str(path), mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        f"%(asctime)s.%(msecs)03d [{_env_tag:8s}] %(message)s",
        datefmt="%H:%M:%S",
    )
    fh.setFormatter(fmt)
    _logger.addHandler(fh)

    _logger.info(f"=== Terminalist debug logging started (env={_env_tag}) ===")
    _logger.info(f"Python {sys.version}")
    _logger.info(f"Log file: {path.resolve()}")
    log_runtime_context()


def log(layer: str, msg: str) -> None:
    """Log a debug message from a specific layer.

    Layers:
        app      — Main loop (startup, shutdown, tick)
        ctx      — Host terminal / runtime context
        focus    — Focus/blur events
        key      — Key events (which pane, what key, forwarded?)
        click    — Mouse click events
        mouse    — Mouse drag / copy interactions
        session  — Session state transitions
        pty      — PTY spawn/read/write/kill
        pyte     — pyte screen feed/dirty
        screen   — Visible screen snapshots after PTY feeds
        tes      — TES event publish/consume/dispatch/gc
        render   — Compositor output (diff, cells written)
        layout   — Split tree / pane geometry
        input    — Input backend (raw bytes, parsed keys)
        chrome   — Tab bar / status bar
    """
    if _logger is not None:
        _logger.debug(f"[{layer:8s}] {msg}")


def is_enabled() -> bool:
    return _logger is not None


def get_env_tag() -> str:
    return _env_tag


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
    log("ctx", f"env_tag={_env_tag}")
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


def _artifact_path(name: str, suffix: str) -> Path:
    return Path(f"terminalist_{name}_{_env_tag}{suffix}")


def _color_to_css(color: str, *, background: bool = False) -> str:
    """Translate pyte color names/values to CSS."""
    named = {
        "default": "transparent" if background else "inherit",
        "black": "#000000",
        "red": "#cd3131",
        "green": "#0dbc79",
        "yellow": "#e5e510",
        "blue": "#2472c8",
        "magenta": "#bc3fbc",
        "cyan": "#11a8cd",
        "white": "#e5e5e5",
        "bright_black": "#666666",
        "bright_red": "#f14c4c",
        "bright_green": "#23d18b",
        "bright_yellow": "#f5f543",
        "bright_blue": "#3b8eea",
        "bright_magenta": "#d670d6",
        "bright_cyan": "#29b8db",
        "bright_white": "#ffffff",
    }
    if color in named:
        return named[color]
    hex_color = color.lstrip("#")
    if len(hex_color) == 6:
        try:
            int(hex_color, 16)
            return f"#{hex_color}"
        except ValueError:
            pass
    return "transparent" if background else "inherit"


def _format_frame_simple(frame: list[list[Char]], width: int, height: int) -> str:
    lines: list[str] = []
    for y in range(min(height, len(frame))):
        row_chars: list[str] = []
        for x in range(min(width, len(frame[y]))):
            ch = frame[y][x]
            if ch.data == "":
                continue
            row_chars.append(ch.data)
        lines.append("".join(row_chars))
    return "\n".join(lines)


def _format_frame_detail(frame: list[list[Char]], width: int, height: int) -> str:
    lines: list[str] = []
    for y in range(min(height, len(frame))):
        data_parts: list[str] = []
        attr_parts: list[str] = []
        for x in range(min(width, len(frame[y]))):
            ch = frame[y][x]
            data_parts.append(ch.data if ch.data else "_")
            attr_parts.append(
                f"[{x:03d}] fg={ch.fg} bg={ch.bg} "
                f"b={'1' if ch.bold else '0'} i={'1' if ch.italics else '0'} "
                f"u={'1' if ch.underscore else '0'} r={'1' if ch.reverse else '0'} "
                f"s={'1' if ch.strikethrough else '0'} blink={'1' if ch.blink else '0'}"
            )
        lines.append(f"Row {y:03d}: {''.join(data_parts)}")
        lines.extend(f"  {part}" for part in attr_parts)
    return "\n".join(lines)


def _format_frame_html(
    frame: list[list[Char]],
    width: int,
    height: int,
    *,
    focused_pane_id: str | None,
    cursor: tuple[int, int] | None,
) -> str:
    rows: list[str] = []
    for y in range(min(height, len(frame))):
        cells: list[str] = []
        for x in range(min(width, len(frame[y]))):
            ch = frame[y][x]
            data = ch.data if ch.data else " "
            styles = [
                f"color:{_color_to_css(ch.fg)}",
                f"background:{_color_to_css(ch.bg, background=True)}",
                "font-weight:700" if ch.bold else "font-weight:400",
                "font-style:italic" if ch.italics else "font-style:normal",
                "text-decoration: underline" if ch.underscore else "text-decoration:none",
            ]
            title = (
                f"x={x} y={y} data={data!r} fg={ch.fg} bg={ch.bg} "
                f"bold={ch.bold} italics={ch.italics} underscore={ch.underscore} "
                f"reverse={ch.reverse} strike={ch.strikethrough} blink={ch.blink}"
            )
            classes = "cell"
            if cursor == (x, y):
                classes += " cursor"
            cells.append(
                f'<span class="{classes}" style="{";".join(styles)}" '
                f'title="{html.escape(title)}">{html.escape(data)}</span>'
            )
        rows.append(f'<div class="row"><span class="rowno">{y:03d}</span>{"".join(cells)}</div>')

    meta = [
        f"env={_env_tag}",
        f"size={width}x{height}",
        f"focused={focused_pane_id or '-'}",
        f"cursor={cursor if cursor is not None else '-'}",
    ]
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Terminalist Render Snapshot</title>
<style>
body {{
  margin: 0;
  padding: 16px;
  background: #111;
  color: #ddd;
  font: 14px/1 Consolas, "Cascadia Mono", monospace;
}}
.meta {{
  margin-bottom: 12px;
  white-space: pre-wrap;
  line-height: 1.4;
}}
.row {{
  white-space: nowrap;
  height: 1.1em;
}}
.rowno {{
  display: inline-block;
  width: 3.5em;
  color: #666;
}}
.cell {{
  display: inline-block;
  width: 1ch;
  text-align: center;
}}
.cursor {{
  outline: 1px solid #ffcc00;
  outline-offset: -1px;
}}
</style>
<div class="meta">{html.escape(" | ".join(meta))}</div>
{''.join(rows)}
</html>
"""


def dump_render_snapshot(
    frame: list[list[Char]],
    width: int,
    height: int,
    vt100_output: str,
    *,
    focused_pane_id: str | None = None,
    cursor: tuple[int, int] | None = None,
) -> None:
    """Write the latest composed frame + emitted VT100 to debug artifacts.

    Files are overwritten on each render so they always represent the latest
    compositor state for the current environment.
    """
    if _logger is None:
        return
    _artifact_path("render_frame", ".txt").write_text(
        _format_frame_simple(frame, width, height),
        encoding="utf-8",
    )
    _artifact_path("render_detail", ".txt").write_text(
        _format_frame_detail(frame, width, height),
        encoding="utf-8",
    )
    _artifact_path("render_preview", ".html").write_text(
        _format_frame_html(
            frame,
            width,
            height,
            focused_pane_id=focused_pane_id,
            cursor=cursor,
        ),
        encoding="utf-8",
    )
    _artifact_path("render_vt100", ".txt").write_text(
        vt100_output,
        encoding="utf-8",
    )
    _artifact_path("render_vt100_repr", ".txt").write_text(
        repr(vt100_output),
        encoding="utf-8",
    )
    log(
        "render",
        "Artifacts updated: "
        f"{_artifact_path('render_frame', '.txt').name}, "
        f"{_artifact_path('render_detail', '.txt').name}, "
        f"{_artifact_path('render_preview', '.html').name}, "
        f"{_artifact_path('render_vt100_repr', '.txt').name}",
    )
