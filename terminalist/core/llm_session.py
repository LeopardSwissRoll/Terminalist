"""LLMSession — Abstract base for LLM CLI sessions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from terminalist.events.event import Channel
from .terminal_session import SessionState, TerminalSession


class LLMSession(TerminalSession, ABC):
    """LLM CLI session with ready detection, response extraction, and resume."""

    def __init__(
        self,
        session_id: str,
        cmd: list[str],
        workspace: Path,
        env: dict[str, str] | None = None,
        cols: int = 120,
        rows: int = 40,
    ) -> None:
        super().__init__(session_id, cmd, workspace, env=env, cols=cols, rows=rows)
        self.resume_id: str | None = None
        self._last_cause_id: int | None = None

    # ── Abstract methods ──

    @abstractmethod
    def detect_ready(self, lines: list[str]) -> bool:
        """Detect whether CLI is at input prompt.
        Claude: line contains only ❯ or > (no trailing text)
        Codex: 'OpenAI Codex' banner + › prompt both present"""

    @abstractmethod
    def detect_command_ready(self, lines: list[str]) -> bool:
        """Detect prompt return after internal command execution.
        Claude: same as detect_ready
        Codex: only check for › (no banner needed)"""

    @abstractmethod
    def extract_response(self, lines: list[str]) -> str:
        """Extract LLM response text from screen."""

    @abstractmethod
    def handle_startup(self) -> None:
        """Post-spawn handling (trust prompt, etc.)."""

    @abstractmethod
    def detect_interaction(self, lines: list[str]) -> dict[str, Any] | None:
        """Detect interactive prompts (permission requests, etc.)."""

    @abstractmethod
    def capture_resume_id(self, lines: list[str]) -> str | None:
        """Extract resume/session ID from response.
        Claude: extract UUID from 'session: UUID' pattern
        Codex: N/A → None"""

    # ── State transition ──

    def _check_state_transition(self) -> None:
        """Detect state transitions based on pyte screen content."""
        if self.state == SessionState.MANUAL:
            return

        lines = self.get_display()

        # Detect interactive prompts → publish to TES
        interaction = self.detect_interaction(lines)
        if interaction and self._event_stream:
            self._event_stream.publish(
                Channel.STATE,
                "interaction",
                f"session:{self.session_id}",
                None,
                interaction,
            )

        # STARTING: use detect_ready (full check, e.g. Codex needs banner+prompt)
        # BUSY: use detect_command_ready (lighter check, e.g. Codex only needs prompt)
        is_ready = False
        if self.state == SessionState.STARTING:
            is_ready = self.detect_ready(lines)
        elif self.state == SessionState.BUSY:
            is_ready = self.detect_command_ready(lines)

        if is_ready:
            if self.state in (SessionState.STARTING, SessionState.BUSY):
                # On BUSY→READY: extract response and publish output
                if self.state == SessionState.BUSY:
                    response = self.extract_response(lines)
                    if response and self._event_stream:
                        self._event_stream.publish(
                            Channel.DATA,
                            "output",
                            f"session:{self.session_id}",
                            None,
                            {"text": response},
                            cause_id=self._last_cause_id,
                        )
                    # Capture resume_id
                    rid = self.capture_resume_id(lines)
                    if rid:
                        self.resume_id = rid

                # _set_state(READY) will trigger _try_consume_next
                self._set_state(SessionState.READY)

    def _try_consume_next(self) -> None:
        """Consume next Data event, tracking cause_id."""
        event = self.consume_next_data()
        if event:
            self._last_cause_id = event.id
            self.send_input(event.data.get("text", ""))
