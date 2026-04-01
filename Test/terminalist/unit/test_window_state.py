"""WindowState unit tests."""

from __future__ import annotations

from terminalist.core.pane import Rect
from terminalist.frontend.split_tree import Direction, Leaf, Split
from terminalist.frontend.window_state import WindowState

from Test.conftest import make_pane


def test_window_local_focus_history_tracks_latest_pane():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    pane2 = make_pane("pane_2", cols=40, rows=24)
    window = WindowState("window_1", Split(Direction.VERTICAL, 0.5, Leaf(pane1), Leaf(pane2)))

    window.activate()
    window.set_focus(pane2)
    window.set_focus(pane1)

    assert window.focus_history == ["pane_2", "pane_1"]


def test_zoom_on_off_is_window_local():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    window = WindowState("window_1", Leaf(pane1))
    window.set_focus(pane1)

    assert window.toggle_zoom() is True
    assert window.zoom_pane is pane1
    assert window.active_root() is not window.root

    assert window.toggle_zoom() is False
    assert window.zoom_pane is None
    assert window.active_root() is window.root


def test_is_empty_reflects_root_presence():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    window = WindowState("window_1", Leaf(pane1))
    assert window.is_empty() is False

    window.root = None
    assert window.is_empty() is True


def test_layout_tracks_terminal_size_and_clears_needs_layout():
    pane1 = make_pane("pane_1", cols=80, rows=24)
    window = WindowState("window_1", Leaf(pane1))

    window.layout(Rect(0, 0, 80, 24), terminal_size=(24, 80))

    assert window.needs_layout is False
    assert window.last_layout_size == (24, 80)
