"""Pane — View wrapper around a TerminalSession.

Pane owns display-related state: position, size, focus, copy mode.
Session owns execution-related state: PTY, pyte screen, state machine.

Pane ≠ Session. A Pane is "where to display", Session is "what to run".
(Ref: pymux Pane wraps Terminal; tmux window_pane owns PTY+screen)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from terminalist.core.copy_mode import CopyState
from terminalist.debug import log

if TYPE_CHECKING:
    from .terminal_session import TerminalSession


@dataclass
class Rect:
    """Rectangular region in terminal cells."""
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w - 1

    @property
    def bottom(self) -> int:
        return self.y + self.h - 1

    @property
    def center_x(self) -> float:
        return self.x + (self.w - 1) / 2

    @property
    def center_y(self) -> float:
        return self.y + (self.h - 1) / 2


class Pane:
    """A view into a TerminalSession, placed at a Rect on screen."""

    def __init__(
        self,
        pane_id: str,
        session: TerminalSession,
        rect: Rect | None = None,
    ) -> None:
        self.pane_id = pane_id
        self.session = session
        base_rect = rect or Rect(0, 0, session._screen.columns, session._screen.lines)
        self.frame_rect = base_rect
        self.content_rect = base_rect
        self.focused = False
        self._copy_state: CopyState | None = None

        log("session", f"[pane:{pane_id}] created for session={session.session_id} rect={self.content_rect}")

    # ── Focus ──

    def focus(self) -> None:
        if not self.focused:
            self.focused = True
            self.session.enter_manual()
            log("focus", f"[pane:{self.pane_id}] focused")

    def blur(self) -> None:
        if self.focused:
            self.focused = False
            self.session.exit_manual()
            log("focus", f"[pane:{self.pane_id}] blurred")

    # ── Resize ──

    def set_geometry(self, frame_rect: Rect, content_rect: Rect) -> None:
        """Update visual frame + PTY content geometry.

        PTY resize is driven only by the content rect.
        """
        old = self.content_rect
        self.frame_rect = frame_rect
        self.content_rect = content_rect
        if old.w != content_rect.w or old.h != content_rect.h:
            self.session.resize(cols=content_rect.w, rows=content_rect.h)
            log(
                "session",
                f"[pane:{self.pane_id}] resized {old.w}x{old.h} → {content_rect.w}x{content_rect.h}",
            )
        self.sync_copy_mode()

    # ── Copy mode ──

    def enter_copy_mode(self) -> None:
        state = self._ensure_copy_state()
        state.enter_copy_mode()
        log("session", f"[pane:{self.pane_id}] enter copy mode")

    def exit_copy_mode(self) -> None:
        if self._copy_state is not None:
            self._copy_state.exit_to_live()
        log("session", f"[pane:{self.pane_id}] exit copy mode")

    @property
    def in_copy_mode(self) -> bool:
        return self._copy_state is not None and self._copy_state.mode != "live"

    @property
    def scroll_offset(self) -> int:
        if self._copy_state is None:
            return 0
        return self._copy_state.scroll_offset

    @property
    def copied_text(self) -> str:
        if self._copy_state is None:
            return ""
        return self._copy_state.copied_text

    @property
    def copy_mode_state(self) -> CopyState | None:
        return self._copy_state

    def scroll_up(self, lines: int = 3) -> bool:
        state = self._ensure_copy_state()
        if state.live_tail_top <= 0:
            return False
        old_offset = state.scroll_offset
        state.scroll_up_history(lines)
        if state.scroll_offset == old_offset:
            return False
        log("session", f"[pane:{self.pane_id}] scroll up -> offset={state.scroll_offset}")
        return True

    def scroll_down(self, lines: int = 3) -> bool:
        if self._copy_state is None:
            return False
        old_offset = self._copy_state.scroll_offset
        self._copy_state.scroll_down_history(lines)
        if self._copy_state.scroll_offset == old_offset:
            if self._copy_state.mode == "live":
                log("session", f"[pane:{self.pane_id}] scroll down -> live")
            return False
        if self._copy_state.mode == "live":
            log("session", f"[pane:{self.pane_id}] scroll down -> live")
        else:
            log("session", f"[pane:{self.pane_id}] scroll down -> offset={self._copy_state.scroll_offset}")
        return True

    def reset_scroll(self) -> None:
        if self._copy_state is not None and (self._copy_state.mode != "live" or self._copy_state.scroll_offset):
            self._copy_state.exit_to_live()
            log("session", f"[pane:{self.pane_id}] reset scroll")

    def sync_copy_mode(self) -> None:
        if self._copy_state is None:
            return
        self._copy_state.sync_content(
            self.session.get_scrollback_lines(),
            self.content_rect.w,
            self.content_rect.h,
        )

    def copy_cursor_position(self) -> tuple[int, int] | None:
        self.sync_copy_mode()
        if self._copy_state is None or self._copy_state.mode == "live":
            return None
        row = self._copy_state.cursor_line_abs - self._copy_state.viewport_top
        if not (0 <= row < self._copy_state.viewport_height):
            return None
        return self._copy_state.cursor_col, row

    def _ensure_copy_state(self) -> CopyState:
        if self._copy_state is None:
            self._copy_state = CopyState.create(
                self.session.get_scrollback_lines(),
                self.content_rect.w,
                self.content_rect.h,
            )
        else:
            self.sync_copy_mode()
        return self._copy_state

    # ── Display delegation ──

    def get_display(self) -> list[str]:
        """Get session screen content."""
        return self.session.get_display()

    def get_cursor(self) -> tuple[int, int]:
        """Get cursor position (x, y) from session."""
        return self.session.get_cursor_position()

    def write_raw(self, data: str) -> None:
        """Forward raw input to session PTY."""
        self.session.write_raw(data)
