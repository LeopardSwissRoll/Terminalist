"""Core data model for TestPane."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Direction(Enum):
    VERTICAL = "v"
    HORIZONTAL = "h"


class MoveDirection(Enum):
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w - 1

    @property
    def bottom(self) -> int:
        return self.y + self.h - 1

    @property
    def center_x(self) -> float:
        return self.x + (self.w - 1) / 2

    @property
    def center_y(self) -> float:
        return self.y + (self.h - 1) / 2


@dataclass
class Pane:
    pane_id: str
    label: str
    rect: Rect


class SplitNode:
    """Base class for tree nodes."""


@dataclass
class Leaf(SplitNode):
    pane: Pane


@dataclass
class Split(SplitNode):
    direction: Direction
    first: SplitNode
    second: SplitNode

