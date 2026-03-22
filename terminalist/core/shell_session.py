"""ShellSession — Generic shell (PowerShell, CMD, bash)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from terminalist.debug import log
from .terminal_session import SessionState, TerminalSession


class ShellSession(TerminalSession):
    """General-purpose shell session."""

    PROMPTS = {
        "powershell": re.compile(r"^PS (?P<cwd>.+)>\s*$"),  # PS C:\path>
        "cmd": re.compile(r"^(?P<cwd>[A-Za-z]:\\.*)>\s*$"),  # C:\path>
        "bash": re.compile(r"^(?:.*?[:\s])?(?P<cwd>(?:~|/)\S*)\$\s*$"),
    }

    CMD_MAP = {
        "powershell": ["powershell.exe", "-NoLogo"],
        "cmd": ["cmd.exe"],
        "bash": ["bash"],
    }

    def __init__(
        self,
        session_id: str,
        workspace: Path,
        shell_type: str = "powershell",
        env: dict[str, str] | None = None,
        cols: int = 120,
        rows: int = 40,
    ) -> None:
        cmd = self.CMD_MAP.get(shell_type)
        if cmd is None:
            raise ValueError(f"Unknown shell type: {shell_type}")
        super().__init__(
            session_id, list(cmd), workspace, env=env, cols=cols, rows=rows
        )
        self.shell_type = shell_type
        self._prompt_re = self.PROMPTS[shell_type]
        self.current_dir = workspace

    def _exit_command(self) -> str | None:
        """Shell exit: 'exit' works for PowerShell, CMD, and bash."""
        return "exit"

    def _normalize_cwd(self, cwd: str) -> Path | None:
        if re.match(r"^[A-Za-z]:\\", cwd):
            return Path(cwd)
        if cwd.startswith("~/"):
            return Path.home() / cwd[2:].replace("/", os.sep)
        match = re.match(r"^/([A-Za-z])/(.*)$", cwd)
        if match:
            drive, tail = match.groups()
            return Path(f"{drive.upper()}:\\{tail.replace('/', '\\')}")
        return None

    def get_split_workspace(self) -> Path:
        return self.current_dir

    def _update_current_dir(self, prompt_line: str) -> None:
        match = self._prompt_re.match(prompt_line)
        if not match:
            return
        cwd = match.groupdict().get("cwd")
        if not cwd:
            return
        normalized = self._normalize_cwd(cwd)
        if normalized is not None:
            if normalized != self.current_dir:
                log(
                    "session",
                    f"[{self.session_id}] cwd update {self.current_dir} -> {normalized}",
                )
            self.current_dir = normalized

    _DETECT_TAIL = 5

    def _check_state_transition(self) -> None:
        if self.state == SessionState.MANUAL:
            return
        tail = self.get_display_tail(self._DETECT_TAIL)
        # Check last non-empty line for prompt pattern
        for line in reversed(tail):
            stripped = line.rstrip()
            if stripped:
                log(
                    "session",
                    f"[{self.session_id}] prompt probe shell={self.shell_type} line={stripped!r}",
                )
                if self._prompt_re.match(stripped):
                    self._update_current_dir(stripped)
                    if self.state in (SessionState.STARTING, SessionState.BUSY):
                        self._set_state(SessionState.READY)
                break
