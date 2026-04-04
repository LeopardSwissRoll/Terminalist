"""Interactive TestCopy application."""

from __future__ import annotations

import argparse
import sys

from Test.TestCopy.console import RawConsoleInput, enable_vt_output, read_event
from Test.TestCopy.data import build_sample_lines
from Test.TestCopy.model import CopyState, handle_named_key, handle_text_input, handle_wheel
from Test.TestCopy.render import compose, frame_to_ansi
from Test.TestCopy.snapshot import dump_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TestCopy standalone copy-mode playground")
    parser.add_argument("--width", type=int, default=80)
    parser.add_argument("--height", type=int, default=24)
    parser.add_argument("--lines", type=int, default=220)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = CopyState.create(build_sample_lines(args.lines), args.width, args.height)
    enable_vt_output()
    sys.stdout.write("\x1b[2J\x1b[H\x1b[?25l")
    sys.stdout.flush()

    try:
        with RawConsoleInput() as h_in:
            while state.running:
                frame = compose(state)
                dump_snapshot(state, frame, state.last_input)
                sys.stdout.write(frame_to_ansi(frame))
                sys.stdout.flush()

                kind, payload = read_event(h_in)
                if kind == "key":
                    handle_named_key(state, payload)
                elif kind == "text":
                    handle_text_input(state, payload)
                elif kind == "wheel":
                    handle_wheel(state, payload)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
