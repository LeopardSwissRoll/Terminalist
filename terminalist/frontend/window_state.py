"""WindowState — one logical tmux-style window.

Owns one pane tree plus window-local focus/zoom state.
App owns the ordered list of windows and active window switching.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from terminalist.core.pane import Pane, Rect
from terminalist.frontend.split_tree import Leaf, SplitNode, all_panes, layout


@dataclass
class WindowState:
    window_id: str
    root: SplitNode | None
    focused: Pane | None = None
    focus_history: list[str] = field(default_factory=list)
    zoom_pane: Pane | None = None
    pre_zoom_root: SplitNode | None = None
    needs_layout: bool = True
    last_layout_size: tuple[int, int] | None = None
    is_active: bool = False

    def __post_init__(self) -> None:
        if self.focused is None and self.root is not None:
            panes = all_panes(self.root)
            if panes:
                self.focused = panes[0]
                self.focus_history = [panes[0].pane_id]

    def all_panes(self) -> list[Pane]:
        return all_panes(self.root) if self.root else []

    def visible_panes(self) -> list[Pane]:
        root = self.active_root()
        return all_panes(root) if root else []

    def active_root(self) -> SplitNode | None:
        if self.zoom_pane is not None:
            return Leaf(self.zoom_pane)
        return self.root

    def is_empty(self) -> bool:
        return self.root is None or not self.all_panes()

    def activate(self) -> None:
        self.is_active = True
        if self.focused is not None:
            self.focused.focus()
            self._touch_focus_history(self.focused)

    def deactivate(self) -> None:
        if self.focused is not None:
            self.focused.blur()
        self.is_active = False

    def set_focus(self, pane: Pane) -> None:
        if self.focused is pane:
            self._touch_focus_history(pane)
            if self.is_active:
                pane.focus()
            return

        if self.focused is not None:
            self.focused.blur()
        self.focused = pane
        self._touch_focus_history(pane)
        if self.is_active:
            pane.focus()

    def layout(self, rect: Rect, terminal_size: tuple[int, int] | None = None) -> None:
        root = self.active_root()
        if root is not None:
            layout(root, rect)
        self.needs_layout = False
        self.last_layout_size = terminal_size

    def toggle_zoom(self) -> bool:
        if self.zoom_pane is not None:
            self.clear_zoom()
            return False

        if self.root is None or self.focused is None:
            return False

        self.pre_zoom_root = self.root
        self.zoom_pane = self.focused
        return True

    def clear_zoom(self) -> None:
        self.zoom_pane = None
        self.pre_zoom_root = None

    def _touch_focus_history(self, pane: Pane) -> None:
        self.focus_history = [pane_id for pane_id in self.focus_history if pane_id != pane.pane_id]
        self.focus_history.append(pane.pane_id)
