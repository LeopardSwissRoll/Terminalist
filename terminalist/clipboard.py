"""Clipboard sink helpers.

Separated from copy-mode state so alternate sinks can be plugged in later for
Flow or remote workflows without changing copy logic.
"""

from __future__ import annotations

import subprocess


def copy_text(text: str) -> bool:
    """Copy text to the Windows clipboard via clip.exe.

    Returns False instead of raising so callers can keep an internal fallback.
    """
    if not text:
        return False
    try:
        proc = subprocess.run(
            ["clip.exe"],
            input=text,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return proc.returncode == 0
