"""App unit tests for window, focus, and split policy."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from terminalist.app import App
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
    app._pending_redraw_at = 0.0
    app._pane_counter = 0
    app._window_counter = 0
    app._input_state = MagicMock()
    app._input_state.track_bracketed_paste = lambda data: None
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


def test_mouse_wheel_scrolls_hovered_pane_and_updates_status():
    pane1 = make_pane("pane_1", cols=40, rows=6, text="live")
    pane2 = make_pane("pane_2", cols=40, rows=6)
    pane1.session.shell_type = "shell"
    pane2.session.shell_type = "shell"
    window = WindowState("window_1", Split(Direction.VERTICAL, 0.5, Leaf(pane1), Leaf(pane2)))
    window.set_focus(pane1)
    app = _make_app(window)
    window.layout(Rect(0, 0, 80, 12), terminal_size=(12, 80))
    for i in range(20):
        feed_pane(pane2, f"line-{i}\r\n")

    App._handle_mouse_event(app, MouseEvent(x=60, y=5, buttons=0, flags=MOUSE_WHEELED))

    assert pane2.scroll_offset == 3
    assert pane2.in_copy_mode is True
    assert app._active_window().focused is pane1
    app._compositor.mark_dirty.assert_called()

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
    assert "scroll=3" in text


def test_status_line_marks_active_window_slot():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=80, rows=24)
    app = _make_app(_window("window_1", pane1), _window("window_2", pane2))

    App._activate_window(app, 1, size=(24, 80))

    text = "".join(ch.data for ch in App._build_status_line(app, 80))
    assert "[ 1:shell]" in text
    assert "[*2:shell]" in text


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
