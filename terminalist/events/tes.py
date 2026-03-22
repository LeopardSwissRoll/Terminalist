"""EventStreamManager — Typed Event Stream with 3 channels.

GC strategy: cursor-based pruning (tmux per-client tracking pattern).
- Track each consumer's cursor position
- Periodically prune events below the minimum cursor
- File logging preserves full history for cross-session data replay
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from terminalist.debug import log
from .event import Channel, Event


class EventStreamManager:
    """Typed Event Stream. Manages Data/Control/State channels."""

    def __init__(self, event_log_path: Path | None = None) -> None:
        self._events: list[Event] = []
        self._next_id: int = 1
        self._lock = threading.Lock()

        # Control: immediate dispatch per target
        self._control_handlers: dict[str, Callable[[Event], None]] = {}

        # State: broadcast to all subscribers
        self._state_subscribers: list[Callable[[Event], None]] = []

        # Data: notify target session when new data arrives
        self._data_subscribers: dict[str, Callable[[Event], None]] = {}

        # GC: track each consumer's cursor for pruning
        self._consumer_cursors: dict[str, int] = {}

        # File logging for history preservation
        self._log_file = None
        if event_log_path:
            self._log_file = open(event_log_path, "a", encoding="utf-8")
            log("tes", f"Event log: {event_log_path}")

    def close(self) -> None:
        """Close file logger."""
        if self._log_file:
            self._log_file.close()
            self._log_file = None

    # ── Core publish ──

    def publish(
        self,
        channel: Channel,
        kind: str,
        source: str,
        target: str | None,
        data: dict[str, Any],
        cause_id: int | None = None,
    ) -> Event:
        """Publish an event to the stream."""
        with self._lock:
            event = Event(
                id=self._next_id,
                channel=channel,
                kind=kind,
                source=source,
                target=target,
                data=data,
                cause_id=cause_id,
            )
            self._next_id += 1
            # Only keep Data events in memory (Control/State are dispatched immediately)
            if channel == Channel.DATA:
                self._events.append(event)

        # Log all events to file for history
        self._log_event(event)

        if channel == Channel.CONTROL:
            self._dispatch_control(event)
        elif channel == Channel.STATE:
            self._dispatch_state(event)
        elif channel == Channel.DATA:
            self._dispatch_data_notify(event)

        return event

    # ── Convenience methods ──

    def publish_data(
        self,
        source: str,
        target: str,
        text: str,
        cause_id: int | None = None,
    ) -> Event:
        return self.publish(
            Channel.DATA, "input", source, target, {"text": text}, cause_id
        )

    def publish_state(
        self, session_id: str, old_state: str, new_state: str
    ) -> Event:
        return self.publish(
            Channel.STATE,
            "state_change",
            f"session:{session_id}",
            None,
            {"old": old_state, "new": new_state},
        )

    def publish_control(
        self, kind: str, target: str, data: dict[str, Any] | None = None
    ) -> Event:
        return self.publish(
            Channel.CONTROL, kind, "system", target, data or {}
        )

    # ── Data consumption (FIFO, cursor-based) ──

    def next_data_for(self, session_id: str, after_id: int) -> Event | None:
        """Return next Data event targeting session_id after the given cursor."""
        target_key = f"session:{session_id}"
        with self._lock:
            for event in self._events:
                if (
                    event.id > after_id
                    and event.channel == Channel.DATA
                    and event.target == target_key
                ):
                    # Update consumer cursor for GC
                    self._consumer_cursors[session_id] = event.id
                    return event
        return None

    # ── GC: cursor-based pruning ──

    def gc(self) -> int:
        """Prune events consumed by ALL subscribers.

        Returns number of events pruned.
        Uses the minimum cursor across all consumers — events below
        that point have been consumed by everyone and are safe to remove.
        (Ref: tmux per-client consumption tracking)
        """
        if not self._consumer_cursors:
            return 0
        min_cursor = min(self._consumer_cursors.values())
        with self._lock:
            before = len(self._events)
            self._events = [e for e in self._events if e.id >= min_cursor]
            pruned = before - len(self._events)
        if pruned > 0:
            log("tes", f"GC pruned {pruned} events (min_cursor={min_cursor}, remaining={len(self._events)})")
        return pruned

    def register_consumer(self, session_id: str, cursor: int = 0) -> None:
        """Register a consumer for GC tracking."""
        self._consumer_cursors[session_id] = cursor

    def unregister_consumer(self, session_id: str) -> None:
        """Remove a consumer from GC tracking."""
        self._consumer_cursors.pop(session_id, None)

    @property
    def event_count(self) -> int:
        """Number of events currently in memory."""
        with self._lock:
            return len(self._events)

    # ── File logging ──

    def _log_event(self, event: Event) -> None:
        """Append event to file log (JSONL format)."""
        if not self._log_file:
            return
        try:
            record = {
                "id": event.id,
                "ch": event.channel.value,
                "kind": event.kind,
                "src": event.source,
                "tgt": event.target,
                "data": event.data,
                "cause": event.cause_id,
                "ts": event.timestamp,
            }
            self._log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._log_file.flush()
        except Exception as e:
            log("tes", f"Event log write error: {e}")

    # ── Subscription ──

    def on_control(self, target: str, handler: Callable[[Event], None]) -> None:
        self._control_handlers[target] = handler

    def remove_control(self, target: str) -> None:
        self._control_handlers.pop(target, None)

    def on_data(self, target: str, callback: Callable[[Event], None]) -> None:
        """Register callback for when new Data events arrive for target."""
        self._data_subscribers[target] = callback

    def remove_data(self, target: str) -> None:
        self._data_subscribers.pop(target, None)

    def subscribe_state(self, callback: Callable[[Event], None]) -> None:
        self._state_subscribers.append(callback)

    def unsubscribe_state(self, callback: Callable[[Event], None]) -> None:
        try:
            self._state_subscribers.remove(callback)
        except ValueError:
            pass

    # ── Dispatch ──

    def _dispatch_control(self, event: Event) -> None:
        handler = self._control_handlers.get(event.target)
        if handler:
            handler(event)

    def _dispatch_state(self, event: Event) -> None:
        for cb in list(self._state_subscribers):
            cb(event)

    def _dispatch_data_notify(self, event: Event) -> None:
        """Notify target session that new data is available."""
        if event.target and event.target in self._data_subscribers:
            self._data_subscribers[event.target](event)
