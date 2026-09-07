"""Pure copy-mode state machine for pane/local text exploration.

This module intentionally depends only on plain Python data structures so it
can be reused by Terminalist panes today and Flow-style text sources later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Mode = Literal["live", "copy", "search"]
Match = tuple[int, int, int]


@dataclass(frozen=True)
class Cursor:
    line_abs: int
    col: int


@dataclass(frozen=True)
class Viewport:
    top: int
    height: int


@dataclass
class Selection:
    anchor_line_abs: int
    anchor_col: int
    cursor_line_abs: int
    cursor_col: int

    def ordered_bounds(self) -> tuple[tuple[int, int], tuple[int, int]]:
        start = (self.anchor_line_abs, self.anchor_col)
        end = (self.cursor_line_abs, self.cursor_col)
        if start <= end:
            return start, end
        return end, start


@dataclass
class SearchState:
    query: str = ""
    matches: list[Match] = field(default_factory=list)
    active_match_idx: int | None = None


@dataclass
class CopyState:
    lines: list[str]
    width: int
    height: int
    mode: Mode = "live"
    viewport_top: int = 0
    cursor_line_abs: int = 0
    cursor_col: int = 0
    selection: Selection | None = None
    search: SearchState = field(default_factory=SearchState)
    copied_text: str = ""

    @classmethod
    def create(cls, lines: list[str], width: int, height: int) -> CopyState:
        state = cls(lines=list(lines), width=width, height=height)
        state.viewport_top = state.live_tail_top
        state._reset_cursor_to_tail()
        return state

    @property
    def viewport_height(self) -> int:
        return max(1, self.height)

    @property
    def line_count(self) -> int:
        return len(self.lines)

    @property
    def max_viewport_top(self) -> int:
        return max(0, self.line_count - self.viewport_height)

    @property
    def live_tail_top(self) -> int:
        return self.max_viewport_top

    @property
    def scroll_offset(self) -> int:
        return max(0, self.live_tail_top - self.viewport_top)

    @property
    def cursor(self) -> Cursor:
        return Cursor(self.cursor_line_abs, self.cursor_col)

    @property
    def viewport(self) -> Viewport:
        return Viewport(self.viewport_top, self.viewport_height)

    def visible_lines(self) -> list[str]:
        end = self.viewport_top + self.viewport_height
        visible = self.lines[self.viewport_top:end]
        if len(visible) < self.viewport_height:
            visible.extend("" for _ in range(self.viewport_height - len(visible)))
        return visible

    def sync_content(self, lines: list[str], width: int, height: int) -> None:
        current_match_key = current_match(self)
        self.lines = list(lines)
        self.width = width
        self.height = height

        if self.mode == "live":
            self.viewport_top = self.live_tail_top
            self._reset_cursor_to_tail()
            return

        self.viewport_top = _clamp(self.viewport_top, 0, self.max_viewport_top)

        if self.line_count <= 0:
            self.cursor_line_abs = 0
            self.cursor_col = 0
            self.selection = None
            self.search.matches = []
            self.search.active_match_idx = None
            return

        self.cursor_line_abs = _clamp(self.cursor_line_abs, 0, self.line_count - 1)
        self.cursor_col = _clamp(self.cursor_col, 0, self._line_cursor_limit_col(self.cursor_line_abs))

        if self.selection is not None:
            self.selection.anchor_line_abs = _clamp(self.selection.anchor_line_abs, 0, self.line_count - 1)
            self.selection.cursor_line_abs = _clamp(self.selection.cursor_line_abs, 0, self.line_count - 1)
            self.selection.anchor_col = _clamp(
                self.selection.anchor_col,
                0,
                self._line_cursor_limit_col(self.selection.anchor_line_abs),
            )
            self.selection.cursor_col = _clamp(
                self.selection.cursor_col,
                0,
                self._line_cursor_limit_col(self.selection.cursor_line_abs),
            )

        if self.search.query:
            self.search.matches = _find_matches(self.lines, self.search.query)
            if current_match_key in self.search.matches:
                self.search.active_match_idx = self.search.matches.index(current_match_key)
            else:
                self.search.active_match_idx = None
        else:
            self.search.matches = []
            self.search.active_match_idx = None

        self._sync_selection_to_cursor()

    def enter_copy_mode(self) -> None:
        self.mode = "copy"
        self.selection = None
        self.search = SearchState()
        self.viewport_top = min(self.viewport_top, self.live_tail_top)
        self._reset_cursor_to_tail()

    def exit_to_live(self) -> None:
        self.mode = "live"
        self.viewport_top = self.live_tail_top
        self.selection = None
        self.search = SearchState()
        self._reset_cursor_to_tail()

    def scroll_up_history(self, lines: int = 3) -> bool:
        if self.mode == "live":
            self.enter_copy_mode()
        new_top = max(0, self.viewport_top - max(1, lines))
        if new_top == self.viewport_top:
            return False
        self.viewport_top = new_top
        return True

    def scroll_down_history(self, lines: int = 3) -> bool:
        if self.mode == "live":
            return False
        new_top = min(self.live_tail_top, self.viewport_top + max(1, lines))
        if new_top == self.viewport_top:
            if new_top == self.live_tail_top:
                self.exit_to_live()
            return False
        self.viewport_top = new_top
        if self.viewport_top >= self.live_tail_top:
            self.exit_to_live()
        return True

    def move_cursor(self, dx: int = 0, dy: int = 0) -> bool:
        if self.mode not in {"copy", "search"} or self.line_count <= 0:
            return False
        old = (self.cursor_line_abs, self.cursor_col)
        self.cursor_line_abs = _clamp(self.cursor_line_abs + dy, 0, max(0, self.line_count - 1))
        self.cursor_col = _clamp(self.cursor_col + dx, 0, self._line_cursor_limit_col(self.cursor_line_abs))
        self._ensure_cursor_visible()
        self._sync_selection_to_cursor()
        return old != (self.cursor_line_abs, self.cursor_col)

    def move_home(self) -> bool:
        if self.mode not in {"copy", "search"}:
            return False
        if self.cursor_col == 0:
            return False
        self.cursor_col = 0
        self._sync_selection_to_cursor()
        return True

    def move_end(self) -> bool:
        if self.mode not in {"copy", "search"}:
            return False
        new_col = self._line_cursor_limit_col(self.cursor_line_abs)
        if new_col == self.cursor_col:
            return False
        self.cursor_col = new_col
        self._sync_selection_to_cursor()
        return True

    def page_up(self) -> bool:
        return self._page_move(-1)

    def page_down(self) -> bool:
        return self._page_move(1)

    def start_selection(self) -> None:
        self.selection = Selection(
            self.cursor_line_abs,
            self.cursor_col,
            self.cursor_line_abs,
            self.cursor_col,
        )

    def enter_search_prompt(self) -> None:
        if self.mode == "live":
            self.enter_copy_mode()
        self.mode = "search"
        self.search = SearchState()

    def append_search_text(self, text: str) -> None:
        if self.mode == "search":
            self.search.query += text

    def backspace_search_text(self) -> None:
        if self.mode == "search" and self.search.query:
            self.search.query = self.search.query[:-1]

    def confirm_search(self) -> bool:
        query = self.search.query
        matches = _find_matches(self.lines, query)
        self.mode = "copy"
        self.search.matches = matches
        self.search.active_match_idx = None
        if not matches:
            return False

        # v1 intentionally does not wrap. Only later matches are considered.
        for idx, (line_abs, col_start, _col_end) in enumerate(matches):
            if line_abs > self.cursor_line_abs or (
                line_abs == self.cursor_line_abs and col_start > self.cursor_col
            ):
                self._activate_match(idx)
                return True
        return False

    def cancel_search(self) -> None:
        if self.mode == "search":
            self.mode = "copy"

    def next_match(self) -> bool:
        if self.search.active_match_idx is None:
            return False
        new_idx = self.search.active_match_idx + 1
        if new_idx >= len(self.search.matches):
            return False
        self._activate_match(new_idx)
        return True

    def prev_match(self) -> bool:
        if self.search.active_match_idx is None:
            return False
        new_idx = self.search.active_match_idx - 1
        if new_idx < 0:
            return False
        self._activate_match(new_idx)
        return True

    def copy_selection(self) -> bool:
        text = extract_selection_text(self)
        if not text:
            return False
        self.copied_text = text
        self.exit_to_live()
        return True

    def _page_move(self, direction: int) -> bool:
        if self.mode not in {"copy", "search"} or self.line_count <= 0:
            return False
        old_top = self.viewport_top
        relative_row = self.cursor_line_abs - self.viewport_top
        self.viewport_top = _clamp(
            self.viewport_top + direction * self.viewport_height,
            0,
            self.max_viewport_top,
        )
        if self.viewport_top == old_top:
            return False
        target_line = min(
            max(0, self.line_count - 1),
            self.viewport_top + min(relative_row, self.viewport_height - 1),
        )
        self.cursor_line_abs = target_line
        self.cursor_col = min(self.cursor_col, self._line_cursor_limit_col(self.cursor_line_abs))
        self._sync_selection_to_cursor()
        return True

    def _activate_match(self, idx: int) -> None:
        line_abs, col_start, _col_end = self.search.matches[idx]
        self.search.active_match_idx = idx
        self.cursor_line_abs = line_abs
        self.cursor_col = col_start
        self._ensure_cursor_visible()
        self._sync_selection_to_cursor()

    def _ensure_cursor_visible(self) -> None:
        if self.cursor_line_abs < self.viewport_top:
            self.viewport_top = self.cursor_line_abs
        bottom = self.viewport_top + self.viewport_height - 1
        if self.cursor_line_abs > bottom:
            self.viewport_top = self.cursor_line_abs - (self.viewport_height - 1)
        self.viewport_top = _clamp(self.viewport_top, 0, self.max_viewport_top)

    def _line_end_col(self, line_abs: int) -> int:
        if not self.lines:
            return -1
        line = self.lines[_clamp(line_abs, 0, self.line_count - 1)]
        return len(line) - 1

    def _line_cursor_limit_col(self, line_abs: int) -> int:
        return max(0, self._line_end_col(line_abs))

    def _reset_cursor_to_tail(self) -> None:
        visible = self.visible_lines()
        for rel in range(len(visible) - 1, -1, -1):
            line = visible[rel]
            if line:
                self.cursor_line_abs = self.viewport_top + rel
                self.cursor_col = len(line) - 1
                return
        fallback = self.viewport_top + len(visible) - 1
        if self.line_count > 0:
            self.cursor_line_abs = min(max(0, self.line_count - 1), fallback)
        else:
            self.cursor_line_abs = 0
        self.cursor_col = 0

    def _sync_selection_to_cursor(self) -> None:
        if self.selection is not None:
            self.selection.cursor_line_abs = self.cursor_line_abs
            self.selection.cursor_col = self.cursor_col


def handle_named_key(state: CopyState, key: str) -> None:
    if key == "copy_mode":
        state.enter_copy_mode()
        return

    if state.mode == "live":
        return

    if state.mode == "search":
        if key == "esc":
            state.cancel_search()
        elif key == "enter":
            state.confirm_search()
        elif key == "backspace":
            state.backspace_search_text()
        return

    if key == "esc":
        state.exit_to_live()
    elif key == "left":
        state.move_cursor(dx=-1)
    elif key == "right":
        state.move_cursor(dx=1)
    elif key == "up":
        state.move_cursor(dy=-1)
    elif key == "down":
        state.move_cursor(dy=1)
    elif key == "page_up":
        state.page_up()
    elif key == "page_down":
        state.page_down()
    elif key == "home":
        state.move_home()
    elif key == "end":
        state.move_end()
    elif key == "space":
        state.start_selection()
    elif key == "enter":
        state.copy_selection()
    elif key == "search":
        state.enter_search_prompt()
    elif key == "next_match":
        state.next_match()
    elif key == "prev_match":
        state.prev_match()


def handle_text_input(state: CopyState, text: str) -> None:
    if state.mode == "search":
        state.append_search_text(text)


def handle_wheel(state: CopyState, direction: Literal["up", "down"]) -> None:
    if direction == "up":
        state.scroll_up_history()
    else:
        state.scroll_down_history()


def extract_selection_text(state: CopyState) -> str:
    if state.selection is None or not state.lines:
        return ""

    (start_line, start_col), (end_line, end_col) = state.selection.ordered_bounds()
    parts: list[str] = []
    for line_abs in range(start_line, end_line + 1):
        line = state.lines[line_abs]
        if start_line == end_line:
            text = line[start_col:end_col + 1]
        elif line_abs == start_line:
            text = line[start_col:]
        elif line_abs == end_line:
            text = line[:end_col + 1]
        else:
            text = line
        parts.append(text.rstrip())

    return "\n".join(parts).rstrip("\n")


def current_match(state: CopyState) -> Match | None:
    idx = state.search.active_match_idx
    if idx is None or not (0 <= idx < len(state.search.matches)):
        return None
    return state.search.matches[idx]


def _find_matches(lines: list[str], query: str) -> list[Match]:
    if not query:
        return []
    matches: list[Match] = []
    for line_abs, line in enumerate(lines):
        start = 0
        while start <= len(line) - len(query):
            pos = line.find(query, start)
            if pos < 0:
                break
            matches.append((line_abs, pos, pos + len(query) - 1))
            start = pos + 1
    return matches


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
