"""VT100 writer tests — escape sequence output verification."""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pyte.screens import Char
from terminalist.frontend.vt100_writer import VT100Writer

results: list[tuple[str, bool, str]] = []


def run_test(name, fn):
    try:
        fn()
        print(f"  PASS  {name}")
        results.append((name, True, ""))
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        results.append((name, False, str(e)))
    except Exception as e:
        print(f"  FAIL  {name}: {type(e).__name__}: {e}")
        results.append((name, False, str(e)))


def _capture_writer() -> tuple[VT100Writer, io.StringIO]:
    """Create a writer that captures output to StringIO."""
    buf = io.StringIO()
    w = VT100Writer()
    # Monkey-patch flush to write to StringIO instead of stdout
    original_flush = w.flush

    def patched_flush():
        data = "".join(w._buf)
        w._buf.clear()
        buf.write(data)

    w.flush = patched_flush
    return w, buf


C = lambda data, fg="default", bg="default", **kw: Char(
    data, fg, bg,
    kw.get("bold", False), kw.get("italics", False),
    kw.get("underscore", False), kw.get("strikethrough", False),
    kw.get("reverse", False), kw.get("blink", False),
)


def test_move_to():
    w, buf = _capture_writer()
    w.move_to(5, 10)
    w.flush()
    assert buf.getvalue() == "\x1b[11;6H"  # 1-indexed


def test_move_to_origin():
    w, buf = _capture_writer()
    w.move_to(0, 0)
    w.flush()
    assert buf.getvalue() == "\x1b[1;1H"


def test_move_to_same_position_skipped():
    w, buf = _capture_writer()
    w.move_to(5, 10)
    w.move_to(5, 10)  # same — should be skipped
    w.flush()
    assert buf.getvalue().count("\x1b[") == 1


def test_set_attrs_default():
    w, buf = _capture_writer()
    w.set_attrs(C("x"))  # default colors
    w.flush()
    output = buf.getvalue()
    assert "\x1b[" in output
    assert "39" in output  # default fg
    assert "49" in output  # default bg


def test_set_attrs_red():
    w, buf = _capture_writer()
    w.set_attrs(C("x", fg="red"))
    w.flush()
    output = buf.getvalue()
    assert "31" in output  # red fg


def test_set_attrs_bold():
    w, buf = _capture_writer()
    w.set_attrs(C("x", bold=True))
    w.flush()
    assert "1" in buf.getvalue().split(";")  # bold SGR


def test_set_attrs_batching():
    """Same attrs twice — second call should produce no output."""
    w, buf = _capture_writer()
    char = C("x", fg="red")
    w.set_attrs(char)
    w.set_attrs(char)  # same — skip
    w.flush()
    # Should have exactly 1 SGR sequence
    count = buf.getvalue().count("\x1b[")
    assert count == 1, f"Expected 1 SGR, got {count}"


def test_set_attrs_change():
    """Different attrs — should produce new SGR."""
    w, buf = _capture_writer()
    w.set_attrs(C("x", fg="red"))
    w.set_attrs(C("x", fg="blue"))
    w.flush()
    count = buf.getvalue().count("\x1b[")
    assert count == 2, f"Expected 2 SGRs, got {count}"


def test_write_char():
    w, buf = _capture_writer()
    w.write_char("A")
    w.write_char("B")
    w.flush()
    assert "AB" in buf.getvalue()


def test_hide_show_cursor():
    w, buf = _capture_writer()
    w.hide_cursor()
    w.show_cursor()
    w.flush()
    output = buf.getvalue()
    assert "\x1b[?25l" in output
    assert "\x1b[?25h" in output


def test_reset_attrs():
    w, buf = _capture_writer()
    w.reset_attrs()
    w.flush()
    assert "\x1b[0m" in buf.getvalue()


def test_24bit_color():
    w, buf = _capture_writer()
    w.set_attrs(C("x", fg="#ff8000", bg="#003366"))
    w.flush()
    output = buf.getvalue()
    assert "38;2;255;128;0" in output
    assert "48;2;0;51;102" in output


def test_256_color():
    w, buf = _capture_writer()
    w.set_attrs(C("x", fg="196"))
    w.flush()
    assert "38;5;196" in buf.getvalue()


def test_clear_resets_state():
    w, buf = _capture_writer()
    w.move_to(5, 5)
    w.set_attrs(C("x", fg="red"))
    w.clear()
    # After clear, move_to should emit again (position reset)
    w.move_to(5, 5)
    w.flush()
    assert "\x1b[6;6H" in buf.getvalue()


def main():
    print("=" * 60)
    print("VT100 Writer Tests")
    print("=" * 60)

    run_test("move_to", test_move_to)
    run_test("move_to_origin", test_move_to_origin)
    run_test("move_to_same_position_skipped", test_move_to_same_position_skipped)
    run_test("set_attrs_default", test_set_attrs_default)
    run_test("set_attrs_red", test_set_attrs_red)
    run_test("set_attrs_bold", test_set_attrs_bold)
    run_test("set_attrs_batching", test_set_attrs_batching)
    run_test("set_attrs_change", test_set_attrs_change)
    run_test("write_char", test_write_char)
    run_test("hide_show_cursor", test_hide_show_cursor)
    run_test("reset_attrs", test_reset_attrs)
    run_test("24bit_color", test_24bit_color)
    run_test("256_color", test_256_color)
    run_test("clear_resets_state", test_clear_resets_state)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed, {len(results)} total")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
