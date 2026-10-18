"""
Real-time event hub.

Every meaningful thing that happens during a call (a transcript line, a
sub-agent starting, a tool call, a risk score...) is published here as a small
JSON event. Agent-desktop browsers subscribe over ``/ws/desktop`` and render
the call purely from this event stream. New subscribers receive a replay of
recent calls so a page refresh mid-call loses nothing.

NOTE: state is in-process. On Cloud Run deploy with ``--max-instances=1``
(the deploy script does) so the phone webhook and the desktop websocket land
on the same instance. Swap this for Pub/Sub or Redis to scale horizontally.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("caseforge.events")
_seq = itertools.count(1)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class EventHub:
    MAX_CALLS = 6  # calls kept for replay

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._log: "OrderedDict[str, list[dict]]" = OrderedDict()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def replay(self) -> list[dict]:
        return [e for events in self._log.values() for e in events]

    def events_for(self, call_id: str) -> list[dict]:
        return list(self._log.get(call_id, []))

    def publish(self, call_id: str, type_: str, data: dict[str, Any] | None = None) -> dict:
        evt = {"seq": next(_seq), "type": type_, "call_id": call_id, "ts": now_iso(), "data": data or {}}
        if call_id not in self._log:
            self._log[call_id] = []
            while len(self._log) > self.MAX_CALLS:
                self._log.popitem(last=False)
        # interim transcripts are ephemeral - don't bloat the replay log
        if not (type_ == "transcript" and evt["data"].get("interim")):
            self._log[call_id].append(evt)
        for q in list(self._subs):
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:  # slow client: drop it
                log.warning("Dropping slow websocket subscriber")
                self._subs.discard(q)
        return evt


hub = EventHub()
