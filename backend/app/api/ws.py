from __future__ import annotations

import asyncio
import contextlib
import json
import re

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ..db import SessionLocal
from ..services.hub import Subscriber, hub
from ..state import accounts, bots
from .deps import user_from_token

router = APIRouter()
TOPIC_RE = re.compile(r"^(accounts|bots|account:\d+|bot:\d+)$")


@router.websocket("/ws")
async def websocket(ws: WebSocket):
    token = ws.query_params.get("token")
    if not token:
        protos = ws.headers.get("sec-websocket-protocol", "")
        token = next((p.strip()[len("bearer."):] for p in protos.split(",") if p.strip().startswith("bearer.")), None)
    db = SessionLocal()
    try:
        user = user_from_token(db, token or "")
    except HTTPException:
        await ws.close(code=4401)
        return
    finally:
        db.close()
    await ws.accept()
    sub = Subscriber(ws=ws, user_id=user.id, role=user.role)
    hub.add(sub)
    sender = asyncio.create_task(hub.sender(sub))
    await ws.send_text(json.dumps({"topic": "system", "type": "hello", "data": {"user": user.username}}))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            action, topics = msg.get("action"), [t for t in msg.get("topics", []) if isinstance(t, str) and TOPIC_RE.match(t)]
            if action == "subscribe":
                sub.topics.update(topics)
                for t in topics:
                    await _initial(sub, t)
            elif action == "unsubscribe":
                sub.topics.difference_update(topics)
            elif action == "ping":
                sub.queue.put_nowait(json.dumps({"topic": "system", "type": "pong", "data": None}))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.remove(sub)
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sender


async def _initial(sub: Subscriber, topic: str) -> None:
    """Send the current state right after subscription so the UI does not wait for the next tick."""
    msgs = []
    if topic.startswith("account:"):
        rt = accounts.runtimes.get(int(topic.split(":")[1]))
        if rt:
            msgs.append({"topic": topic, "type": "status", "data": rt.public()})
            if rt.status == "connected":
                msgs.append({"topic": topic, "type": "snapshot", "data": {
                    "account": rt.account, "terminal": rt.terminal, "positions": rt.positions, "orders": rt.orders}})
                if rt.ticks:
                    msgs.append({"topic": topic, "type": "ticks", "data": rt.ticks})
    elif topic.startswith("bot:"):
        m = bots.metrics(int(topic.split(":")[1]))
        if m:
            msgs.append({"topic": topic, "type": "metrics", "data": m})
    for m in msgs:
        with contextlib.suppress(asyncio.QueueFull):
            sub.queue.put_nowait(json.dumps(m, default=str))
