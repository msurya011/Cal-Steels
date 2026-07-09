"""
WebSocket connection manager for real-time events (job progress, notifications).
Clients connect to /api/v1/events?token=<jwt> and receive JSON frames:
  { type: "job.progress", payload: {...} }
  { type: "job.done",     payload: {...} }
  { type: "notification", payload: {...} }
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections keyed by user_id."""

    def __init__(self) -> None:
        # user_id -> set of connected websockets
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.setdefault(user_id, set()).add(ws)
        logger.debug("WS connect: user=%s total=%d", user_id, len(self._connections.get(user_id, set())))

    async def disconnect(self, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(user_id, set())
            conns.discard(ws)
            if not conns:
                self._connections.pop(user_id, None)
        logger.debug("WS disconnect: user=%s", user_id)

    async def send_to_user(self, user_id: str, event_type: str, payload: Any) -> None:
        """Send an event to all WebSocket connections for a user."""
        frame = json.dumps({"type": event_type, "payload": payload})
        conns = self._connections.get(user_id, set()).copy()
        dead: Set[WebSocket] = set()
        for ws in conns:
            try:
                await ws.send_text(frame)
            except Exception as exc:
                logger.debug("WS send failed (%s): %s", user_id, exc)
                dead.add(ws)

        if dead:
            async with self._lock:
                self._connections.get(user_id, set()).difference_update(dead)

    async def broadcast_job_progress(
        self,
        user_id: str,
        job_id: str,
        progress: int,
        message: Optional[str] = None,
    ) -> None:
        await self.send_to_user(user_id, "job.progress", {
            "job_id": job_id,
            "progress": progress,
            "message": message,
        })

    async def broadcast_job_done(
        self,
        user_id: str,
        job_id: str,
        result_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        await self.send_to_user(user_id, "job.done", {
            "job_id": job_id,
            "result_type": result_type,
            "entity_id": entity_id,
            "error": error,
        })

    async def broadcast_notification(self, user_id: str, notification: Dict[str, Any]) -> None:
        await self.send_to_user(user_id, "notification", notification)


# Singleton — shared across all routers
manager = ConnectionManager()
