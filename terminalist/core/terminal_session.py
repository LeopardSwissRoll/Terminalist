"""TerminalSession — pyte screen + state machine + TES connection.

PTY lifecycle is delegated to PtyBackend (composition).
View/layout concerns belong to Pane (separate class).
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyte

from terminalist.debug import is_enabled, log, log_screen_snapshot
from .pty_backend import PtyBackend
from .winpty_backend import WinPtyBackend

if TYPE_CHECKING:
    from terminalist.events.event import Event
    from terminalist.events.tes import EventStreamManager


class SessionState(Enum):
    STARTING = "starting"
    READY = "ready"
    BUSY = "busy"
    MANUAL = "manual"
    DEAD = "dead"


class TerminalSession:
    """Terminal session: pyte virtual screen + state machine.

    PTY I/O is handled by a PtyBackend instance (default: WinPtyBackend).
    """

    def __init__(
        self,
        session_id: str,
        cmd: list[str],
        workspace: Path,
        env: dict[str, str] | None = None,
        cols: int = 120,
        rows: int = 40,
        backend: PtyBackend | None = None,
    ) -> None:
        self.session_id = session_id
        self.cmd = cmd
        self.workspace = workspace
        self.env = env or {}
        self.state = SessionState.DEAD
        self._pre_manual_state: SessionState | None = None

        # PTY backend (composable, swappable)
        self._backend: PtyBackend = backend or WinPtyBackend()

        # pyte virtual terminal
        self._screen = pyte.HistoryScreen(cols, rows, history=5000)
        self._stream = pyte.Stream(self._screen)
        self._lock = threading.Lock()

        # Reader thread
        self._reader_thread: threading.Thread | None = None
        self._alive = False

        # TES connection
        self._event_stream: EventStreamManager | None = None
        self._cursor: int = 0

        # Dirty tracking — multiple subscribers
        self._dirty_rows: set[int] = set()
        self._on_dirty_listeners: list[Callable[[], None]] = []

        log("session", f"[{session_id}] created cmd={cmd} cols={cols} rows={rows}")

    # ── PTY lifecycle (delegated to backend) ──

    def spawn(self) -> None:
        """Start PTY process and reader thread."""
        cmdline = subprocess.list2cmdline(self.cmd)
        rows, cols = self._screen.lines, self._screen.columns
        cwd = str(self.workspace)
        log("pty", f"[{self.session_id}] spawning: {cmdline} cwd={cwd} dims=({rows},{cols})")
        if is_enabled():
            log(
                "ctx",
                f"[{self.session_id}] spawn_env_overrides="
                f"{ {k: self.env[k] for k in sorted(self.env)}!r}",
            )

        env_merged = self._merged_env() if self.env else None
        self._backend.spawn(cmdline, cwd, rows, cols, env_merged)

        self._alive = True
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True
        )
        self._reader_thread.start()
        self.state = SessionState.STARTING
        log("pty", f"[{self.session_id}] spawned pid={self._backend.pid}, reader thread started")

    def kill(self) -> None:
        """Graceful shutdown. Subclasses override _exit_command() for provider-specific exit."""
        log("pty", f"[{self.session_id}] killing")
        self._alive = False
        if self._backend.is_alive():
            exit_cmd = self._exit_command()
            if exit_cmd:
                try:
                    self._backend.write(exit_cmd + "\r")
                    log("pty", f"[{self.session_id}] sent {exit_cmd!r}, waiting 1s")
                except Exception:
                    pass
                time.sleep(1.0)
            if self._backend.is_alive():
                try:
                    self._backend.terminate()
                    log("pty", f"[{self.session_id}] force terminated")
                except Exception as e:
                    log("pty", f"[{self.session_id}] terminate error: {e}")
        if (
            self._reader_thread
            and self._reader_thread.is_alive()
            and self._reader_thread is not threading.current_thread()
        ):
            self._reader_thread.join(timeout=2.0)
        self._set_state(SessionState.DEAD)

    def _exit_command(self) -> str | None:
        """Return the graceful exit command for this session type. None = skip, just terminate."""
        return None

    def resize(self, cols: int, rows: int) -> None:
        """Resize terminal."""
        log("pty", f"[{self.session_id}] resize {cols}x{rows}")
        try:
            self._backend.set_size(rows, cols)
        except Exception as e:
            log("pty", f"[{self.session_id}] setwinsize error: {e}")
        with self._lock:
            self._screen.resize(rows, cols)

    def _merged_env(self) -> dict[str, str]:
        merged = os.environ.copy()
        merged.update(self.env)
        return merged

    def _handle_control(self, event: Event) -> None:
        log("tes", f"[{self.session_id}] control event: {event.kind}")
        if event.kind == "kill":
            self.kill()
        elif event.kind == "resize":
            self.resize(
                event.data.get("cols", 120), event.data.get("rows", 40)
            )

    # ── PTY I/O (via backend) ──

    def write_raw(self, data: str) -> None:
        """Write raw data to PTY."""
        if self._backend.is_alive():
            log("pty", f"[{self.session_id}] write_raw: {data!r:.50}")
            self._backend.write(data)

    def send_input(self, text: str) -> None:
        """Programmatic input (fire-and-forget)."""
        if self.state in (SessionState.MANUAL, SessionState.DEAD):
            log("session", f"[{self.session_id}] send_input BLOCKED (state={self.state.value})")
            return
        log("session", f"[{self.session_id}] send_input: {text!r:.80}")
        self._set_state(SessionState.BUSY)
        if self._backend.is_alive():
            self._backend.write(text + "\r\n")

    def get_display(self) -> list[str]:
        """Return current screen content."""
        with self._lock:
            result: list[str] = []
            for y in range(self._screen.lines):
                try:
                    line = "".join(
                        self._screen.buffer[y][x].data or " "
                        for x in range(self._screen.columns)
                    )
                except (IndexError, KeyError):
                    line = " " * self._screen.columns
                result.append(line)
            return result

    def get_display_tail(self, n: int = 5) -> list[str]:
        """Return last n lines of screen content (for prompt detection)."""
        with self._lock:
            start = max(0, self._screen.lines - n)
            result: list[str] = []
            for y in range(start, self._screen.lines):
                try:
                    line = "".join(
                        self._screen.buffer[y][x].data or " "
                        for x in range(self._screen.columns)
                    )
                except (IndexError, KeyError):
                    line = " " * self._screen.columns
                result.append(line)
            return result

    # ── Reader loop ──

    def _reader_loop(self) -> None:
        """Read PTY output → feed pyte → track dirty rows."""
        log("pty", f"[{self.session_id}] reader_loop started")
        read_count = 0
        try:
            while self._alive:
                if not self._backend.is_alive():
                    log("pty", f"[{self.session_id}] process not alive, exiting reader")
                    break
                try:
                    data = self._backend.read(4096)
                except EOFError:
                    log("pty", f"[{self.session_id}] EOF from process")
                    break
                except Exception as e:
                    log("pty", f"[{self.session_id}] read exception: {type(e).__name__}: {e}")
                    if not self._alive:
                        break
                    time.sleep(0.05)
                    continue
                if not data:
                    continue
                if not self._alive:
                    break
                read_count += 1
                log("pyte", f"[{self.session_id}] feed #{read_count} len={len(data)} data={data!r:.100}")
                with self._lock:
                    self._stream.feed(data)
                    self._dirty_rows.update(self._screen.dirty)
                    self._screen.dirty.clear()
                    display_tail = list(self._screen.display)
                    cursor = (self._screen.cursor.x, self._screen.cursor.y)
                dirty_count = len(self._dirty_rows)
                if dirty_count > 0:
                    log("pyte", f"[{self.session_id}] dirty_rows={dirty_count} listeners={len(self._on_dirty_listeners)}")
                if is_enabled():
                    log_screen_snapshot(
                        self.session_id,
                        display_tail,
                        cursor=cursor,
                    )
                for cb in list(self._on_dirty_listeners):
                    cb()
                self._check_state_transition()
        finally:
            log("pty", f"[{self.session_id}] reader_loop exited after {read_count} reads")
            self._alive = False
            if self.state != SessionState.DEAD:
                self._set_state(SessionState.DEAD)

    # ── Dirty listeners (multiple pane support) ──

    def add_dirty_listener(self, cb: Callable[[], None]) -> None:
        log("session", f"[{self.session_id}] add_dirty_listener (total={len(self._on_dirty_listeners)+1})")
        self._on_dirty_listeners.append(cb)

    def remove_dirty_listener(self, cb: Callable[[], None]) -> None:
        try:
            self._on_dirty_listeners.remove(cb)
        except ValueError:
            pass

    # ── State management ──

    def _set_state(self, new_state: SessionState) -> None:
        if self.state != new_state:
            old = self.state
            self.state = new_state
            log("session", f"[{self.session_id}] {old.value} → {new_state.value}")
            if self._event_stream:
                self._event_stream.publish_state(
                    self.session_id, old.value, new_state.value
                )
            if new_state == SessionState.READY:
                self._try_consume_next()

    def _check_state_transition(self) -> None:
        pass

    def enter_manual(self) -> None:
        """User takes focus → MANUAL mode."""
        log("session", f"[{self.session_id}] enter_manual (current={self.state.value})")
        if self.state != SessionState.MANUAL:
            self._pre_manual_state = self.state
            self._set_state(SessionState.MANUAL)

    def exit_manual(self) -> None:
        """User releases focus → restore previous state."""
        restore = self._pre_manual_state or SessionState.READY
        log("session", f"[{self.session_id}] exit_manual → restore to {restore.value}")
        if self.state == SessionState.MANUAL:
            self._pre_manual_state = None
            self._set_state(restore)

    # ── TES connection ──

    def bind_event_stream(self, es: EventStreamManager) -> None:
        self._event_stream = es

    def consume_next_data(self) -> Event | None:
        if self.state != SessionState.READY or not self._event_stream:
            return None
        event = self._event_stream.next_data_for(
            self.session_id, self._cursor
        )
        if event:
            self._cursor = event.id
            log("tes", f"[{self.session_id}] consumed data event #{event.id}")
        return event

    def _try_consume_next(self) -> None:
        event = self.consume_next_data()
        if event:
            self.send_input(event.data.get("text", ""))

    def notify_data_available(self) -> None:
        if self.state == SessionState.READY:
            self._try_consume_next()
