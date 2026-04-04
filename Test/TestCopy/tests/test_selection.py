from Test.TestCopy.model import CopyState, extract_selection_text, handle_named_key


def _enter_copy(lines: list[str]) -> CopyState:
    state = CopyState.create(lines, 40, 6)
    handle_named_key(state, "copy_mode")
    return state


def test_single_line_copy():
    state = _enter_copy(["alpha beta"])
    state.cursor_line_abs = 0
    state.cursor_col = 2
    handle_named_key(state, "space")
    state.move_cursor(dx=2)
    assert extract_selection_text(state) == "pha"


def test_multi_line_copy():
    state = _enter_copy(["abc", "def", "ghi"])
    state.cursor_line_abs = 0
    state.cursor_col = 1
    handle_named_key(state, "space")
    state.cursor_line_abs = 2
    state.cursor_col = 1
    state.selection.cursor_line_abs = 2
    state.selection.cursor_col = 1
    assert extract_selection_text(state) == "bc\ndef\ngh"


def test_trailing_whitespace_trim():
    state = _enter_copy(["abc   ", "def   "])
    state.cursor_line_abs = 0
    state.cursor_col = 0
    handle_named_key(state, "space")
    state.cursor_line_abs = 1
    state.cursor_col = 5
    state.selection.cursor_line_abs = 1
    state.selection.cursor_col = 5
    assert extract_selection_text(state) == "abc\ndef"


def test_enter_copies_and_exits_copy_mode():
    state = _enter_copy(["hello"])
    state.cursor_line_abs = 0
    state.cursor_col = 1
    handle_named_key(state, "space")
    state.move_cursor(dx=2)
    handle_named_key(state, "enter")
    assert state.copied_text == "ell"
    assert state.mode == "live"

