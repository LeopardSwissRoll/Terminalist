"""Rendering helpers for TestCopy."""

from __future__ import annotations

from dataclasses import dataclass

from Test.TestCopy.model import CopyState, current_match


@dataclass(frozen=True)
class RenderCell:
    ch: str
    style: str


STYLE_TO_ANSI = {
    "normal": "\x1b[0m",
    "selection": "\x1b[30;103m",
    "search_hit": "\x1b[30;106m",
    "cursor": "\x1b[30;102m",
    "cursor_selection": "\x1b[30;105m",
    "status": "\x1b[30;100m",
}


def compose(state: CopyState) -> list[list[RenderCell]]:
    frame = [
        [RenderCell(" ", "normal") for _ in range(state.width)]
        for _ in range(state.height)
    ]

    visible = state.visible_lines()
    active_match = current_match(state)
    for row_idx, line in enumerate(visible):
        if row_idx >= state.viewport_height:
            break
        for col, ch in enumerate(line[:state.width]):
            frame[row_idx][col] = RenderCell(ch, "normal")

        if active_match is not None:
            _apply_match_highlight(frame, state, row_idx, active_match)
        _apply_selection_highlight(frame, state, row_idx)
        _apply_cursor(frame, state, row_idx)

    _render_status_line(frame[-1], state)
    return frame


def frame_to_plain_text(frame: list[list[RenderCell]]) -> str:
    return "\n".join("".join(cell.ch for cell in row) for row in frame)


def frame_to_ansi(frame: list[list[RenderCell]]) -> str:
    parts = ["\x1b[H"]
    current_style = "normal"
    parts.append(STYLE_TO_ANSI[current_style])
    for row in frame:
        for cell in row:
            if cell.style != current_style:
                current_style = cell.style
                parts.append(STYLE_TO_ANSI[current_style])
            parts.append(cell.ch)
        parts.append("\x1b[0m\n")
        current_style = "normal"
        parts.append(STYLE_TO_ANSI[current_style])
    parts.append("\x1b[0m")
    return "".join(parts)


def _apply_match_highlight(
    frame: list[list[RenderCell]],
    state: CopyState,
    row_idx: int,
    match: tuple[int, int, int],
) -> None:
    line_abs, start_col, end_col = match
    if line_abs != state.viewport_top + row_idx:
        return
    for col in range(start_col, min(end_col, state.width - 1) + 1):
        cell = frame[row_idx][col]
        frame[row_idx][col] = RenderCell(cell.ch, "search_hit")


def _apply_selection_highlight(
    frame: list[list[RenderCell]],
    state: CopyState,
    row_idx: int,
) -> None:
    if state.selection is None:
        return

    line_abs = state.viewport_top + row_idx
    start, end = state.selection.ordered_bounds()
    start_line, start_col = start
    end_line, end_col = end
    if not (start_line <= line_abs <= end_line):
        return

    if start_line == end_line:
        col_start, col_end = start_col, end_col
    elif line_abs == start_line:
        col_start, col_end = start_col, state.width - 1
    elif line_abs == end_line:
        col_start, col_end = 0, end_col
    else:
        col_start, col_end = 0, state.width - 1

    for col in range(max(0, col_start), min(state.width - 1, col_end) + 1):
        cell = frame[row_idx][col]
        frame[row_idx][col] = RenderCell(cell.ch, "selection")


def _apply_cursor(frame: list[list[RenderCell]], state: CopyState, row_idx: int) -> None:
    if state.mode == "live":
        return
    line_abs = state.viewport_top + row_idx
    if line_abs != state.cursor_line_abs:
        return
    if not (0 <= state.cursor_col < state.width):
        return
    cell = frame[row_idx][state.cursor_col]
    style = "cursor_selection" if cell.style == "selection" else "cursor"
    frame[row_idx][state.cursor_col] = RenderCell(cell.ch, style)


def _render_status_line(row: list[RenderCell], state: CopyState) -> None:
    total = state.line_count
    start = state.viewport_top + 1 if total else 0
    end = min(total, state.viewport_top + state.viewport_height)
    selection = "yes" if state.selection is not None else "no"
    status = (
        f" {state.mode.upper()} "
        f"{start}-{end}/{total} "
        f"L{state.cursor_line_abs + 1} C{state.cursor_col + 1} "
        f"sel={selection} "
        f"q={state.search.query!r} "
        f"copied={len(state.copied_text)} "
    )
    padded = status[: len(row)].ljust(len(row))
    for idx, ch in enumerate(padded):
        row[idx] = RenderCell(ch, "status")
