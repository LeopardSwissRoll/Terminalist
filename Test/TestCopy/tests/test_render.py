from Test.TestCopy.model import CopyState, handle_named_key, handle_text_input
from Test.TestCopy.render import compose


def _copy_state(lines: list[str]) -> CopyState:
    state = CopyState.create(lines, 30, 6)
    handle_named_key(state, "copy_mode")
    return state


def test_cursor_highlight():
    state = _copy_state(["alpha"])
    state.cursor_line_abs = 0
    state.cursor_col = 1
    frame = compose(state)
    assert frame[0][1].style == "cursor"


def test_selection_highlight():
    state = _copy_state(["alpha"])
    state.cursor_line_abs = 0
    state.cursor_col = 1
    handle_named_key(state, "space")
    state.move_cursor(dx=2)
    frame = compose(state)
    assert frame[0][1].style == "selection"
    assert frame[0][3].style == "cursor_selection"


def test_search_hit_highlight():
    state = _copy_state(["alpha needle beta"])
    state.cursor_line_abs = 0
    state.cursor_col = 0
    handle_named_key(state, "search")
    for ch in "needle":
        handle_text_input(state, ch)
    handle_named_key(state, "enter")
    frame = compose(state)
    assert frame[0][6].style == "cursor"
    assert frame[0][7].style == "search_hit"


def test_status_line_contains_mode_query_and_copy_count():
    state = CopyState.create(["alpha"], 60, 6)
    handle_named_key(state, "copy_mode")
    state.copied_text = "copied!"
    state.search.query = "needle"
    frame = compose(state)
    status = "".join(cell.ch for cell in frame[-1])
    assert "COPY" in status
    assert "needle" in status
    assert "copied=7" in status
