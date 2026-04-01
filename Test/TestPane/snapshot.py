"""Snapshot dump helpers for TestPane."""

from __future__ import annotations

from pathlib import Path

from Test.TestPane.layout import collect_leaves
from Test.TestPane.render import frame_to_plain_text


META_PATH = Path(__file__).resolve().parent / "latest_meta.txt"
FRAME_PATH = Path(__file__).resolve().parent / "latest_frame.txt"


def dump_snapshot(state, frame: list[list], last_input: str) -> None:
    leaves = collect_leaves(state.root)
    meta_lines = [
        f"last_input={last_input}",
        f"focused={state.focused_id or '-'}",
        f"size={state.width}x{state.height}",
        f"focus_history={' -> '.join(state.focus_history) if state.focus_history else '-'}",
        "panes:",
    ]
    for pane in leaves:
        rect = pane.rect
        meta_lines.append(
            f"  {pane.pane_id}: rect=({rect.x},{rect.y},{rect.w},{rect.h}) label={pane.label}"
        )

    META_PATH.write_text("\n".join(meta_lines) + "\n", encoding="utf-8")
    FRAME_PATH.write_text(frame_to_plain_text(frame) + "\n", encoding="utf-8")
