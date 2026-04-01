"""Interactive TestPane application."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from Test.TestPane.console import RawConsoleInput, enable_vt_output, read_event
from Test.TestPane.layout import (
    close_leaf,
    collect_leaves,
    find_neighbor,
    first_leaf,
    hit_test,
    layout,
    split_leaf,
)
from Test.TestPane.model import Direction, Leaf, MoveDirection, Pane, Rect, SplitNode
from Test.TestPane.render import compose, frame_to_ansi
from Test.TestPane.snapshot import dump_snapshot


@dataclass
class AppState:
    width: int
    height: int
    root: SplitNode | None
    focused_id: str | None
    focus_history: list[str]
    running: bool = True

    @classmethod
    def create(cls, width: int, height: int) -> AppState:
        root = Leaf(Pane("p1", "p1", Rect(0, 0, width, height)))
        layout(root, Rect(0, 0, width, height))
        return cls(width=width, height=height, root=root, focused_id="p1", focus_history=["p1"])

    def set_focus(self, pane_id: str | None) -> None:
        if pane_id is None or self.root is None:
            self.focused_id = None
            return
        alive = {pane.pane_id for pane in collect_leaves(self.root)}
        if pane_id not in alive:
            return
        self.focused_id = pane_id
        self.focus_history = [pid for pid in self.focus_history if pid != pane_id and pid in alive]
        self.focus_history.append(pane_id)

    def split(self, direction: Direction) -> bool:
        if self.root is None or self.focused_id is None:
            return False
        new_root, new_id = split_leaf(self.root, self.focused_id, direction)
        if new_id is None:
            return False
        self.root = new_root
        layout(self.root, Rect(0, 0, self.width, self.height))
        self.set_focus(new_id)
        return True

    def move(self, direction: MoveDirection) -> bool:
        if self.root is None or self.focused_id is None:
            return False
        neighbor = find_neighbor(self.root, self.focused_id, direction)
        if neighbor is None:
            return False
        self.set_focus(neighbor)
        return True

    def close_focused(self) -> bool:
        if self.root is None or self.focused_id is None:
            return False

        closed_id = self.focused_id
        new_root, replacement = close_leaf(self.root, closed_id)
        if new_root is None:
            self.root = None
            self.focused_id = None
            self.focus_history = []
            self.running = False
            return True

        self.root = new_root
        layout(self.root, Rect(0, 0, self.width, self.height))
        alive = {pane.pane_id for pane in collect_leaves(self.root)}
        self.focus_history = [pid for pid in self.focus_history if pid != closed_id and pid in alive]

        replacement_pane = first_leaf(replacement)
        next_focus = None
        for pane_id in reversed(self.focus_history):
            if pane_id in alive:
                next_focus = pane_id
                break
        if next_focus is None and replacement_pane is not None:
            next_focus = replacement_pane.pane_id
        if next_focus is None:
            fallback = first_leaf(self.root)
            next_focus = fallback.pane_id if fallback is not None else None

        self.set_focus(next_focus)
        return True

    def render_frame(self) -> list[list]:
        if self.root is None or self.focused_id is None:
            return []
        return compose(self.root, self.focused_id, self.width, self.height)

    def handle_mouse_click(self, x: int, y: int) -> bool:
        if self.root is None:
            return False
        pane_id = hit_test(self.root, x, y)
        if pane_id is None or pane_id == self.focused_id:
            return False
        self.set_focus(pane_id)
        return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TestPane standalone pane playground")
    parser.add_argument("--width", type=int, default=60)
    parser.add_argument("--height", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = AppState.create(args.width, args.height)
    enable_vt_output()
    sys.stdout.write("\x1b[2J\x1b[H\x1b[?25l")
    sys.stdout.flush()

    try:
        with RawConsoleInput() as h_in:
            last_input = "init"
            while state.running and state.root is not None and state.focused_id is not None:
                frame = state.render_frame()
                dump_snapshot(state, frame, last_input)
                sys.stdout.write(frame_to_ansi(frame))
                sys.stdout.flush()

                event = read_event(h_in)
                if event is None:
                    continue

                if event[0] == "key":
                    key = event[1]
                    last_input = f"key:{key}"
                    if key == "q":
                        break
                    if key == "v":
                        state.split(Direction.VERTICAL)
                    elif key == "h":
                        state.split(Direction.HORIZONTAL)
                    elif key == "x":
                        state.close_focused()
                    elif key == "left":
                        state.move(MoveDirection.LEFT)
                    elif key == "right":
                        state.move(MoveDirection.RIGHT)
                    elif key == "up":
                        state.move(MoveDirection.UP)
                    elif key == "down":
                        state.move(MoveDirection.DOWN)
                elif event[0] == "mouse":
                    _, x, y = event
                    last_input = f"mouse:left@({x},{y})"
                    state.handle_mouse_click(x, y)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
