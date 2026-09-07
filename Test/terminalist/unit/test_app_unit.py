"""App unit tests for window, focus, and split policy."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from terminalist.app import App
from terminalist.core.copy_mode import handle_named_key
from terminalist.core.pane import Rect
from terminalist.frontend.split_tree import Direction, Leaf, Split
from terminalist.frontend.window_state import WindowState
from terminalist.input.win32 import MOUSE_WHEELED, MouseEvent

from Test.conftest import FakeSession, feed_pane, make_pane


def _window(window_id: str, pane):
    pane.session.shell_type = "shell"
    window = WindowState(window_id, Leaf(pane))
    window.set_focus(pane)
    return window


def _blank_app() -> App:
    app = App.__new__(App)
    app._windows = []
    app._active_window_idx = 0
    app._window_history = []
    app._compositor = MagicMock()
    app._render_interval_s = 0.016
    app._last_render_at = 0.0
    app._next_render_at = 0.0
    app._render_immediate_requested = False
    app._followup_redraw_at = 0.0
    app._pane_counter = 0
    app._window_counter = 0
    app._input_state = MagicMock()
    app._input_state.track_bracketed_paste = lambda data: None
    app._input_state.input_count = 0
    app._sm = MagicMock()
    app._running = True
    app._tes = MagicMock()
    app._writer = MagicMock()
    return app


def _make_app(*windows: WindowState) -> App:
    app = _blank_app()
    app._windows = list(windows)
    app._window_counter = len(windows)
    app._pane_counter = sum(len(window.all_panes()) for window in windows)
    if windows:
        App._activate_window(app, 0, size=(24, 80))
    return app


def test_bootstrap_initial_window_creates_single_active_window():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane1.session.shell_type = "powershell"
    app = _blank_app()
    app._create_pane = lambda provider: pane1

    App._bootstrap_initial_window(app, 24, 80)

    assert len(app._windows) == 1
    assert app._active_window_idx == 0
    assert app._active_window().focused is pane1
    assert app._active_window().window_id == "window_1"


def test_new_window_creates_second_window_and_activates_it():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=80, rows=24)
    app = _make_app(_window("window_1", pane1))
    app._create_pane = lambda provider: pane2

    App._new_window(app)

    assert len(app._windows) == 2
    assert app._active_window_idx == 1
    assert app._active_window().focused is pane2


def test_next_prev_tab_wrap_around():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=80, rows=24)
    app = _make_app(_window("window_1", pane1), _window("window_2", pane2))

    App._cycle_window(app, 1)
    assert app._active_window_idx == 1

    App._cycle_window(app, 1)
    assert app._active_window_idx == 0

    App._cycle_window(app, -1)
    assert app._active_window_idx == 1


def test_goto_tab_slot_success_and_noop():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=80, rows=24)
    app = _make_app(_window("window_1", pane1), _window("window_2", pane2))

    App._goto_window_slot(app, 1)
    assert app._active_window_idx == 1

    App._goto_window_slot(app, 4)
    assert app._active_window_idx == 1


def test_split_applies_only_to_active_window():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=80, rows=24)
    pane3 = make_pane("pane_3", cols=40, rows=24)
    app = _make_app(_window("window_1", pane1), _window("window_2", pane2))
    app._create_pane = lambda provider: pane3

    App._activate_window(app, 1, size=(24, 80))
    with patch("terminalist.app.terminal_size", return_value=(24, 80)):
        App._split(app, Direction.VERTICAL)

    assert isinstance(app._windows[0].root, Leaf)
    assert isinstance(app._windows[1].root, Split)
    assert app._windows[1].focused is pane3


def test_window_switch_restores_each_windows_focused_pane():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=40, rows=24)
    pane3 = make_pane("pane_3", cols=80, rows=24)
    window1 = WindowState("window_1", Split(Direction.VERTICAL, 0.5, Leaf(pane1), Leaf(pane2)))
    window1.set_focus(pane2)
    window2 = _window("window_2", pane3)
    app = _make_app(window1, window2)

    App._activate_window(app, 1, size=(24, 80))
    assert app._active_window().focused is pane3

    App._activate_window(app, 0, size=(24, 80))
    assert app._active_window().focused is pane2


def test_close_last_pane_removes_window_and_activates_recent_window():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=80, rows=24)
    app = _make_app(_window("window_1", pane1), _window("window_2", pane2))
    app._sm = MagicMock()

    App._activate_window(app, 1, size=(24, 80))
    with patch("terminalist.app.terminal_size", return_value=(24, 80)):
        App._close_pane(app)

    assert len(app._windows) == 1
    assert app._active_window_idx == 0
    assert app._active_window().focused is pane1


def test_close_last_window_stops_app():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    app = _make_app(_window("window_1", pane1))
    app._sm = MagicMock()

    with patch("terminalist.app.terminal_size", return_value=(24, 80)):
        App._close_pane(app)

    assert app._running is False
    assert app._windows == []


def test_mouse_click_focuses_interior_pane_of_active_window():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=40, rows=24)
    window = WindowState("window_1", Split(Direction.VERTICAL, 0.5, Leaf(pane1), Leaf(pane2)))
    window.set_focus(pane1)
    app = _make_app(window)
    window.layout(Rect(0, 0, 80, 24), terminal_size=(24, 80))

    App._handle_mouse_event(app, MouseEvent(x=60, y=5, buttons=0x0001, flags=0))

    assert app._active_window().focused is pane2


def test_batched_dirty_render_schedules_next_frame():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    app = _make_app(_window("window_1", pane1))
    app._compositor.reset_mock()
    app._render_immediate_requested = False
    app._next_render_at = 0.0
    app._last_render_at = 10.0

    with patch("terminalist.app.time.monotonic", return_value=10.001):
        App._mark_dirty_for_pane(app, pane1)

    assert app._render_immediate_requested is False
    assert app._next_render_at == 10.016
    app._compositor.mark_dirty.assert_called_once()


def test_mouse_wheel_scrolls_hovered_pane_and_updates_status():
    pane1 = make_pane("pane_1", cols=40, rows=6, text="live")
    pane2 = make_pane("pane_2", cols=40, rows=6)
    pane1.session.shell_type = "shell"
    pane2.session.shell_type = "shell"
    window = WindowState("window_1", Split(Direction.VERTICAL, 0.5, Leaf(pane1), Leaf(pane2)))
    window.set_focus(pane1)
    app = _make_app(window)
    window.layout(Rect(0, 0, 80, 12), terminal_size=(12, 80))
    app._compositor.reset_mock()
    for i in range(20):
        feed_pane(pane2, f"line-{i}\r\n")

    App._handle_mouse_event(app, MouseEvent(x=60, y=5, buttons=0, flags=MOUSE_WHEELED))

    assert pane2.scroll_offset == 3
    assert pane2.in_copy_mode is True
    assert app._active_window().focused is pane1
    app._compositor.full_redraw.assert_called_once()

    text = "".join(ch.data for ch in App._build_status_line(app, 120))
    assert "[*1:shell]" in text
    assert "pane_1: shell" in text


def test_mouse_wheel_falls_back_to_focused_pane():
    pane1 = make_pane("pane_1", cols=80, rows=6)
    app = _make_app(_window("window_1", pane1))
    app._active_window().layout(Rect(0, 0, 80, 12), terminal_size=(12, 80))
    for i in range(20):
        feed_pane(pane1, f"history-{i}\r\n")

    App._handle_mouse_event(app, MouseEvent(x=500, y=500, buttons=0, flags=MOUSE_WHEELED))

    assert pane1.scroll_offset == 3
    assert pane1.in_copy_mode is True
    text = "".join(ch.data for ch in App._build_status_line(app, 120))
    assert "[COPY " in text
    assert "sel=no" in text


def test_prefix_copy_mode_enters_copy_mode():
    pane1 = make_pane("pane_1", cols=80, rows=6)
    app = _make_app(_window("window_1", pane1))
    feed_pane(pane1, "alpha\r\nbeta")
    app._compositor.reset_mock()
    app._render_immediate_requested = False

    with patch("terminalist.app.time.monotonic", return_value=20.0):
        App._dispatch_prefix(app, "enter_copy_mode", 1)

    assert pane1.in_copy_mode is True
    assert pane1.copy_mode_state is not None
    assert app._render_immediate_requested is True
    assert app._next_render_at == 20.0
    app._compositor.full_redraw.assert_called_once()


def test_ctrl_shift_c_shortcut_enters_copy_mode():
    pane1 = make_pane("pane_1", cols=80, rows=6)
    app = _make_app(_window("window_1", pane1))
    feed_pane(pane1, "alpha\r\nbeta")
    app._compositor.reset_mock()

    remaining = App._consume_global_copy_shortcut(app, [("\x03", 0x43, 0x0010 | 0x0008, 1)])

    assert remaining == []
    assert pane1.in_copy_mode is True
    app._compositor.full_redraw.assert_called_once()


def test_copy_mode_survives_window_switch():
    pane1 = make_pane("pane_1", cols=80, rows=6)
    pane2 = make_pane("pane_2", cols=80, rows=6)
    app = _make_app(_window("window_1", pane1), _window("window_2", pane2))
    feed_pane(pane1, "alpha\r\nbeta")
    pane1.enter_copy_mode()

    App._activate_window(app, 1, size=(24, 80))
    App._activate_window(app, 0, size=(24, 80))

    assert pane1.in_copy_mode is True


def test_copy_mode_cursor_move_requests_immediate_render():
    pane1 = make_pane("pane_1", cols=80, rows=6)
    app = _make_app(_window("window_1", pane1))
    feed_pane(pane1, "alpha\r\nbeta")
    pane1.enter_copy_mode()
    app._compositor.reset_mock()
    app._render_immediate_requested = False
    app._next_render_at = 0.0

    with patch("terminalist.app.time.monotonic", return_value=30.0):
        App._process_copy_input(app, [(None, 0x25, 0, 1)], h_in=0)

    assert app._render_immediate_requested is True
    assert app._next_render_at == 30.0
    app._compositor.mark_dirty.assert_called_once()


def test_search_mode_escape_requests_full_redraw():
    pane1 = make_pane("pane_1", cols=80, rows=6)
    app = _make_app(_window("window_1", pane1))
    feed_pane(pane1, "alpha\r\nbeta")
    pane1.enter_copy_mode()
    app._compositor.reset_mock()

    with patch("terminalist.app.time.monotonic", return_value=31.0):
        App._process_copy_input(app, [("/", 0xBF, 0, 1)], h_in=0)

    assert pane1.copy_mode_state is not None
    assert pane1.copy_mode_state.mode == "search"
    app._compositor.full_redraw.assert_called_once()


def test_copy_mode_prefix_coexists_with_window_navigation():
    pane1 = make_pane("pane_1", cols=80, rows=6)
    pane2 = make_pane("pane_2", cols=80, rows=6)
    app = _make_app(_window("window_1", pane1), _window("window_2", pane2))
    feed_pane(pane1, "alpha\r\nbeta")
    pane1.enter_copy_mode()

    with patch("terminalist.app._read_prefix_action", return_value="next_tab"):
        App._process_copy_input(app, [("\x02", 0x42, 0, 1)], h_in=0)

    assert app._active_window_idx == 1


def test_copy_mode_copy_keeps_internal_text_when_clipboard_fails():
    pane1 = make_pane("pane_1", cols=80, rows=6)
    app = _make_app(_window("window_1", pane1))
    feed_pane(pane1, "hello")
    pane1.enter_copy_mode()
    state = pane1.copy_mode_state
    assert state is not None
    state.start_selection()
    handle_named_key(state, "left")

    with patch("terminalist.app.copy_text", return_value=False):
        App._process_copy_input(app, [("\r", 0x0D, 0, 1)], h_in=0)

    assert pane1.in_copy_mode is False
    assert pane1.copied_text == "lo"


def test_status_line_marks_active_window_slot():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=80, rows=24)
    app = _make_app(_window("window_1", pane1), _window("window_2", pane2))

    App._activate_window(app, 1, size=(24, 80))

    text = "".join(ch.data for ch in App._build_status_line(app, 80))
    assert "[ 1:shell]" in text
    assert "[*2:shell]" in text


def test_status_line_shows_copy_mode_details():
    pane1 = make_pane("pane_1", cols=80, rows=6)
    app = _make_app(_window("window_1", pane1))
    feed_pane(pane1, "alpha\r\nbeta")
    pane1.enter_copy_mode()

    text = "".join(ch.data for ch in App._build_status_line(app, 120))

    assert "[COPY " in text
    assert "sel=no" in text


def test_resize_pane_updates_split_ratio_only_in_active_window():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=40, rows=24)
    pane3 = make_pane("pane_3", cols=80, rows=24)
    window1 = WindowState("window_1", Split(Direction.VERTICAL, 0.5, Leaf(pane1), Leaf(pane2)))
    window1.set_focus(pane1)
    window2 = _window("window_2", pane3)
    app = _make_app(window1, window2)
    app._compositor = MagicMock()

    with patch("terminalist.app.terminal_size", return_value=(24, 80)):
        App._resize_pane(app, Direction.VERTICAL, toward_second=True)

    assert window1.root.ratio > 0.5
    app._compositor.full_redraw.assert_called_once()


def test_inactive_window_dirty_callback_does_not_mark_active_render_dirty():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    app = _make_app(_window("window_1", pane1))
    app._compositor = MagicMock()

    sessions = [FakeSession("powershell_1", 80, 24), FakeSession("powershell_2", 80, 24)]
    app._sm.create = MagicMock(side_effect=sessions)

    pane2 = App._create_pane(app, "powershell")
    pane2.session.shell_type = "powershell"
    app._windows.append(_window("window_2", pane2))

    pane2.session.emit_dirty()
    app._compositor.mark_dirty.assert_not_called()


def test_activation_after_inactive_output_triggers_redraw_and_preserves_screen():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    app = _make_app(_window("window_1", pane1))
    app._compositor = MagicMock()

    sessions = [FakeSession("powershell_1", 80, 24), FakeSession("powershell_2", 80, 24)]
    app._sm.create = MagicMock(side_effect=sessions)

    pane2 = App._create_pane(app, "powershell")
    pane2.session.shell_type = "powershell"
    window2 = _window("window_2", pane2)
    app._windows.append(window2)

    feed_pane(pane2, "hello")
    pane2.session.emit_dirty()
    app._compositor.mark_dirty.assert_not_called()

    App._activate_window(app, 1, size=(24, 80))

    grid, _, _, _, _ = pane2.session.get_screen_snapshot()
    rendered = "".join(cell.data for cell in grid[0][:5])
    assert rendered == "hello"
    app._compositor.full_redraw.assert_called()


def test_zoom_state_is_window_local_across_switches():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=80, rows=24)
    app = _make_app(_window("window_1", pane1), _window("window_2", pane2))

    with patch("terminalist.app.terminal_size", return_value=(24, 80)):
        App._toggle_zoom(app)

    assert app._windows[0].zoom_pane is pane1
    App._activate_window(app, 1, size=(24, 80))
    App._activate_window(app, 0, size=(24, 80))
    assert app._active_window().zoom_pane is pane1
