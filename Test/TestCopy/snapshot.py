"""Snapshot dump helpers for TestCopy."""

from __future__ import annotations

from pathlib import Path

from Test.TestCopy.model import CopyState
from Test.TestCopy.render import frame_to_plain_text


META_PATH = Path(__file__).resolve().parent / "latest_meta.txt"
FRAME_PATH = Path(__file__).resolve().parent / "latest_frame.txt"
COPY_PATH = Path(__file__).resolve().parent / "latest_copy.txt"


def dump_snapshot(state: CopyState, frame: list[list], last_input: str) -> None:
    selection = "-"
    if state.selection is not None:
        selection = (
            f"anchor=({state.selection.anchor_line_abs},{state.selection.anchor_col}) "
            f"cursor=({state.selection.cursor_line_abs},{state.selection.cursor_col})"
        )

    meta_lines = [
        f"last_input={last_input}",
        f"mode={state.mode}",
        f"viewport_top={state.viewport_top}",
        f"cursor=({state.cursor_line_abs},{state.cursor_col})",
        f"selection={selection}",
        f"query={state.search.query!r}",
        f"copied_len={len(state.copied_text)}",
        f"size={state.width}x{state.height}",
        f"viewport={state.viewport_top + 1}-{min(state.line_count, state.viewport_top + state.viewport_height)}/{state.line_count}",
    ]
    META_PATH.write_text("\n".join(meta_lines) + "\n", encoding="utf-8")
    FRAME_PATH.write_text(frame_to_plain_text(frame) + "\n", encoding="utf-8")
    COPY_PATH.write_text(state.copied_text, encoding="utf-8")
