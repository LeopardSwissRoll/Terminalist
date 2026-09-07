"""Terminalist — Terminal multiplexer with compositor rendering.

Multi-pane terminal multiplexer. Each pane runs a PTY session
(PowerShell, Claude, Codex) rendered via pyte + compositor diff.

Usage:
    python -m terminalist.app [--debug]
    terminalist [--debug]

Keys (Ctrl+B prefix):
    w       new window
    v/h     split vertical/horizontal
    arrows  focus pane
    Ctrl+arrows  resize pane
    x       close pane
    z       zoom (toggle fullscreen)
    s       new shell
    c       new Claude session
    o       new Codex session
    n/p/1-5 switch windows
    Ctrl+C  quit
    Ctrl+B  send literal Ctrl+B
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from pyte.screens import Char

from terminalist.clipboard import copy_text
from terminalist.core.copy_mode import handle_named_key, handle_text_input
from terminalist.core.pane import Pane, Rect
from terminalist.core.session_manager import SessionManager
from terminalist.debug import detect_env, init_debug, log
from terminalist.events.tes import EventStreamManager
from terminalist.frontend.compositor import Compositor
from terminalist.frontend.split_tree import (
    Direction,
    Leaf,
    all_panes,
    can_split,
    find_neighbor,
    hit_test,
    remove_pane,
    split_pane,
    adjust_ratio,
)
from terminalist.frontend.vt100_writer import VT100Writer
from terminalist.frontend.window_state import WindowState
from terminalist.input.handler import InputState, _read_prefix_action, process_events
from terminalist.input.win32 import (
    MOUSE_WHEELED,
    RawConsoleInput,
    enable_vt,
    enter_alt_screen,
    exit_alt_screen,
    has_events,
    read_batch,
    terminal_size,
)
from terminalist.pyte_patch import apply as patch_pyte

_CTRL_PRESSED_MASK = 0x0004 | 0x0008
_SHIFT_PRESSED_MASK = 0x0010
_COPY_SPECIAL_KEYS = {
    0x25: "left",
    0x27: "right",
    0x26: "up",
    0x28: "down",
    0x21: "page_up",
    0x22: "page_down",
    0x24: "home",
    0x23: "end",
}


class App:
    """Terminalist multi-pane terminal multiplexer."""

    def __init__(self, debug: bool = False, debug_log: str | None = None) -> None:
        init_debug(enabled=debug, log_path=debug_log)
        patch_pyte()
        enable_vt()

        self._tes = EventStreamManager()
        self._sm = SessionManager(self._tes)
        self._windows: list[WindowState] = []
        self._active_window_idx = 0
        self._window_history: list[str] = []
        self._writer = VT100Writer()
        self._compositor: Compositor | None = None
        self._running = False
        self._pane_counter = 0
        self._window_counter = 0
        self._input_state = InputState()
        self._render_interval_s = 0.016
        self._last_render_at = 0.0
        self._next_render_at = 0.0
        self._render_immediate_requested = False
        self._followup_redraw_at = 0.0

    def run(self) -> None:
        """Main entry point."""
        env = detect_env()
        rows, cols = terminal_size()
        log("app", f"=== Terminalist starting (env={env}, {cols}x{rows}) ===")

        stderr_log = open(f"terminalist_stderr_{env}.log", "w", encoding="utf-8")
        old_stderr = sys.stderr
        sys.stderr = stderr_log
        log("app", f"stderr redirected to terminalist_stderr_{env}.log")

        enter_alt_screen()
        self._compositor = Compositor(cols, rows, self._writer)
        self._bootstrap_initial_window(rows, cols)

        self._running = True

        prev_handler = signal.getsignal(signal.SIGINT)

        def on_sigint(_s, _f):
            active_pane = self._active_pane()
            if active_pane:
                try:
                    active_pane.write_raw("\x03")
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
            sys.stderr = old_stderr
            stderr_log.close()
            log("app", "=== Terminalist exited ===")
            print("[terminalist] Session ended.")

    def _request_render(
        self,
        immediate: bool = False,
        *,
        full: bool = False,
        follow_up_delay: float | None = None,
    ) -> None:
        if self._compositor is None:
            return

        if full:
            self._compositor.full_redraw()
        else:
            self._compositor.mark_dirty()

        now = time.monotonic()
        if immediate:
            self._render_immediate_requested = True
            self._next_render_at = now
        elif not self._render_immediate_requested:
            deadline = max(now, self._last_render_at + self._render_interval_s)
            if self._next_render_at <= 0.0 or deadline < self._next_render_at:
                self._next_render_at = deadline

        if follow_up_delay is not None:
            follow_up_at = now + follow_up_delay
            if self._followup_redraw_at <= 0.0 or follow_up_at < self._followup_redraw_at:
                self._followup_redraw_at = follow_up_at

    def _render_due(self, now: float) -> bool:
        if self._compositor is None or not self._compositor.needs_render():
            return False
        if self._render_immediate_requested:
            return True
        if self._next_render_at <= 0.0:
            return True
        return now >= self._next_render_at

    def _note_rendered(self, now: float) -> None:
        self._last_render_at = now
        self._next_render_at = 0.0
        self._render_immediate_requested = False

    def _main_loop(self, h_in: int) -> None:
        """Tick loop: input → render."""
        last_size = terminal_size()

        while self._running:
            if not self._windows:
                break

            panes = self._all_panes()
            if not panes:
                break
            if not any(p.session.is_alive() for p in panes):
                break

            new_size = terminal_size()
            if new_size != last_size:
                last_size = new_size
                rows, cols = new_size
                self._compositor.resize(cols, rows)
                active_window = self._active_window()
                if active_window is not None:
                    self._layout_window(active_window, rows, cols)
                for index, window in enumerate(self._windows):
                    if index != self._active_window_idx:
                        window.needs_layout = True
                self._request_render(immediate=True, full=True, follow_up_delay=0.2)
                log("app", f"Terminal resized: {cols}x{rows}")

            if has_events(h_in):
                keys, mice = read_batch(h_in)

                for me in mice:
                    self._handle_mouse_event(me)

                if keys:
                    keys = self._consume_global_copy_shortcut(keys)
                    active_pane = self._active_pane()
                    if active_pane and active_pane.in_copy_mode:
                        self._process_copy_input(keys, h_in)
                    elif keys:
                        write_target = active_pane.write_raw if active_pane else (lambda s: None)
                        result = process_events(
                            keys,
                            write_target,
                            self._input_state,
                            on_prefix_key=self._dispatch_prefix,
                            on_mouse_event=self._handle_mouse_event,
                            h_in=h_in,
                        )
                        if result == "exit":
                            break
            else:
                time.sleep(0.01)

            now = time.monotonic()
            if self._followup_redraw_at and now >= self._followup_redraw_at:
                self._followup_redraw_at = 0.0
                self._request_render(immediate=True, full=True)

            active_window = self._active_window()
            active_root = active_window.active_root() if active_window else None
            if self._render_due(now) and active_root:
                render_mode = "immediate" if self._render_immediate_requested else "batched"
                log("render", f"{render_mode} render")
                rows, cols = last_size
                self._compositor.render(
                    active_root,
                    self._pane_area_rect(rows, cols),
                    active_window.focused,
                    status_line=self._build_status_line(cols),
                    status_y=self._status_line_y(rows),
                )
                self._note_rendered(now)

    # ── Window helpers ──

    def _bootstrap_initial_window(self, rows: int, cols: int) -> None:
        pane = self._create_pane("powershell")
        window = self._create_window_state(pane)
        self._windows = [window]
        self._active_window_idx = 0
        self._activate_window(0, size=(rows, cols))

    def _create_window_state(self, pane: Pane) -> WindowState:
        self._window_counter += 1
        window = WindowState(window_id=f"window_{self._window_counter}", root=Leaf(pane))
        window.set_focus(pane)
        return window

    def _active_window(self) -> WindowState | None:
        if not self._windows:
            return None
        if not (0 <= self._active_window_idx < len(self._windows)):
            return None
        return self._windows[self._active_window_idx]

    def _active_pane(self) -> Pane | None:
        window = self._active_window()
        return window.focused if window else None

    def _all_panes(self) -> list[Pane]:
        panes: list[Pane] = []
        for window in self._windows:
            panes.extend(window.all_panes())
        return panes

    def _window_by_id(self, window_id: str) -> WindowState | None:
        for window in self._windows:
            if window.window_id == window_id:
                return window
        return None

    def _activate_window(self, index: int, size: tuple[int, int] | None = None) -> None:
        if not (0 <= index < len(self._windows)):
            return

        previous = self._active_window()
        target = self._windows[index]
        same_window = previous is target

        if previous is not None and not same_window:
            previous.deactivate()

        self._active_window_idx = index
        if not target.is_active:
            target.activate()

        self._window_history = [wid for wid in self._window_history if wid != target.window_id]
        self._window_history.append(target.window_id)

        rows, cols = size or terminal_size()
        if target.needs_layout or target.last_layout_size != (rows, cols):
            self._layout_window(target, rows, cols)

        self._request_render(immediate=True, full=True)
        log("window", f"Activate → slot={index + 1} id={target.window_id}")

    def _layout_window(self, window: WindowState, rows: int, cols: int) -> None:
        window.layout(self._pane_area_rect(rows, cols), terminal_size=(rows, cols))

    def _clear_zoom_for_mutation(self, window: WindowState) -> None:
        if window.zoom_pane is None:
            return
        window.clear_zoom()
        rows, cols = terminal_size()
        self._layout_window(window, rows, cols)

    # ── Pane / window creation ──

    def _create_pane(self, provider: str) -> Pane:
        """Create a new pane with a PTY session."""
        self._pane_counter += 1
        pane_id = f"pane_{self._pane_counter}"

        workspace = "."
        active_pane = self._active_pane()
        if active_pane and hasattr(active_pane.session, "current_dir"):
            workspace = str(active_pane.session.current_dir)

        session = self._sm.create(provider, workspace=workspace)
        pane = Pane(pane_id, session)

        session.add_dirty_listener(lambda p=pane: self._mark_dirty_for_pane(p))
        session.add_raw_output_listener(self._input_state.track_bracketed_paste)

        log("app", f"Created pane {pane_id} ({provider}) session={session.session_id}")
        return pane

    def _new_window(self, provider: str = "powershell") -> None:
        new_pane = self._create_pane(provider)
        window = self._create_window_state(new_pane)
        self._windows.append(window)
        self._activate_window(len(self._windows) - 1)
        log("window", f"New window {window.window_id} provider={provider}")

    def _mark_dirty_for_pane(self, pane: Pane) -> None:
        active_window = self._active_window()
        if active_window is None:
            return
        if any(candidate is pane for candidate in active_window.visible_panes()):
            self._request_render(immediate=False)

    @staticmethod
    def _copy_mode_boundary_changed(before: str | None, after: str | None) -> bool:
        return before != after

    # ── Mouse / focus ──

    def _handle_mouse_event(self, me) -> None:
        active_window = self._active_window()
        active_root = active_window.active_root() if active_window else None

        if me.flags & MOUSE_WHEELED:
            # Windows sets the sign bit for wheel-up, but our viewport model is
            # intentionally inverted from raw wheel direction:
            #   wheel-up   -> move down toward live output
            #   wheel-down -> move up into scrollback history
            direction = "down" if me.buttons & 0x80000000 else "up"
            target = hit_test(active_root, me.x, me.y) if active_root else None
            if target is None:
                target = active_window.focused if active_window else None
            if target is None:
                log("mouse", f"scroll {direction} at ({me.x},{me.y}) (no target)")
                return

            mode_before = target.copy_mode_state.mode if target.copy_mode_state is not None else "live"
            changed = target.scroll_up() if direction == "up" else target.scroll_down()
            mode_after = target.copy_mode_state.mode if target.copy_mode_state is not None else "live"
            if changed:
                self._request_render(
                    immediate=True,
                    full=self._copy_mode_boundary_changed(mode_before, mode_after),
                )
                log(
                    "mouse",
                    f"scroll {direction} pane={target.pane_id} offset={target.scroll_offset} at ({me.x},{me.y})",
                )
            else:
                log(
                    "mouse",
                    f"scroll {direction} pane={target.pane_id} unchanged offset={target.scroll_offset} at ({me.x},{me.y})",
                )
            return

        if me.buttons == 0x0001 and me.flags == 0:
            clicked = hit_test(active_root, me.x, me.y) if active_root else None
            if clicked and active_window and clicked is not active_window.focused:
                active_window.set_focus(clicked)
                self._request_render(immediate=True)
                log("mouse", f"click → focus {clicked.pane_id} at ({me.x},{me.y})")
            else:
                log("mouse", f"click at ({me.x},{me.y}) (no pane change)")

    def _consume_global_copy_shortcut(self, keys) -> list:
        active_pane = self._active_pane()
        if active_pane is None:
            return keys

        remaining = []
        entered = False
        for event in keys:
            ch, vk, ctrl, repeat = event
            if vk == 0x43 and (ctrl & _CTRL_PRESSED_MASK) and (ctrl & _SHIFT_PRESSED_MASK):
                active_pane.enter_copy_mode()
                entered = True
                continue
            remaining.append(event)

        if entered:
            self._request_render(immediate=True, full=True)
            log("app", f"Enter copy mode: {active_pane.pane_id} via Ctrl+Shift+C")
        return remaining

    def _process_copy_input(self, keys, h_in: int) -> None:
        handled = False
        full_redraw = False

        for ch, vk, ctrl, repeat in keys:
            active_pane = self._active_pane()
            if active_pane is None:
                break
            active_pane.sync_copy_mode()
            state = active_pane.copy_mode_state
            if state is None:
                break
            mode_before = state.mode

            self._input_state.input_count += 1
            n = self._input_state.input_count

            if ch == "\x02":
                action = _read_prefix_action(h_in, active_pane.write_raw, n)
                if action:
                    self._dispatch_prefix(action, n)
                    handled = True
                continue

            if vk in _COPY_SPECIAL_KEYS and ch is None:
                handle_named_key(state, _COPY_SPECIAL_KEYS[vk])
                handled = True
                continue

            if state.mode == "search":
                if ch in ("\r", "\n"):
                    handle_named_key(state, "enter")
                    handled = True
                elif ch == "\x1b":
                    handle_named_key(state, "esc")
                    handled = True
                elif ch == "\x08":
                    handle_named_key(state, "backspace")
                    handled = True
                elif ch and ord(ch) >= 0x20:
                    handle_text_input(state, ch)
                    handled = True
                if self._copy_mode_boundary_changed(mode_before, state.mode):
                    full_redraw = True
                continue

            if ch in ("\r", "\n"):
                copied_before = state.copied_text
                mode_before = state.mode
                handle_named_key(state, "enter")
                if mode_before != "live" and state.mode == "live" and state.copied_text:
                    copied = state.copied_text
                    clipboard_ok = copy_text(copied)
                    if clipboard_ok:
                        log("copy", f"[pane:{active_pane.pane_id}] copied {len(copied)} chars to clipboard")
                    else:
                        log("copy", f"[pane:{active_pane.pane_id}] clipboard fallback ({len(copied)} chars)")
                    if copied_before == copied:
                        log("copy", f"[pane:{active_pane.pane_id}] copied same text again")
                handled = True
            elif ch == "\x1b":
                handle_named_key(state, "esc")
                handled = True
            elif ch == "\x08":
                handle_named_key(state, "backspace")
                handled = True
            elif ch == "/":
                handle_named_key(state, "search")
                handled = True
            elif ch == " ":
                handle_named_key(state, "space")
                handled = True
            elif ch == "n":
                handle_named_key(state, "next_match")
                handled = True
            elif ch == "N":
                handle_named_key(state, "prev_match")
                handled = True

            if self._copy_mode_boundary_changed(mode_before, state.mode):
                full_redraw = True

        if handled:
            self._request_render(immediate=True, full=full_redraw)

    # ── Prefix action dispatch ──

    def _dispatch_prefix(self, action: str, input_count: int) -> None:
        log("app", f"Prefix action: {action}")

        match action:
            case "new_window":
                self._new_window("powershell")
            case "enter_copy_mode":
                active_pane = self._active_pane()
                if active_pane:
                    active_pane.enter_copy_mode()
                    self._request_render(immediate=True, full=True)
            case "next_tab":
                self._cycle_window(1)
            case "prev_tab":
                self._cycle_window(-1)
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
            case "resize_pane_up":
                self._resize_pane(Direction.HORIZONTAL, toward_second=False)
            case "resize_pane_down":
                self._resize_pane(Direction.HORIZONTAL, toward_second=True)
            case "resize_pane_left":
                self._resize_pane(Direction.VERTICAL, toward_second=False)
            case "resize_pane_right":
                self._resize_pane(Direction.VERTICAL, toward_second=True)
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
                active_pane = self._active_pane()
                if active_pane:
                    active_pane.write_raw("\x02")
            case _ if action.startswith("goto_tab_"):
                try:
                    slot = int(action.rsplit("_", 1)[1]) - 1
                except ValueError:
                    return
                self._goto_window_slot(slot)
            case _:
                log("app", f"Unhandled prefix action: {action}")

    def _cycle_window(self, delta: int) -> None:
        if len(self._windows) <= 1:
            return
        new_index = (self._active_window_idx + delta) % len(self._windows)
        self._activate_window(new_index)

    def _goto_window_slot(self, slot: int) -> None:
        if 0 <= slot < len(self._windows):
            self._activate_window(slot)

    # ── Split / close / focus / resize ──

    def _split(self, direction: Direction) -> None:
        window = self._active_window()
        if window is None or window.focused is None or window.root is None:
            return

        self._clear_zoom_for_mutation(window)

        if not can_split(window.focused.content_rect, direction):
            log("app", "Split rejected: pane too small")
            return

        source_pane = window.focused
        new_pane = self._create_pane("powershell")
        window.root = split_pane(window.root, source_pane.pane_id, new_pane, direction)
        window.set_focus(new_pane)

        rows, cols = terminal_size()
        self._layout_window(window, rows, cols)
        self._request_render(immediate=True, full=True, follow_up_delay=0.2)
        log("app", f"Split {direction.value}: {source_pane.pane_id} + {new_pane.pane_id} (focus={new_pane.pane_id})")

    def _close_pane(self) -> None:
        window = self._active_window()
        if window is None or window.focused is None or window.root is None:
            return

        self._clear_zoom_for_mutation(window)

        old_pane = window.focused
        old_id = old_pane.pane_id
        old_session_id = old_pane.session.session_id

        neighbor = (
            find_neighbor(window.root, old_id, Direction.VERTICAL, True)
            or find_neighbor(window.root, old_id, Direction.VERTICAL, False)
            or find_neighbor(window.root, old_id, Direction.HORIZONTAL, True)
            or find_neighbor(window.root, old_id, Direction.HORIZONTAL, False)
        )

        window.root, replacement = remove_pane(window.root, old_id)
        if window.zoom_pane is old_pane:
            window.clear_zoom()
        self._sm.destroy(old_session_id)

        if window.root is None:
            old_window_id = window.window_id
            window.deactivate()
            del self._windows[self._active_window_idx]
            self._window_history = [wid for wid in self._window_history if wid != old_window_id]

            if not self._windows:
                self._running = False
                return

            new_index = None
            for window_id in reversed(self._window_history):
                candidate = self._window_by_id(window_id)
                if candidate is None:
                    continue
                new_index = self._windows.index(candidate)
                break

            if new_index is None:
                new_index = min(self._active_window_idx, len(self._windows) - 1)

            self._activate_window(new_index)
            self._request_render(immediate=True, full=True, follow_up_delay=0.2)
            log("window", f"Closed last pane in {old_window_id}, active slot={self._active_window_idx + 1}")
            return

        alive = {pane.pane_id: pane for pane in window.all_panes()}
        window.focus_history = [
            pane_id for pane_id in window.focus_history
            if pane_id != old_id and pane_id in alive
        ]

        new_focus = None
        for pane_id in reversed(window.focus_history):
            new_focus = alive.get(pane_id)
            if new_focus is not None:
                break

        if new_focus is None and replacement is not None:
            replacement_panes = all_panes(replacement)
            if replacement_panes:
                new_focus = replacement_panes[0]

        if new_focus is None:
            new_focus = neighbor or window.all_panes()[0]

        window.set_focus(new_focus)
        rows, cols = terminal_size()
        self._layout_window(window, rows, cols)
        self._request_render(immediate=True, full=True, follow_up_delay=0.2)
        log("app", f"Closed pane {old_id}, focused {window.focused.pane_id}")

    def _focus_direction(self, direction: Direction, toward_second: bool) -> None:
        window = self._active_window()
        active_root = window.active_root() if window else None
        if window is None or window.focused is None or active_root is None:
            return
        neighbor = find_neighbor(active_root, window.focused.pane_id, direction, toward_second)
        if neighbor and neighbor is not window.focused:
            window.set_focus(neighbor)
            self._request_render(immediate=True)

    def _resize_pane(self, direction: Direction, toward_second: bool) -> None:
        window = self._active_window()
        if window is None or window.focused is None or window.root is None:
            return
        if window.zoom_pane is not None:
            log("layout", "Resize ignored: window is zoomed")
            return

        delta = 0.05 if toward_second else -0.05
        if not adjust_ratio(window.root, window.focused.pane_id, direction, delta):
            log(
                "layout",
                f"Resize ignored: pane={window.focused.pane_id} dir={direction.value} delta={delta:+.2f}",
            )
            return

        rows, cols = terminal_size()
        self._layout_window(window, rows, cols)
        self._request_render(immediate=True, full=True, follow_up_delay=0.2)
        log(
            "layout",
            f"Resize applied: pane={window.focused.pane_id} dir={direction.value} delta={delta:+.2f}",
        )

    def _new_session_split(self, provider: str) -> None:
        window = self._active_window()
        if window is None or window.focused is None or window.root is None:
            return

        self._clear_zoom_for_mutation(window)

        direction = Direction.VERTICAL
        if not can_split(window.focused.content_rect, direction):
            direction = Direction.HORIZONTAL
            if not can_split(window.focused.content_rect, direction):
                log("app", f"Cannot split for new {provider}: too small")
                return

        new_pane = self._create_pane(provider)
        window.root = split_pane(window.root, window.focused.pane_id, new_pane, direction)
        window.set_focus(new_pane)

        rows, cols = terminal_size()
        self._layout_window(window, rows, cols)
        self._request_render(immediate=True, full=True, follow_up_delay=0.2)
        log("app", f"New {provider} session in split: {new_pane.pane_id}")

    def _toggle_zoom(self) -> None:
        window = self._active_window()
        if window is None or window.focused is None or window.root is None:
            return

        zoom_on = window.toggle_zoom()
        log("app", f"Zoom {'ON' if zoom_on else 'OFF'}: {window.focused.pane_id}")

        rows, cols = terminal_size()
        self._layout_window(window, rows, cols)
        self._request_render(immediate=True, full=True, follow_up_delay=0.2)

    # ── Chrome ──

    @staticmethod
    def _pane_area_rect(rows: int, cols: int) -> Rect:
        return Rect(0, 0, cols, max(1, rows - 1))

    @staticmethod
    def _status_line_y(rows: int) -> int:
        return max(0, rows - 1)

    def _build_status_line(self, width: int) -> list[Char]:
        base = Char(" ", "white", "bright_black", False, False, False, False, False, False)
        chars = [base for _ in range(max(0, width))]
        if width <= 0:
            return chars

        x = 0
        for slot, window in enumerate(self._windows, start=1):
            active = slot - 1 == self._active_window_idx
            label = self._window_label(window)
            segment = f"[{'*' if active else ' '}{slot}:{label}] "
            x = self._write_status_segment(
                chars,
                x,
                segment,
                fg="green" if active else "white",
                bold=active,
            )
            if x >= width:
                return chars

        active_window = self._active_window()
        active_pane = active_window.focused if active_window else None
        if active_pane is None:
            return chars

        provider = self._provider_label(active_pane)
        state = getattr(getattr(active_pane.session, "state", None), "value", None)
        copy_state = active_pane.copy_mode_state
        if copy_state is not None and copy_state.mode != "live":
            total = copy_state.line_count
            start = copy_state.viewport_top + 1 if total else 0
            end = min(total, copy_state.viewport_top + copy_state.viewport_height)
            selection = "yes" if copy_state.selection is not None else "no"
            right_segment = (
                f"[{copy_state.mode.upper()} "
                f"{start}-{end}/{total} "
                f"L{copy_state.cursor_line_abs + 1} C{copy_state.cursor_col + 1} "
                f"sel={selection} "
                f"q={copy_state.search.query!r} "
                f"copied={len(copy_state.copied_text)}]"
            )
        else:
            right_segment = f"[{active_pane.pane_id}: {provider}"
            if state:
                right_segment += f" {state}"
            if active_pane.scroll_offset:
                right_segment += f" scroll={active_pane.scroll_offset}"
            right_segment += "]"

        start = max(x, width - len(right_segment))
        self._write_status_segment(chars, start, right_segment, fg="green", bold=True)
        return chars

    @staticmethod
    def _write_status_segment(
        chars: list[Char],
        start: int,
        text: str,
        *,
        fg: str,
        bold: bool,
    ) -> int:
        x = start
        for ch in text:
            if x >= len(chars):
                break
            chars[x] = Char(ch, fg, "bright_black", bold, False, False, False, False, False)
            x += 1
        return x

    def _window_label(self, window: WindowState) -> str:
        pane = window.focused
        if pane is None:
            panes = window.all_panes()
            pane = panes[0] if panes else None
        if pane is None:
            return "window"
        return self._provider_label(pane)

    @staticmethod
    def _provider_label(pane: Pane) -> str:
        session = pane.session
        shell_type = getattr(session, "shell_type", None)
        if shell_type:
            return shell_type
        name = type(session).__name__
        if name.endswith("Session"):
            name = name[:-7]
        return name.lower() or "session"

    # ── Cleanup ──

    def _cleanup(self) -> None:
        for pane in self._all_panes():
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
