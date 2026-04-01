"""App unit tests for focus and split policy.

Lightweight tests that exercise App methods without spawning PTYs.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from terminalist.app import App
from terminalist.core.pane import Rect
from terminalist.frontend.split_tree import Direction, Leaf, Split, layout
from terminalist.input.win32 import MOUSE_WHEELED, MouseEvent

from Test.conftest import make_pane, feed_pane


def _make_app(pane):
    app = App.__new__(App)
    app._root = Leaf(pane)
    app._focused = None
    app._focus_history = []
    app._compositor = MagicMock()
    app._pending_redraw_at = 0.0
    app._pane_counter = 1
    App._set_focus(app, pane)
    return app


def test_split_focuses_new_pane():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    app = _make_app(pane1)
    layout(app._root, Rect(0, 0, 80, 24))

    pane2 = make_pane("pane_2", cols=40, rows=24)
    app._create_pane = lambda provider: pane2

    with patch("terminalist.app.terminal_size", return_value=(24, 80)):
        App._split(app, Direction.VERTICAL)

    assert app._focused is pane2
    assert pane1.focused is False
    assert pane2.focused is True
    assert isinstance(app._root, Split)
    assert app._root.first.pane is pane1
    assert app._root.second.pane is pane2


def test_repeated_split_applies_to_latest_focused_pane():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    app = _make_app(pane1)
    layout(app._root, Rect(0, 0, 80, 24))

    pane2 = make_pane("pane_2", cols=40, rows=24)
    pane3 = make_pane("pane_3", cols=40, rows=12)
    created = iter([pane2, pane3])
    app._create_pane = lambda provider: next(created)

    with patch("terminalist.app.terminal_size", return_value=(24, 80)):
        App._split(app, Direction.VERTICAL)
        App._split(app, Direction.HORIZONTAL)

    assert app._focused is pane3
    assert isinstance(app._root, Split)
    assert app._root.direction == Direction.VERTICAL
    assert app._root.first.pane is pane1
    assert isinstance(app._root.second, Split)
    assert app._root.second.direction == Direction.HORIZONTAL
    assert app._root.second.first.pane is pane2
    assert app._root.second.second.pane is pane3


def test_close_prefers_recent_focus_history():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    app = _make_app(pane1)
    layout(app._root, Rect(0, 0, 80, 24))

    pane2 = make_pane("pane_2", cols=40, rows=24)
    pane3 = make_pane("pane_3", cols=40, rows=12)
    created = iter([pane2, pane3])
    app._create_pane = lambda provider: next(created)
    app._sm = MagicMock()
    app._zoom_pane = None
    app._pre_zoom_root = None
    app._running = True

    with patch("terminalist.app.terminal_size", return_value=(24, 80)):
        App._split(app, Direction.VERTICAL)    # focus pane2
        App._set_focus(app, pane1)             # recent focus pane1
        App._split(app, Direction.HORIZONTAL)  # focus pane3
        App._close_pane(app)                   # close pane3 -> pane1

    assert app._focused is pane1


def test_mouse_click_focuses_interior_pane():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=40, rows=24)
    app = _make_app(pane1)
    app._root = Split(Direction.VERTICAL, 0.5, Leaf(pane1), Leaf(pane2))
    layout(app._root, Rect(0, 0, 80, 24))

    App._handle_mouse_event(app, MouseEvent(x=60, y=5, buttons=0x0001, flags=0))

    assert app._focused is pane2


def test_mouse_wheel_scrolls_hovered_pane_and_updates_status():
    pane1 = make_pane("pane_1", cols=40, rows=6, text="live")
    pane2 = make_pane("pane_2", cols=40, rows=6)

    app = _make_app(pane1)
    app._root = Split(Direction.VERTICAL, 0.5, Leaf(pane1), Leaf(pane2))
    layout(app._root, Rect(0, 0, 80, 12))
    for i in range(20):
        feed_pane(pane2, f"line-{i}\r\n")

    # Reversed semantics: wheel-down enters scrollback.
    App._handle_mouse_event(
        app,
        MouseEvent(x=60, y=5, buttons=0, flags=MOUSE_WHEELED),
    )

    assert pane2.scroll_offset == 3
    assert pane2.in_copy_mode is True
    assert app._focused is pane1
    app._compositor.mark_dirty.assert_called()

    text = "".join(ch.data for ch in App._build_status_line(app, 120))
    assert "pane_2:" in text
    assert "scroll=3" in text


def test_mouse_wheel_falls_back_to_focused_pane():
    pane1 = make_pane("pane_1", cols=80, rows=6)

    app = _make_app(pane1)
    layout(app._root, Rect(0, 0, 80, 12))
    for i in range(20):
        feed_pane(pane1, f"history-{i}\r\n")

    App._handle_mouse_event(
        app,
        MouseEvent(x=500, y=500, buttons=0, flags=MOUSE_WHEELED),
    )

    assert pane1.scroll_offset == 3
    assert pane1.in_copy_mode is True


def test_status_line_marks_focused_pane():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=40, rows=24)
    app = _make_app(pane1)
    app._root = Split(Direction.VERTICAL, 0.5, Leaf(pane1), Leaf(pane2))
    App._set_focus(app, pane2)

    chars = App._build_status_line(app, 80)
    text = "".join(ch.data for ch in chars)

    assert "[*pane_2:" in text
    assert "[ pane_1:" in text


def test_resize_pane_updates_split_ratio():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=40, rows=24)
    app = _make_app(pane1)
    app._root = Split(Direction.VERTICAL, 0.5, Leaf(pane1), Leaf(pane2))
    app._focused = pane1
    app._compositor = MagicMock()
    layout(app._root, Rect(0, 0, 80, 24))

    with patch("terminalist.app.terminal_size", return_value=(24, 80)):
        App._resize_pane(app, Direction.VERTICAL, toward_second=True)

    assert app._root.ratio > 0.5
    app._compositor.full_redraw.assert_called_once()
