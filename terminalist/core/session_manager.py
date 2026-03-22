"""SessionManager — Session lifecycle management."""

from __future__ import annotations

import itertools
from pathlib import Path

from terminalist.events.tes import EventStreamManager
from .claude_session import ClaudeSession
from .codex_session import CodexSession
from .llm_session import LLMSession
from .terminal_session import SessionState, TerminalSession
from .shell_session import ShellSession


class SessionManager:
    """Create, manage, and destroy terminal sessions."""

    def __init__(self, event_stream: EventStreamManager) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._es = event_stream
        self._id_counter = itertools.count(1)

    def create(
        self,
        provider: str,
        session_id: str | None = None,
        workspace: str = ".",
        **kwargs,
    ) -> TerminalSession:
        """Create session + spawn + bind to TES.
        Auto-generates session_id if not provided."""
        if session_id is None:
            session_id = f"{provider}_{next(self._id_counter)}"
        if session_id in self._sessions:
            raise ValueError(f"Session '{session_id}' already exists")

        ws = Path(workspace).resolve()
        session: TerminalSession

        if provider == "claude":
            session = ClaudeSession(session_id, ws, **kwargs)
        elif provider == "codex":
            session = CodexSession(session_id, ws, **kwargs)
        elif provider in ("powershell", "cmd", "bash"):
            session = ShellSession(session_id, ws, shell_type=provider, **kwargs)
        else:
            raise ValueError(f"Unknown provider: {provider}")

        # Bind to TES + register GC consumer
        session.bind_event_stream(self._es)
        target_key = f"session:{session_id}"
        self._es.on_control(target_key, session._handle_control)
        self._es.on_data(
            target_key, lambda _e, s=session: s.notify_data_available()
        )
        self._es.register_consumer(session_id)

        # Spawn
        session.spawn()
        if isinstance(session, LLMSession):
            session.handle_startup()

        self._sessions[session_id] = session
        return session

    def destroy(self, session_id: str) -> None:
        """Kill session and clean up TES handlers + GC consumer."""
        session = self._sessions.pop(session_id, None)
        if session:
            target_key = f"session:{session_id}"
            self._es.remove_control(target_key)
            self._es.remove_data(target_key)
            self._es.unregister_consumer(session_id)
            session.kill()
            # GC after removing a consumer
            self._es.gc()

    def get(self, session_id: str) -> TerminalSession | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        return [
            {
                "id": sid,
                "type": type(s).__name__,
                "state": s.state.value,
                "workspace": str(s.workspace),
            }
            for sid, s in self._sessions.items()
        ]

    def restart(self, session_id: str) -> TerminalSession:
        """Restart a DEAD session. LLM sessions use resume_id if available."""
        session = self._sessions.get(session_id)
        if not session or session.state != SessionState.DEAD:
            raise ValueError(f"Session '{session_id}' is not DEAD")

        # Rebuild command with resume_id for Claude
        if isinstance(session, ClaudeSession) and session.resume_id:
            session.cmd = ClaudeSession._build_cmd(
                session.model,
                session.effort,
                session.permission,
                session.prompt_file,
                session.add_dirs,
                session.resume_id,
            )

        session.spawn()
        if isinstance(session, LLMSession):
            session.handle_startup()
        return session
