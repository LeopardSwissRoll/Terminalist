from Test.TestCopy.model import CopyState, handle_named_key, handle_text_input


def _enter_copy(lines: list[str]) -> CopyState:
    state = CopyState.create(lines, 40, 6)
    handle_named_key(state, "copy_mode")
    return state


def test_search_prompt_capture():
    state = _enter_copy(["alpha", "needle here"])
    handle_named_key(state, "search")
    handle_text_input(state, "n")
    handle_text_input(state, "e")
    assert state.mode == "search"
    assert state.search.query == "ne"


def test_forward_search_lands_on_first_later_match():
    state = _enter_copy(["needle one", "middle", "needle two"])
    state.cursor_line_abs = 0
    state.cursor_col = 0
    handle_named_key(state, "search")
    for ch in "needle":
        handle_text_input(state, ch)
    handle_named_key(state, "enter")
    assert state.mode == "copy"
    assert state.cursor_line_abs == 2
    assert state.cursor_col == 0


def test_next_prev_move_among_matches():
    state = _enter_copy(["aaa", "needle first", "bbb", "needle second", "needle third"])
    state.cursor_line_abs = 0
    state.cursor_col = 0
    handle_named_key(state, "search")
    for ch in "needle":
        handle_text_input(state, ch)
    handle_named_key(state, "enter")
    assert state.cursor_line_abs == 1
    handle_named_key(state, "next_match")
    assert state.cursor_line_abs == 3
    handle_named_key(state, "prev_match")
    assert state.cursor_line_abs == 1


def test_no_match_leaves_state_stable():
    state = _enter_copy(["alpha", "beta"])
    state.cursor_line_abs = 1
    state.cursor_col = 2
    handle_named_key(state, "search")
    for ch in "zzz":
        handle_text_input(state, ch)
    handle_named_key(state, "enter")
    assert state.mode == "copy"
    assert state.cursor_line_abs == 1
    assert state.search.active_match_idx is None

