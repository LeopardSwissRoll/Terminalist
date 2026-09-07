import shutil
import uuid
from pathlib import Path
from unittest.mock import patch

from Test.TestCopy.model import CopyState
from Test.TestCopy.render import compose
from Test.TestCopy.snapshot import dump_snapshot


def test_snapshot_files_overwrite_not_append():
    state = CopyState.create(["alpha", "beta"], 20, 6)
    state.copied_text = "first"
    frame = compose(state)
    tmp_path = Path(__file__).resolve().parent / f"_tmp_snapshot_{uuid.uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)

    try:
        with (
            patch("Test.TestCopy.snapshot.META_PATH", tmp_path / "meta.txt"),
            patch("Test.TestCopy.snapshot.FRAME_PATH", tmp_path / "frame.txt"),
            patch("Test.TestCopy.snapshot.COPY_PATH", tmp_path / "copy.txt"),
        ):
            dump_snapshot(state, frame, "key:[")
            state.copied_text = "second"
            dump_snapshot(state, frame, "key:enter")

        meta_text = (tmp_path / "meta.txt").read_text(encoding="utf-8")
        frame_text = (tmp_path / "frame.txt").read_text(encoding="utf-8")
        copy_text = (tmp_path / "copy.txt").read_text(encoding="utf-8")

        assert meta_text.count("last_input=") == 1
        assert "last_input=key:enter" in meta_text
        assert frame_text.count("LIVE") == 1
        assert copy_text == "second"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
