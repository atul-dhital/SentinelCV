"""Unit tests for RealtimeManager (core/realtime.py).

Tests run entirely in-memory with fake WebSocket objects. No real Redis
server is required — Redis behaviour is simulated with monkeypatching.

Coverage:
- No-Redis: connect → broadcast → local delivery
- No-Redis: org isolation (org A messages don't reach org B)
- Dead socket removed from _connections during broadcast
- disconnect() is idempotent
- Redis publish success skips direct _local_broadcast (no double delivery)
- Redis publish failure falls back to _local_broadcast
- Subscriber task starts only once under concurrent connect() calls
- Redis reconnect calls client.aclose() in finally block
- Subscriber CancelledError exits cleanly without re-raising
"""

import asyncio
import json
from collections import defaultdict
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.realtime import RealtimeManager


# ── Fake WebSocket helpers ────────────────────────────────────────────────────


class FakeWebSocket:
    """Minimal fake that records sent messages."""

    def __init__(self):
        self.sent: list[str] = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_text(self, message: str):
        self.sent.append(message)


class DeadWebSocket:
    """Fake that raises on send_text, simulating a closed connection."""

    def __init__(self):
        self.sent: list[str] = []

    async def accept(self):
        pass

    async def send_text(self, message: str):
        raise RuntimeError("Connection closed")


# ── Fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture
def manager(monkeypatch):
    """Fresh RealtimeManager with REDIS_URL unset."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    return RealtimeManager()


# ── 1. No-Redis: connect → broadcast → local delivery ────────────────────────


@pytest.mark.asyncio
async def test_no_redis_broadcast_delivers_to_local_socket(manager):
    ws = FakeWebSocket()
    await manager.connect("org1", ws)
    await manager.broadcast("org1", "test_event", {"key": "value"})

    assert len(ws.sent) == 1
    data = json.loads(ws.sent[0])
    assert data["type"] == "test_event"
    assert data["payload"] == {"key": "value"}
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_no_redis_broadcast_multiple_clients_same_org(manager):
    ws_a, ws_b = FakeWebSocket(), FakeWebSocket()
    await manager.connect("org1", ws_a)
    await manager.connect("org1", ws_b)
    await manager.broadcast("org1", "ev", {})

    assert len(ws_a.sent) == 1
    assert len(ws_b.sent) == 1


@pytest.mark.asyncio
async def test_no_redis_broadcast_to_unknown_org_does_nothing(manager):
    ws = FakeWebSocket()
    await manager.connect("org1", ws)
    await manager.broadcast("org2", "ev", {})  # different org

    assert ws.sent == []


# ── 2. No-Redis: org isolation ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_redis_org_isolation(manager):
    ws_a, ws_b = FakeWebSocket(), FakeWebSocket()
    await manager.connect("org-A", ws_a)
    await manager.connect("org-B", ws_b)

    await manager.broadcast("org-A", "private_event", {"secret": True})

    assert len(ws_a.sent) == 1, "org-A socket must receive its own event"
    assert ws_b.sent == [], "org-B socket must not receive org-A event"


# ── 3. Dead socket removed during broadcast ───────────────────────────────────


@pytest.mark.asyncio
async def test_dead_socket_removed_during_broadcast(manager):
    good_ws = FakeWebSocket()
    dead_ws = DeadWebSocket()

    await manager.connect("org1", good_ws)
    await manager.connect("org1", dead_ws)
    assert len(manager._connections["org1"]) == 2

    await manager.broadcast("org1", "ev", {})

    # Good socket delivered, dead socket cleaned up
    assert len(good_ws.sent) == 1
    assert "org1" in manager._connections
    assert dead_ws not in manager._connections["org1"]


@pytest.mark.asyncio
async def test_all_dead_sockets_removes_org_key(manager):
    dead = DeadWebSocket()
    await manager.connect("org1", dead)
    await manager.broadcast("org1", "ev", {})

    assert "org1" not in manager._connections


# ── 4. disconnect() is idempotent ─────────────────────────────────────────────


def test_disconnect_idempotent(manager):
    ws = FakeWebSocket()
    manager._connections["org1"].add(ws)

    manager.disconnect("org1", ws)
    manager.disconnect("org1", ws)  # second call must not raise

    assert "org1" not in manager._connections


def test_disconnect_unknown_org_does_not_raise(manager):
    ws = FakeWebSocket()
    manager.disconnect("nonexistent-org", ws)  # must not raise


def test_disconnect_removes_org_key_when_empty(manager):
    ws_a, ws_b = FakeWebSocket(), FakeWebSocket()
    manager._connections["org1"].add(ws_a)
    manager._connections["org1"].add(ws_b)

    manager.disconnect("org1", ws_a)
    assert "org1" in manager._connections

    manager.disconnect("org1", ws_b)
    assert "org1" not in manager._connections


# ── 5. Redis publish success skips direct _local_broadcast ────────────────────


@pytest.mark.asyncio
async def test_redis_publish_success_no_direct_local_broadcast(manager, monkeypatch):
    """When Redis publish returns True, _local_broadcast must NOT be called
    directly by broadcast() — the subscriber handles delivery."""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    ws = FakeWebSocket()
    manager._connections["org1"].add(ws)

    local_calls: list[str] = []
    original_local = manager._local_broadcast

    async def spy_local(org_id: str, message: str):
        local_calls.append(org_id)
        await original_local(org_id, message)

    async def fake_publish(org_id: str, message: str) -> bool:
        return True  # simulate successful Redis publish

    manager._local_broadcast = spy_local
    manager._redis_publish = fake_publish

    await manager.broadcast("org1", "ev", {})

    # Publish succeeded → local broadcast must NOT have been called directly
    assert local_calls == [], (
        "_local_broadcast must not be called when Redis publish succeeds; "
        "subscriber loop handles delivery"
    )
    # Socket should have received nothing via direct path
    assert ws.sent == []


# ── 6. Redis publish failure falls back to _local_broadcast ──────────────────


@pytest.mark.asyncio
async def test_redis_publish_failure_falls_back_to_local(manager, monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    ws = FakeWebSocket()
    manager._connections["org1"].add(ws)

    async def fake_publish(org_id: str, message: str) -> bool:
        return False  # simulate Redis unavailable

    manager._redis_publish = fake_publish
    await manager.broadcast("org1", "ev", {"x": 1})

    assert len(ws.sent) == 1
    data = json.loads(ws.sent[0])
    assert data["payload"] == {"x": 1}


# ── 7. Subscriber task starts only once under concurrent calls ────────────────


@pytest.mark.asyncio
async def test_subscriber_task_starts_only_once(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    manager = RealtimeManager()

    task_count = 0
    original_create_task = asyncio.create_task

    async def fake_loop():
        await asyncio.sleep(1)  # run long enough to appear "not done"

    def counting_create_task(coro, **kwargs):
        nonlocal task_count
        task_count += 1
        return original_create_task(coro, **kwargs)

    with patch("asyncio.create_task", side_effect=counting_create_task):
        # Simulate 5 concurrent connects from the same org
        ws_list = [FakeWebSocket() for _ in range(5)]
        await asyncio.gather(*[manager.connect("org1", ws) for ws in ws_list])

    assert task_count == 1, (
        f"Expected exactly 1 subscriber task to be created, got {task_count}"
    )

    # Clean up background task if it started
    if manager._subscriber_task and not manager._subscriber_task.done():
        manager._subscriber_task.cancel()
        try:
            await manager._subscriber_task
        except (asyncio.CancelledError, Exception):
            pass


# ── 8. Redis reconnect calls client.aclose() ──────────────────────────────────


@pytest.mark.asyncio
async def test_redis_reconnect_calls_aclose_on_client(monkeypatch):
    """When the subscriber loop encounters an error, the Redis client must be
    closed via aclose() so connections are not leaked."""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    manager = RealtimeManager()

    aclose_called = False
    iteration = 0

    class FakeClient:
        async def aclose(self):
            nonlocal aclose_called
            aclose_called = True

        def pubsub(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def psubscribe(self, *args):
            nonlocal iteration
            iteration += 1
            if iteration == 1:
                raise ConnectionError("Redis refused")
            # Second iteration: raise CancelledError to stop the loop
            raise asyncio.CancelledError()

        def listen(self):
            async def _gen():
                return
                yield  # make it an async generator
            return _gen()

    async def fake_from_url(url, **kwargs):
        return FakeClient()

    with patch("redis.asyncio.from_url", new=fake_from_url):
        # Run the subscriber loop briefly; it should error, call aclose, then
        # get cancelled on the second iteration
        task = asyncio.create_task(manager._redis_subscriber_loop())
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    assert aclose_called, "client.aclose() must be called in the finally block on error"


# ── 9. Subscriber CancelledError exits cleanly ───────────────────────────────


@pytest.mark.asyncio
async def test_subscriber_cancelled_exits_cleanly(monkeypatch):
    """CancelledError must cause the subscriber loop to exit without re-raising
    or leaving the task in a bad state."""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    manager = RealtimeManager()

    class FakeClientCancelOnSubscribe:
        async def aclose(self):
            pass

        def pubsub(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def psubscribe(self, *args):
            raise asyncio.CancelledError()

        def listen(self):
            async def _gen():
                return
                yield
            return _gen()

    with patch("redis.asyncio.from_url", new=AsyncMock(return_value=FakeClientCancelOnSubscribe())):
        task = asyncio.create_task(manager._redis_subscriber_loop())
        await asyncio.wait_for(task, timeout=2.0)  # must not hang

    # Task completed without exception
    assert task.done()
    assert not task.cancelled(), "Task should exit normally on CancelledError, not be cancelled"
    assert task.exception() is None, f"Task raised: {task.exception()}"
