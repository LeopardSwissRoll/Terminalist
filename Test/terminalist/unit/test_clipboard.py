from unittest.mock import MagicMock, patch

from terminalist.clipboard import copy_text


def test_copy_text_success():
    completed = MagicMock(returncode=0)
    with patch("terminalist.clipboard.subprocess.run", return_value=completed) as run:
        assert copy_text("hello") is True
    run.assert_called_once()


def test_copy_text_failure_falls_back_cleanly():
    completed = MagicMock(returncode=1)
    with patch("terminalist.clipboard.subprocess.run", return_value=completed):
        assert copy_text("hello") is False


def test_copy_text_os_error_falls_back_cleanly():
    with patch("terminalist.clipboard.subprocess.run", side_effect=OSError):
        assert copy_text("hello") is False
