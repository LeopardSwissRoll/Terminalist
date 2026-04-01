from pathlib import Path
from unittest.mock import patch

from Test.TestPane.main import AppState
from Test.TestPane.model import Direction, MoveDirection
from Test.TestPane.snapshot import dump_snapshot


def test_split_focuses_new_pane():
    state = AppState.create(9, 7)
    assert state.focused_id == "p1"
    assert state.split(Direction.VERTICAL) is True
    assert state.focused_id == "p2"


def test_move_focus_updates_history():
    state = AppState.create(9, 7)
    state.split(Direction.VERTICAL)
    state.move(MoveDirection.LEFT)
    assert state.focused_id == "p1"
    assert state.focus_history[-1] == "p1"


def test_close_restores_recent_focus():
    state = AppState.create(11, 9)
    state.split(Direction.VERTICAL)   # p2 focused
    state.move(MoveDirection.LEFT)    # p1 focused
    state.split(Direction.HORIZONTAL) # p3 focused
    state.move(MoveDirection.UP)      # p1 focused
    state.close_focused()
    assert state.focused_id == "p3"


def test_close_falls_back_to_replacement_subtree_when_history_missing():
    state = AppState.create(9, 7)
    state.split(Direction.VERTICAL)   # p2 focused
    state.focus_history = ["p2"]
    state.close_focused()
    assert state.focused_id == "p1"


def test_last_pane_close_stops_app():
    state = AppState.create(9, 7)
    state.close_focused()
    assert state.running is False
    assert state.root is None


def test_mouse_click_focuses_clicked_pane():
    state = AppState.create(9, 7)
    state.split(Direction.VERTICAL)
    assert state.focused_id == "p2"
    assert state.handle_mouse_click(1, 1) is True
    assert state.focused_id == "p1"


def test_snapshot_dump_overwrites_files(tmp_path: Path):
    with patch("Test.TestPane.snapshot.META_PATH", tmp_path / "meta.txt"), patch("Test.TestPane.snapshot.FRAME_PATH", tmp_path / "frame.txt"):
        state = AppState.create(9, 7)
        frame = state.render_frame()
        dump_snapshot(state, frame, "init")
        dump_snapshot(state, frame, "key:v")

        meta_text = (tmp_path / "meta.txt").read_text(encoding="utf-8")
        frame_text = (tmp_path / "frame.txt").read_text(encoding="utf-8")
        assert "last_input=key:v" in meta_text
        assert meta_text.count("last_input=") == 1
        assert "P1" in frame_text
