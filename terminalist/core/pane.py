"""Pane — View wrapper around a TerminalSession.

Pane owns display-related state: position, size, focus, copy mode.
Session owns execution-related state: PTY, pyte screen, state machine.

Pane ≠ Session. A Pane is "where to display", Session is "what to run".
(Ref: pymux Pane wraps Terminal; tmux window_pane owns PTY+screen)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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
        self.rect = rect or Rect(0, 0, session._screen.columns, session._screen.lines)
        self.focused = False
        self._copy_mode = False
        self._scroll_offset = 0

        log("session", f"[pane:{pane_id}] created for session={session.session_id} rect={self.rect}")

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

    def set_rect(self, rect: Rect) -> None:
        """Update pane position/size. Propagates size to session if changed."""
        old = self.rect
        self.rect = rect
        if old.w != rect.w or old.h != rect.h:
            self.session.resize(cols=rect.w, rows=rect.h)
            log("session", f"[pane:{self.pane_id}] resized {old.w}x{old.h} → {rect.w}x{rect.h}")

    # ── Copy mode (placeholder for future) ──

    def enter_copy_mode(self) -> None:
        self._copy_mode = True
        self._scroll_offset = 0
        log("session", f"[pane:{self.pane_id}] enter copy mode")

    def exit_copy_mode(self) -> None:
        self._copy_mode = False
        self._scroll_offset = 0
        log("session", f"[pane:{self.pane_id}] exit copy mode")

    @property
    def in_copy_mode(self) -> bool:
        return self._copy_mode

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
