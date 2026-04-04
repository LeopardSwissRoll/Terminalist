from Test.TestCopy.model import CopyState, handle_named_key, handle_wheel


def _state(lines: list[str] | None = None) -> CopyState:
    return CopyState.create(lines or [f"line {i}" for i in range(20)], 20, 6)


def test_bracket_enters_copy_mode():
    state = _state(["", "alpha", "beta"])
    handle_named_key(state, "copy_mode")
    assert state.mode == "copy"
    assert state.cursor_line_abs == 2
    assert state.cursor_col == len("beta") - 1


def test_escape_exits_to_live():
    state = _state()
    handle_named_key(state, "copy_mode")
    handle_wheel(state, "up")
    assert state.mode == "copy"
    handle_named_key(state, "esc")
    assert state.mode == "live"
    assert state.viewport_top == state.live_tail_top
    assert state.selection is None


def test_wheel_up_from_live_enters_copy_mode():
    state = _state()
    old_top = state.viewport_top
    handle_wheel(state, "up")
    assert state.mode == "copy"
    assert state.viewport_top < old_top


def test_cursor_clamps_at_boundaries():
    state = _state(["a", "bb"])
    handle_named_key(state, "copy_mode")
    handle_named_key(state, "left")
    assert state.cursor_col == 0
    handle_named_key(state, "up")
    assert state.cursor_line_abs == 0
    handle_named_key(state, "end")
    assert state.cursor_col == 0


def test_page_navigation_preserves_visible_row_when_possible():
    state = _state([f"line {i}" for i in range(40)])
    handle_named_key(state, "copy_mode")
    state.viewport_top = 20
    state.cursor_line_abs = 22
    state.cursor_col = 2
    relative_row = state.cursor_line_abs - state.viewport_top
    handle_named_key(state, "page_up")
    assert state.cursor_line_abs - state.viewport_top == relative_row

