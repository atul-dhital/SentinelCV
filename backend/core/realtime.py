"""Realtime broadcast manager.

Single-process mode (default): messages are delivered in-memory to all
WebSocket connections registered in this process.

Multi-worker mode (REDIS_URL set): each process publishes broadcasts to a
Redis pub/sub channel. A background subscriber task running in every process
receives messages from Redis and forwards them to local WebSocket connections.
This ensures all workers share a consistent broadcast view regardless of which
worker handles a given HTTP request.

Pattern: all events for an organization publish to
  ``sentinelcv:rt:{organization_id}``
and a single per-process subscriber task listens on
  ``sentinelcv:rt:*``  (pattern subscribe).
"""

import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

_REDIS_CHANNEL_PREFIX = "sentinelcv:rt:"


class RealtimeManager:
    """Manages WebSocket connections partitioned by organization.

    When ``REDIS_URL`` is set the manager publishes to Redis so that all
    uvicorn workers receive every broadcast. Without Redis it falls back to
    direct in-memory delivery (single-worker only).
    """

    def __init__(self) -> None:
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._redis_pub = None          # async publish client (lazy)
        self._subscriber_task: Optional[asyncio.Task] = None
        self._subscriber_started = False
        self._lock = asyncio.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    async def connect(self, organization_id: str, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        org_id = str(organization_id)
        try:
            await websocket.accept()
        except Exception as exc:
            logger.error("Failed to accept WebSocket for org %s: %s", org_id, exc)
            return

        self._connections[org_id].add(websocket)
        logger.info("RT connect org=%s total=%d", org_id, len(self._connections[org_id]))
        await self._ensure_redis_subscriber()

    def disconnect(self, organization_id: str, websocket: WebSocket) -> None:
        """Unregister a WebSocket connection."""
        org_id = str(organization_id)
        if org_id in self._connections:
            self._connections[org_id].discard(websocket)
            if not self._connections[org_id]:
                self._connections.pop(org_id, None)

    async def broadcast(self, organization_id: str, event_type: str, payload: dict) -> None:
        """Broadcast an event to all connected clients of an organization.

        If Redis is configured, publishes to the shared channel and lets the
        subscriber task handle local delivery. Without Redis, delivers directly.
        """
        org_id = str(organization_id)
        message = json.dumps({
            "type": event_type,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        published = await self._redis_publish(org_id, message)
        if not published:
            await self._local_broadcast(org_id, message)

    # ── Redis helpers ─────────────────────────────────────────────────────────

    def _redis_url(self) -> Optional[str]:
        return (os.getenv("REDIS_URL") or "").strip() or None

    async def _ensure_redis_subscriber(self) -> None:
        """Start the background Redis subscriber task once per process."""
        if not self._redis_url():
            return
        async with self._lock:
            if self._subscriber_started and (
                self._subscriber_task and not self._subscriber_task.done()
            ):
                return
            self._subscriber_started = True
            self._subscriber_task = asyncio.create_task(self._redis_subscriber_loop())

    async def _redis_publish(self, org_id: str, message: str) -> bool:
        """Publish a message to the Redis channel for org_id.

        Returns True if published successfully, False if Redis is unavailable.
        """
        url = self._redis_url()
        if not url:
            return False
        try:
            if self._redis_pub is None:
                import redis.asyncio as aioredis  # type: ignore[import]
                self._redis_pub = await aioredis.from_url(url, decode_responses=True)
            await self._redis_pub.publish(f"{_REDIS_CHANNEL_PREFIX}{org_id}", message)
            return True
        except Exception as exc:
            logger.warning("RealtimeManager: Redis publish failed for org %s: %s", org_id, exc)
            self._redis_pub = None  # reset so next call retries the connection
            return False

    async def _redis_subscriber_loop(self) -> None:
        """Background task: subscribe to all org channels and deliver locally."""
        url = self._redis_url()
        if not url:
            return
        while True:
            client = None
            try:
                import redis.asyncio as aioredis  # type: ignore[import]
                client = await aioredis.from_url(url, decode_responses=True)
                async with client.pubsub() as pubsub:
                    await pubsub.psubscribe(f"{_REDIS_CHANNEL_PREFIX}*")
                    logger.info("RealtimeManager: Redis subscriber started (%s*)", _REDIS_CHANNEL_PREFIX)
                    async for msg in pubsub.listen():
                        if msg.get("type") != "pmessage":
                            continue
                        channel: str = msg.get("channel", "")
                        org_id = channel.removeprefix(_REDIS_CHANNEL_PREFIX)
                        data: str = msg.get("data", "")
                        if org_id and data:
                            await self._local_broadcast(org_id, data)
            except asyncio.CancelledError:
                logger.info("RealtimeManager: Redis subscriber cancelled")
                return
            except Exception as exc:
                logger.warning(
                    "RealtimeManager: Redis subscriber error (%s) — reconnecting in 5s", exc
                )
                await asyncio.sleep(5)
            finally:
                # Close the connection pool so sockets are not leaked between
                # reconnect attempts. aclose() is safe to call even if the
                # client was never fully connected.
                if client is not None:
                    try:
                        await client.aclose()
                    except Exception:
                        pass

    # ── Local delivery ────────────────────────────────────────────────────────

    async def _local_broadcast(self, org_id: str, message: str) -> None:
        """Send a pre-serialised message to all local WebSocket connections."""
        sockets = self._connections.get(org_id, set())
        if not sockets:
            return
        dead: list[WebSocket] = []
        for ws in list(sockets):
            try:
                await ws.send_text(message)
            except (WebSocketDisconnect, Exception) as exc:
                logger.debug("RT send error org=%s: %s", org_id, exc)
                dead.append(ws)
        for ws in dead:
            self.disconnect(org_id, ws)


realtime_manager = RealtimeManager()
