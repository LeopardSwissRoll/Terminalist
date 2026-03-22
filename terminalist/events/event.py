"""Typed Event Stream — Event and Channel definitions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Channel(Enum):
    DATA = "data"  # FIFO, cursor-based consumption
    CONTROL = "control"  # Immediate dispatch, bypasses queue
    STATE = "state"  # Broadcast to all subscribers


@dataclass
class Event:
    id: int  # Monotonically increasing, assigned by TES
    channel: Channel
    kind: str  # "input", "output", "state_change", "kill", "resize", "tick", ...
    source: str  # "user", "session:claude_1", "timer:x", "file:/src"
    target: str | None  # "session:claude_1" or None (broadcast)
    data: dict[str, Any]  # Payload
    cause_id: int | None = None  # The event that triggered this one
    timestamp: float = field(default_factory=time.time)
