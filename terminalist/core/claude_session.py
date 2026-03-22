"""ClaudeSession — Claude Code CLI session."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .llm_session import LLMSession


class ClaudeSession(LLMSession):
    # Ready: line contains ONLY ❯ or > (with optional whitespace)
    # "❯" → ready, "> " → ready, "❯ some text" → NOT ready
    _READY_RE = re.compile(r"^\s*[❯>]\s*$")

    # Resume ID: "session: UUID" pattern
    _RESUME_RE = re.compile(r"session:\s*([0-9a-f-]{36})", re.IGNORECASE)

    def __init__(
        self,
        session_id: str,
        workspace: Path,
        *,
        model: str = "opus",
        effort: str = "high",
        permission: str = "bypass",
        prompt_file: str | None = None,
        add_dirs: list[str] | None = None,
        resume_id: str | None = None,
        env: dict[str, str] | None = None,
        cols: int = 120,
        rows: int = 40,
    ) -> None:
        cmd = self._build_cmd(
            model, effort, permission, prompt_file, add_dirs, resume_id
        )
        super().__init__(session_id, cmd, workspace, env=env, cols=cols, rows=rows)
        self.model = model
        self.effort = effort
        self.permission = permission
        self.prompt_file = prompt_file
        self.add_dirs = add_dirs or []
        self.resume_id = resume_id

    @staticmethod
    def _build_cmd(
        model: str,
        effort: str,
        permission: str,
        prompt_file: str | None,
        add_dirs: list[str] | None,
        resume_id: str | None,
    ) -> list[str]:
        cmd = ["claude", "--verbose", "--model", model, "--effort", effort]
        if permission == "bypass":
            cmd += ["--permission-mode", "bypassPermissions"]
        if prompt_file:
            cmd += ["--append-system-prompt-file", prompt_file]
        for d in add_dirs or []:
            cmd += ["--add-dir", d]
        if resume_id:
            cmd += ["--resume", resume_id]
        return cmd

    def detect_ready(self, lines: list[str]) -> bool:
        return any(self._READY_RE.match(line) for line in lines[-5:])

    def detect_command_ready(self, lines: list[str]) -> bool:
        # Claude: same as detect_ready
        return self.detect_ready(lines)

    def extract_response(self, lines: list[str]) -> str:
        # TODO: ● marker detection, context echo removal, tool block collapsing
        # For now, return non-empty lines between prompts
        result_lines: list[str] = []
        for line in lines:
            stripped = line.rstrip()
            if stripped and not self._READY_RE.match(line):
                result_lines.append(stripped)
        return "\n".join(result_lines)

    def handle_startup(self) -> None:
        # TODO: detect trust prompt → auto-accept ('y' + Enter)
        pass

    def detect_interaction(self, lines: list[str]) -> dict[str, Any] | None:
        # TODO: detect permission request prompts
        return None

    def _exit_command(self) -> str | None:
        return "/exit"

    def capture_resume_id(self, lines: list[str]) -> str | None:
        for line in lines:
            m = self._RESUME_RE.search(line)
            if m:
                return m.group(1)
        return None
