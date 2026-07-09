"""
WebSocket events router.
Clients connect to /api/v1/events?token=<jwt> to receive real-time events.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.core.events import manager
from app.core.security import get_current_user
from fastapi.security import HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)
router = APIRouter(tags=["events"])


@router.websocket("/events")
async def websocket_events(ws: WebSocket, token: str = Query(...)):
    """
    WebSocket endpoint for real-time job progress and notifications.
    Client must pass ?token=<supabase_jwt> in the URL.
    """
    # Verify the JWT token
    try:
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = await get_current_user(creds)
    except Exception as exc:
        logger.warning("WS auth failed: %s", exc)
        await ws.close(code=4001, reason="Authentication failed")
        return

    await manager.connect(user.id, ws)
    logger.info("WS connected: user=%s", user.id)

    try:
        # Send a welcome ping
        await ws.send_json({"type": "connected", "payload": {"user_id": user.id}})

        # Keep alive — echo pings from client
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=30)
                if data == "ping":
                    await ws.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # Send heartbeat to keep the connection alive
                await ws.send_json({"type": "heartbeat"})
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WS error for user %s: %s", user.id, exc)
    finally:
        await manager.disconnect(user.id, ws)
        logger.info("WS disconnected: user=%s", user.id)
