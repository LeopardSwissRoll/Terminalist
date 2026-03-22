"""EventStreamManager — Typed Event Stream with 3 channels."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from .event import Channel, Event


class EventStreamManager:
    """Typed Event Stream. Manages Data/Control/State channels."""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._next_id: int = 1
        self._lock = threading.Lock()

        # Control: immediate dispatch per target
        self._control_handlers: dict[str, Callable[[Event], None]] = {}

        # State: broadcast to all subscribers
        self._state_subscribers: list[Callable[[Event], None]] = []

        # Data: notify target session when new data arrives
        self._data_subscribers: dict[str, Callable[[Event], None]] = {}

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
            self._events.append(event)

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
                    return event
        return None

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
