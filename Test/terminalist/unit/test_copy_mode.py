from terminalist.core.copy_mode import CopyState, handle_named_key, handle_text_input, handle_wheel


def _state(lines: list[str] | None = None) -> CopyState:
    return CopyState.create(lines or [f"line {i}" for i in range(20)], 20, 5)


def test_enter_copy_mode_positions_cursor_at_tail():
    state = _state(["", "alpha", "beta"])
    handle_named_key(state, "copy_mode")

    assert state.mode == "copy"
    assert state.cursor_line_abs == 2
    assert state.cursor_col == len("beta") - 1


def test_escape_returns_to_live_tail():
    state = _state()
    handle_named_key(state, "copy_mode")
    handle_wheel(state, "up")

    handle_named_key(state, "esc")

    assert state.mode == "live"
    assert state.viewport_top == state.live_tail_top


def test_wheel_up_from_live_enters_copy_mode():
    state = _state()
    old_top = state.viewport_top

    handle_wheel(state, "up")

    assert state.mode == "copy"
    assert state.viewport_top < old_top


def test_page_navigation_preserves_visible_row():
    state = _state([f"line {i}" for i in range(40)])
    handle_named_key(state, "copy_mode")
    state.viewport_top = 20
    state.cursor_line_abs = 22
    state.cursor_col = 2

    relative_row = state.cursor_line_abs - state.viewport_top
    handle_named_key(state, "page_up")

    assert state.cursor_line_abs - state.viewport_top == relative_row


def test_selection_trim_and_copy_to_internal_buffer():
    state = CopyState.create(["hello"], 20, 5)
    handle_named_key(state, "copy_mode")
    handle_named_key(state, "space")
    handle_named_key(state, "left")
    handle_named_key(state, "enter")

    assert state.mode == "live"
    assert state.copied_text == "lo"


def test_search_is_non_wrapping():
    state = CopyState.create(["needle here", "middle", "tail"], 20, 5)
    handle_named_key(state, "copy_mode")
    state.cursor_line_abs = 2
    state.cursor_col = 0
    handle_named_key(state, "search")
    for ch in "needle":
        handle_text_input(state, ch)

    handle_named_key(state, "enter")

    assert state.mode == "copy"
    assert state.search.active_match_idx is None
    assert state.cursor_line_abs == 2


def test_sync_content_preserves_copy_state_and_clamps():
    state = CopyState.create([f"line {i}" for i in range(10)], 20, 5)
    handle_named_key(state, "copy_mode")
    state.viewport_top = 3
    state.cursor_line_abs = 4
    state.cursor_col = 5

    state.sync_content(["a", "b", "c"], 10, 2)

    assert state.mode == "copy"
    assert state.viewport_top <= state.max_viewport_top
    assert state.cursor_line_abs <= 2
