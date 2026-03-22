"""CodexSession — OpenAI Codex CLI session."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .llm_session import LLMSession


class CodexSession(LLMSession):
    # Command-ready: line contains only › (with optional whitespace)
    _CMD_READY_RE = re.compile(r"^\s*›\s*$")

    def __init__(
        self,
        session_id: str,
        workspace: Path,
        *,
        model: str = "gpt-5.4",
        effort: str = "xhigh",
        add_dirs: list[str] | None = None,
        codex_home: str | None = None,
        env: dict[str, str] | None = None,
        cols: int = 120,
        rows: int = 40,
    ) -> None:
        cmd = ["codex", "--no-alt-screen"]
        for d in add_dirs or []:
            cmd += ["--add-dir", d]
        # CODEX_HOME: force ASCII path (v2 Korean path bug)
        session_env = dict(env or {})
        if codex_home:
            ascii_home = str(codex_home).encode("ascii", "replace").decode()
            session_env["CODEX_HOME"] = ascii_home
        super().__init__(
            session_id, cmd, workspace, env=session_env, cols=cols, rows=rows
        )
        self.model = model
        self.effort = effort
        self.add_dirs = add_dirs or []
        self.codex_home = codex_home

    def detect_ready(self, lines: list[str]) -> bool:
        """'OpenAI Codex' banner + › prompt both present."""
        joined = "\n".join(lines)
        has_banner = "OpenAI Codex" in joined
        has_prompt = any(self._CMD_READY_RE.match(line) for line in lines[-5:])
        return has_banner and has_prompt

    def detect_command_ready(self, lines: list[str]) -> bool:
        """After internal command: only › needed (no banner check)."""
        return any(self._CMD_READY_RE.match(line) for line in lines[-5:])

    def extract_response(self, lines: list[str]) -> str:
        # TODO: Running/Ran block processing
        result_lines: list[str] = []
        for line in lines:
            stripped = line.rstrip()
            if stripped and not self._CMD_READY_RE.match(line):
                result_lines.append(stripped)
        return "\n".join(result_lines)

    def handle_startup(self) -> None:
        # Codex has no trust prompt
        pass

    def detect_interaction(self, lines: list[str]) -> dict[str, Any] | None:
        return None

    def capture_resume_id(self, lines: list[str]) -> str | None:
        return None
