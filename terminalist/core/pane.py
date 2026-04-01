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
        self._copy_mode = False
        self._scroll_offset = 0

        log("session", f"[pane:{pane_id}] created for session={session.session_id} rect={self.content_rect}")

    @property
    def rect(self) -> Rect:
        """Backward-compatible alias for the PTY content rect."""
        return self.content_rect

    @rect.setter
    def rect(self, value: Rect) -> None:
        old_content = getattr(self, "content_rect", None)
        old_frame = getattr(self, "frame_rect", None)
        self.content_rect = value
        if old_content is None or old_frame is None or old_frame == old_content:
            self.frame_rect = value

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
        """Backward-compatible geometry update for legacy callers."""
        self.set_geometry(rect, rect)

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

    @property
    def scroll_offset(self) -> int:
        return self._scroll_offset

    def scroll_up(self, lines: int = 3) -> bool:
        max_offset = self.session.get_max_scroll_offset()
        if max_offset <= 0:
            return False
        new_offset = min(max_offset, self._scroll_offset + max(1, lines))
        if new_offset == self._scroll_offset:
            return False
        self._copy_mode = True
        self._scroll_offset = new_offset
        log("session", f"[pane:{self.pane_id}] scroll up -> offset={self._scroll_offset}")
        return True

    def scroll_down(self, lines: int = 3) -> bool:
        new_offset = max(0, self._scroll_offset - max(1, lines))
        if new_offset == self._scroll_offset:
            return False
        self._scroll_offset = new_offset
        if self._scroll_offset == 0:
            self._copy_mode = False
            log("session", f"[pane:{self.pane_id}] scroll down -> live")
        else:
            self._copy_mode = True
            log("session", f"[pane:{self.pane_id}] scroll down -> offset={self._scroll_offset}")
        return True

    def reset_scroll(self) -> None:
        if self._copy_mode or self._scroll_offset:
            self._copy_mode = False
            self._scroll_offset = 0
            log("session", f"[pane:{self.pane_id}] reset scroll")

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
