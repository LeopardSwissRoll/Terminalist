"""Terminalist — Terminal multiplexer with compositor rendering.

Multi-pane terminal multiplexer. Each pane runs a PTY session
(PowerShell, Claude, Codex) rendered via pyte + compositor diff.

Usage:
    python -m terminalist.app [--debug]
    terminalist [--debug]

Keys (Ctrl+B prefix):
    v/h     split vertical/horizontal
    arrows  focus pane
    x       close pane
    z       zoom (toggle fullscreen)
    s       new shell
    c       new Claude session
    o       new Codex session
    Ctrl+C  quit
    Ctrl+B  send literal Ctrl+B
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from terminalist.core.pane import Pane, Rect
from terminalist.core.session_manager import SessionManager
from terminalist.core.terminal_session import SessionState
from terminalist.debug import init_debug, log, detect_env
from terminalist.events.tes import EventStreamManager
from terminalist.frontend.compositor import Compositor
from terminalist.frontend.split_tree import (
    Direction,
    Leaf,
    Split,
    SplitNode,
    all_panes,
    can_split,
    find_neighbor,
    hit_test,
    layout,
    remove_pane,
    split_pane,
)
from terminalist.frontend.vt100_writer import VT100Writer
from terminalist.input.handler import InputState, process_events
from terminalist.input.win32 import (
    RawConsoleInput,
    enable_vt,
    enter_alt_screen,
    exit_alt_screen,
    has_events,
    read_batch,
    terminal_size,
)
from terminalist.pyte_patch import apply as patch_pyte


class App:
    """Terminalist multi-pane terminal multiplexer."""

    def __init__(self, debug: bool = False, debug_log: str | None = None) -> None:
        init_debug(enabled=debug, log_path=debug_log)
        patch_pyte()
        enable_vt()

        self._tes = EventStreamManager()
        self._sm = SessionManager(self._tes)
        self._root: SplitNode | None = None
        self._focused: Pane | None = None
        self._writer = VT100Writer()
        self._compositor: Compositor | None = None
        self._running = False
        self._pane_counter = 0
        self._input_state = InputState()

        # Zoom state
        self._zoom_pane: Pane | None = None
        self._pre_zoom_root: SplitNode | None = None

        # Delayed redraw after split/resize (give PTY time to re-render)
        self._pending_redraw_at: float = 0.0

    def run(self) -> None:
        """Main entry point."""
        env = detect_env()
        rows, cols = terminal_size()
        log("app", f"=== Terminalist starting (env={env}, {cols}x{rows}) ===")

        # Redirect stderr to debug log so tracebacks are captured
        # even when alt screen is active (stderr would be invisible)
        import io
        stderr_log = open(f"terminalist_stderr_{env}.log", "w", encoding="utf-8")
        old_stderr = sys.stderr
        sys.stderr = stderr_log
        log("app", f"stderr redirected to terminalist_stderr_{env}.log")

        enter_alt_screen()
        self._compositor = Compositor(cols, rows, self._writer)

        # Create initial shell pane
        pane = self._create_pane("powershell")
        self._root = Leaf(pane)
        self._focused = None  # _set_focus will set it
        self._set_focus(pane)
        layout(self._root, Rect(0, 0, cols, rows))
        self._compositor.full_redraw()

        self._running = True

        # SIGINT → forward to active PTY
        prev_handler = signal.getsignal(signal.SIGINT)
        def on_sigint(_s, _f):
            if self._focused:
                try:
                    self._focused.write_raw("\x03")
                except Exception:
                    pass
        signal.signal(signal.SIGINT, on_sigint)

        try:
            with RawConsoleInput() as h_in:
                self._main_loop(h_in)
        except Exception as e:
            log("app", f"CRASHED: {type(e).__name__}: {e}")
            import traceback
            log("app", traceback.format_exc())
        finally:
            signal.signal(signal.SIGINT, prev_handler)
            self._cleanup()
            exit_alt_screen()
            # Restore stderr
            sys.stderr = old_stderr
            stderr_log.close()
            log("app", "=== Terminalist exited ===")
            print("[terminalist] Session ended.")

    def _main_loop(self, h_in: int) -> None:
        """Tick loop: input → render."""
        last_size = terminal_size()

        while self._running:
            # Any pane alive?
            if self._root is None:
                break
            panes = all_panes(self._root)
            if not panes:
                break
            if not any(p.session.is_alive() for p in panes):
                break

            # ── Resize check ──
            new_size = terminal_size()
            if new_size != last_size:
                last_size = new_size
                rows, cols = new_size
                self._compositor.resize(cols, rows)
                layout(self._root, Rect(0, 0, cols, rows))
                self._compositor.full_redraw()
                log("app", f"Terminal resized: {cols}x{rows}")

            # ── Input ──
            if has_events(h_in):
                keys, mice = read_batch(h_in)

                # Mouse events
                for me in mice:
                    if me.flags & 0x0004:  # MOUSE_WHEELED
                        direction = "up" if me.buttons & 0x80000000 else "down"
                        log("mouse", f"scroll {direction} at ({me.x},{me.y})")
                    elif me.buttons == 0x0001 and me.flags == 0:  # LEFT_CLICK (not drag)
                        # Click-to-focus: hit test → set focus
                        clicked = hit_test(self._root, me.x, me.y) if self._root else None
                        if clicked and clicked != self._focused:
                            self._set_focus(clicked)
                            log("mouse", f"click → focus {clicked.pane_id} at ({me.x},{me.y})")
                        else:
                            log("mouse", f"click at ({me.x},{me.y}) (no pane change)")

                if keys:
                    write_target = self._focused.write_raw if self._focused else lambda s: None
                    result = process_events(
                        keys,
                        write_target,
                        self._input_state,
                        on_prefix_key=self._dispatch_prefix,
                        h_in=h_in,
                    )
                    if result == "exit":
                        break
            else:
                time.sleep(0.01)

            # ── Pending full redraw (after split/resize, PTY had time to re-render) ──
            if self._pending_redraw_at and time.monotonic() >= self._pending_redraw_at:
                self._pending_redraw_at = 0.0
                self._compositor.full_redraw()

            # ── Render ──
            if self._compositor.needs_render() and self._root:
                rows, cols = last_size
                rect = Rect(0, 0, cols, rows)
                self._compositor.render(self._root, rect, self._focused)

    # ── Pane creation ──

    def _create_pane(self, provider: str) -> Pane:
        """Create a new pane with a PTY session."""
        self._pane_counter += 1
        pane_id = f"pane_{self._pane_counter}"

        workspace = "."
        if self._focused and hasattr(self._focused.session, "current_dir"):
            workspace = str(self._focused.session.current_dir)

        session = self._sm.create(provider, workspace=workspace)
        pane = Pane(pane_id, session)

        # Connect dirty listener → compositor
        session.add_dirty_listener(self._compositor.mark_dirty)

        # Track bracketed paste from PTY output
        session.add_raw_output_listener(self._input_state.track_bracketed_paste)

        log("app", f"Created pane {pane_id} ({provider}) session={session.session_id}")
        return pane

    # ── Focus management ──

    def _set_focus(self, pane: Pane) -> None:
        """Single entry point for all focus changes.

        Ensures blur()/focus() contract (enter_manual/exit_manual) is
        always honored. Marks compositor dirty for border highlight update.
        """
        if self._focused is pane:
            return
        if self._focused:
            self._focused.blur()
        self._focused = pane
        pane.focus()
        self._compositor.mark_dirty()
        log("focus", f"Focus → {pane.pane_id}")

    # ── Prefix action dispatch ──

    def _dispatch_prefix(self, action: str, input_count: int) -> None:
        """Handle prefix key action from keymap."""
        log("app", f"Prefix action: {action}")

        match action:
            case "split_vertical":
                self._split(Direction.VERTICAL)
            case "split_horizontal":
                self._split(Direction.HORIZONTAL)
            case "close_pane":
                self._close_pane()
            case "focus_pane_up":
                self._focus_direction(Direction.HORIZONTAL, False)
            case "focus_pane_down":
                self._focus_direction(Direction.HORIZONTAL, True)
            case "focus_pane_left":
                self._focus_direction(Direction.VERTICAL, False)
            case "focus_pane_right":
                self._focus_direction(Direction.VERTICAL, True)
            case "new_shell":
                self._new_session_split("powershell")
            case "new_claude":
                self._new_session_split("claude")
            case "new_codex":
                self._new_session_split("codex")
            case "zoom_pane":
                self._toggle_zoom()
            case "confirm_quit" | "detach":
                self._running = False
            case "send_prefix_char":
                if self._focused:
                    self._focused.write_raw("\x02")
            case _:
                log("app", f"Unhandled prefix action: {action}")

    # ── Split ──

    def _split(self, direction: Direction) -> None:
        if not self._focused or not self._root:
            return
        if not can_split(self._focused.rect, direction):
            log("app", "Split rejected: pane too small")
            return

        new_pane = self._create_pane("powershell")
        self._root = split_pane(self._root, self._focused.pane_id, new_pane, direction)
        rows, cols = terminal_size()
        layout(self._root, Rect(0, 0, cols, rows))
        # Don't full_redraw immediately — PTY needs time to re-render after resize.
        # mark_dirty lets the next tick render after PTY output arrives.
        self._compositor.mark_dirty()
        # But also schedule a delayed full_redraw to catch PTY re-renders
        self._pending_redraw_at = time.monotonic() + 0.2
        log("app", f"Split {direction.value}: {self._focused.pane_id} + {new_pane.pane_id}")

    # ── Close pane ──

    def _close_pane(self) -> None:
        if not self._focused or not self._root:
            return

        # If zoomed, exit zoom first and operate on the real tree
        if self._zoom_pane:
            real_root = self._pre_zoom_root
            self._zoom_pane = None
            self._pre_zoom_root = None
            self._root = real_root

        old_id = self._focused.pane_id
        old_session_id = self._focused.session.session_id

        # Find a neighbor to focus after close
        neighbor = (
            find_neighbor(self._root, old_id, Direction.VERTICAL, True)
            or find_neighbor(self._root, old_id, Direction.VERTICAL, False)
            or find_neighbor(self._root, old_id, Direction.HORIZONTAL, True)
            or find_neighbor(self._root, old_id, Direction.HORIZONTAL, False)
        )

        # Remove from tree
        self._root = remove_pane(self._root, old_id)
        self._sm.destroy(old_session_id)

        if self._root is None:
            self._running = False
            return

        # Focus neighbor
        new_focus = neighbor or all_panes(self._root)[0]
        self._set_focus(new_focus)

        rows, cols = terminal_size()
        layout(self._root, Rect(0, 0, cols, rows))
        self._pending_redraw_at = time.monotonic() + 0.2
        log("app", f"Closed pane {old_id}, focused {self._focused.pane_id}")

    # ── Focus navigation ──

    def _focus_direction(self, direction: Direction, toward_second: bool) -> None:
        if not self._focused or not self._root:
            return
        neighbor = find_neighbor(self._root, self._focused.pane_id, direction, toward_second)
        if neighbor and neighbor != self._focused:
            self._set_focus(neighbor)

    # ── New session in split ──

    def _new_session_split(self, provider: str) -> None:
        """Create new session in a vertical split."""
        if not self._focused or not self._root:
            return
        direction = Direction.VERTICAL
        if not can_split(self._focused.rect, direction):
            direction = Direction.HORIZONTAL
            if not can_split(self._focused.rect, direction):
                log("app", f"Cannot split for new {provider}: too small")
                return

        new_pane = self._create_pane(provider)
        self._root = split_pane(self._root, self._focused.pane_id, new_pane, direction)

        # Focus the new pane
        self._set_focus(new_pane)

        rows, cols = terminal_size()
        layout(self._root, Rect(0, 0, cols, rows))
        self._pending_redraw_at = time.monotonic() + 0.2
        log("app", f"New {provider} session in split: {new_pane.pane_id}")

    # ── Zoom ──

    def _toggle_zoom(self) -> None:
        if not self._focused or not self._root:
            return

        if self._zoom_pane:
            # Restore from zoom
            self._root = self._pre_zoom_root
            self._zoom_pane = None
            self._pre_zoom_root = None
            log("app", "Zoom OFF")
        else:
            # Zoom focused pane
            self._pre_zoom_root = self._root
            self._zoom_pane = self._focused
            self._root = Leaf(self._focused)
            log("app", f"Zoom ON: {self._focused.pane_id}")

        rows, cols = terminal_size()
        layout(self._root, Rect(0, 0, cols, rows))
        self._compositor.mark_dirty()
        self._pending_redraw_at = time.monotonic() + 0.2

    # ── Cleanup ──

    def _cleanup(self) -> None:
        if self._root:
            for pane in all_panes(self._root):
                try:
                    self._sm.destroy(pane.session.session_id)
                except Exception:
                    pass
        self._tes.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Terminalist — LLM CLI terminal multiplexer")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    p.add_argument("--debug-log", type=str, default=None, help="Debug log file path")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    app = App(debug=args.debug, debug_log=args.debug_log)
    app.run()


if __name__ == "__main__":
    main()
