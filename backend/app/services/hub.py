"""In-process WebSocket publish/subscribe hub."""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket


@dataclass(eq=False)
class Subscriber:
    ws: WebSocket
    user_id: int
    role: str
    topics: set[str] = field(default_factory=set)
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=2000))
    dropped: int = 0


class Hub:
    def __init__(self) -> None:
        self._subs: set[Subscriber] = set()

    def add(self, sub: Subscriber) -> None:
        self._subs.add(sub)

    def remove(self, sub: Subscriber) -> None:
        self._subs.discard(sub)

    @property
    def clients(self) -> int:
        return len(self._subs)

    def has_subscribers(self, topic: str) -> bool:
        return any(topic in s.topics for s in self._subs)

    def active_topics(self) -> set[str]:
        out: set[str] = set()
        for s in self._subs:
            out |= s.topics
        return out

    async def publish(self, topic: str, type_: str, data: Any) -> None:
        if not self._subs:
            return
        msg = json.dumps({"topic": topic, "type": type_, "data": data, "ts": time.time()}, default=str)
        for s in list(self._subs):
            if topic in s.topics:
                try:
                    s.queue.put_nowait(msg)
                except asyncio.QueueFull:
                    s.dropped += 1

    @staticmethod
    async def sender(sub: Subscriber) -> None:
        while True:
            msg = await sub.queue.get()
            await sub.ws.send_text(msg)

    async def close_all(self) -> None:
        for s in list(self._subs):
            with contextlib.suppress(Exception):
                await s.ws.close(code=1001)
        self._subs.clear()


hub = Hub()
