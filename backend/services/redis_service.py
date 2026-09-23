"""Redis caching service with graceful in-memory fallback.

Provides:
- Generic cache operations (get/set/delete/exists)
- Visitor embedding caching
- Session data caching
- API rate limiting counters
- Visitor search result caching with TTL
- Connection pooling via redis-py ConnectionPool
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("sentinelcv.redis_service")

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD: Optional[str] = os.getenv("REDIS_PASSWORD") or None
REDIS_URL: Optional[str] = os.getenv("REDIS_URL") or None
REDIS_POOL_MAX_CONNECTIONS: int = int(os.getenv("REDIS_POOL_MAX_CONNECTIONS", "20"))
IS_PRODUCTION: bool = (os.getenv("SENTINELCV_ENV") or "").strip().lower() == "production"

# Default TTLs (seconds)
DEFAULT_CACHE_TTL: int = int(os.getenv("REDIS_DEFAULT_TTL", "3600"))
EMBEDDING_CACHE_TTL: int = int(os.getenv("REDIS_EMBEDDING_TTL", "7200"))
SESSION_CACHE_TTL: int = int(os.getenv("REDIS_SESSION_TTL", "1800"))
SEARCH_RESULT_TTL: int = int(os.getenv("REDIS_SEARCH_RESULT_TTL", "300"))

# Key prefixes
KEY_PREFIX: str = "sentinelcv:"
EMBEDDING_PREFIX: str = f"{KEY_PREFIX}embedding:"
SESSION_PREFIX: str = f"{KEY_PREFIX}session:"
RATE_LIMIT_PREFIX: str = f"{KEY_PREFIX}ratelimit:"
SEARCH_PREFIX: str = f"{KEY_PREFIX}search:"


# ---------------------------------------------------------------------------
# In-memory fallback store
# ---------------------------------------------------------------------------

class _InMemoryStore:
    """Thread-safe dict-based fallback when Redis is unavailable."""

    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}
        self._expiry: Dict[str, float] = {}
        self._lock = threading.Lock()

    def _evict_expired(self) -> int:
        now = time.time()
        expired_keys = [k for k, exp in self._expiry.items() if exp <= now]
        for k in expired_keys:
            self._data.pop(k, None)
            self._expiry.pop(k, None)
        return len(expired_keys)

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            self._evict_expired()
            return self._data.get(key)

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        with self._lock:
            self._data[key] = value
            if ttl and ttl > 0:
                self._expiry[key] = time.time() + ttl
            else:
                self._expiry.pop(key, None)

    def delete(self, key: str) -> bool:
        with self._lock:
            existed = key in self._data
            self._data.pop(key, None)
            self._expiry.pop(key, None)
            return existed

    def exists(self, key: str) -> bool:
        with self._lock:
            self._evict_expired()
            return key in self._data

    def incr(self, key: str) -> int:
        with self._lock:
            self._evict_expired()
            current = int(self._data.get(key, 0))
            current += 1
            self._data[key] = str(current)
            return current

    def expire(self, key: str, ttl: int) -> None:
        with self._lock:
            if key in self._data:
                self._expiry[key] = time.time() + ttl

    def ttl(self, key: str) -> int:
        with self._lock:
            exp = self._expiry.get(key)
            if exp is None:
                return -1
            remaining = int(exp - time.time())
            return max(remaining, 0)

    def flush(self) -> None:
        with self._lock:
            self._data.clear()
            self._expiry.clear()

    def cleanup(self) -> int:
        """Remove expired keys and return the number of keys removed."""
        with self._lock:
            return self._evict_expired()


# ---------------------------------------------------------------------------
# Redis Service
# ---------------------------------------------------------------------------

class RedisService:
    """Unified Redis caching service with in-memory fallback.

    Usage::

        redis_svc = RedisService()
        redis_svc.connect()              # call once at startup
        redis_svc.cache_set("foo", "bar", ttl=60)
        value = redis_svc.cache_get("foo")
    """

    # Exponential backoff for reconnection attempts
    _RECONNECT_BASE_DELAY: float = 5.0
    _RECONNECT_MAX_DELAY: float = 300.0   # cap at 5 min

    def __init__(self) -> None:
        self._client: Any = None
        self._pool: Any = None
        self._fallback = _InMemoryStore()
        self._connected = False
        self._using_fallback = True
        self._metrics_lock = threading.Lock()
        self._metrics: Dict[str, int] = {
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_sets": 0,
            "cache_deletes": 0,
            "cache_errors": 0,
            "fallback_reads": 0,
            "fallback_writes": 0,
            "reconnect_attempts": 0,
            "reconnect_successes": 0,
        }
        self._last_error: Optional[str] = None
        self._last_error_at: Optional[float] = None
        self._reconnect_attempt: int = 0
        self._next_reconnect_at: float = 0.0
        self._reconnect_lock = threading.Lock()

    def _record_metric(self, name: str, value: int = 1) -> None:
        with self._metrics_lock:
            self._metrics[name] = self._metrics.get(name, 0) + value

    def _record_cache_result(self, value: Optional[str]) -> None:
        if value is None:
            self._record_metric("cache_misses")
        else:
            self._record_metric("cache_hits")

    def _record_error(self, exc: Exception) -> None:
        self._record_metric("cache_errors")
        self._last_error = str(exc)
        self._last_error_at = time.time()
        self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        """Push out the next reconnect attempt using exponential backoff."""
        delay = min(
            self._RECONNECT_BASE_DELAY * (2 ** self._reconnect_attempt),
            self._RECONNECT_MAX_DELAY,
        )
        self._next_reconnect_at = time.time() + delay

    def _maybe_reconnect(self) -> None:
        """Try to reconnect to Redis if the backoff window has elapsed.

        Called lazily from cache operations when using the in-memory fallback.
        Uses a lock so only one thread attempts the reconnect at a time.
        """
        if not self._using_fallback:
            return
        if time.time() < self._next_reconnect_at:
            return
        if not self._reconnect_lock.acquire(blocking=False):
            return  # another thread is already reconnecting
        try:
            if not self._using_fallback or time.time() < self._next_reconnect_at:
                return  # re-check under lock
            self._record_metric("reconnect_attempts")
            self._reconnect_attempt += 1
            logger.info(
                "Attempting Redis reconnect (attempt %d, backoff=%.0fs)",
                self._reconnect_attempt,
                min(
                    self._RECONNECT_BASE_DELAY * (2 ** (self._reconnect_attempt - 1)),
                    self._RECONNECT_MAX_DELAY,
                ),
            )
            success = self.connect()
            if success:
                self._reconnect_attempt = 0
                self._next_reconnect_at = 0.0
                self._record_metric("reconnect_successes")
                logger.info("Redis reconnected successfully after %d attempt(s)", self._reconnect_attempt)
            else:
                self._schedule_reconnect()
        finally:
            self._reconnect_lock.release()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Attempt to connect to Redis. Returns True on success."""
        try:
            import redis as redis_lib  # type: ignore
        except ImportError:
            log_fn = logger.critical if IS_PRODUCTION else logger.warning
            log_fn("redis Python package not installed. Using in-memory fallback.")
            self._using_fallback = True
            return False

        try:
            if REDIS_URL:
                self._pool = redis_lib.ConnectionPool.from_url(
                    REDIS_URL,
                    decode_responses=True,
                    max_connections=REDIS_POOL_MAX_CONNECTIONS,
                )
            else:
                self._pool = redis_lib.ConnectionPool(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    db=REDIS_DB,
                    password=REDIS_PASSWORD,
                    decode_responses=True,
                    max_connections=REDIS_POOL_MAX_CONNECTIONS,
                )

            self._client = redis_lib.Redis(connection_pool=self._pool)
            self._client.ping()
            self._connected = True
            self._using_fallback = False
            logger.info(
                "Redis connected successfully (%s:%s db=%s)",
                REDIS_HOST,
                REDIS_PORT,
                REDIS_DB,
            )
            return True
        except Exception as exc:
            log_fn = logger.critical if IS_PRODUCTION else logger.warning
            log_fn(
                "Redis connection failed (%s). Using in-memory fallback.",
                exc,
            )
            self._client = None
            self._pool = None
            self._connected = False
            self._using_fallback = True
            return False

    def disconnect(self) -> None:
        """Close the Redis connection pool."""
        if self._pool is not None:
            try:
                self._pool.disconnect()
            except Exception:
                pass
        self._client = None
        self._pool = None
        self._connected = False
        self._using_fallback = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def using_fallback(self) -> bool:
        return self._using_fallback

    def status(self) -> Dict[str, Any]:
        """Return a dict describing current connection state."""
        return {
            "connected": self._connected,
            "using_fallback": self._using_fallback,
            "host": REDIS_HOST,
            "port": REDIS_PORT,
            "db": REDIS_DB,
        }

    # ------------------------------------------------------------------
    # Generic cache operations
    # ------------------------------------------------------------------

    def cache_get(self, key: str) -> Optional[str]:
        """Retrieve a cached value by key. Returns None on miss."""
        self._maybe_reconnect()
        if self._using_fallback:
            value = self._fallback.get(key)
            self._record_metric("fallback_reads")
            self._record_cache_result(value)
            return value
        try:
            value = self._client.get(key)
            self._record_cache_result(value)
            return value
        except Exception as exc:
            logger.debug("Redis GET failed for %s: %s", key, exc)
            self._record_error(exc)
            self._using_fallback = True
            value = self._fallback.get(key)
            self._record_metric("fallback_reads")
            self._record_cache_result(value)
            return value

    def cache_set(
        self, key: str, value: str, ttl: Optional[int] = None
    ) -> bool:
        """Store a value. *ttl* is in seconds; None means no expiry."""
        self._maybe_reconnect()
        effective_ttl = ttl if ttl is not None else DEFAULT_CACHE_TTL
        self._record_metric("cache_sets")
        if self._using_fallback:
            self._fallback.set(key, value, effective_ttl)
            self._record_metric("fallback_writes")
            return True
        try:
            if effective_ttl and effective_ttl > 0:
                self._client.setex(key, effective_ttl, value)
            else:
                self._client.set(key, value)
            return True
        except Exception as exc:
            logger.debug("Redis SET failed for %s: %s", key, exc)
            self._record_error(exc)
            self._using_fallback = True
            self._fallback.set(key, value, effective_ttl)
            self._record_metric("fallback_writes")
            return False

    def cache_delete(self, key: str) -> bool:
        """Remove a key from the cache. Returns True if the key existed."""
        self._record_metric("cache_deletes")
        if self._using_fallback:
            return self._fallback.delete(key)
        try:
            return bool(self._client.delete(key))
        except Exception as exc:
            logger.debug("Redis DELETE failed for %s: %s", key, exc)
            self._record_error(exc)
            return self._fallback.delete(key)

    def cache_exists(self, key: str) -> bool:
        """Check whether a key exists."""
        if self._using_fallback:
            return self._fallback.exists(key)
        try:
            return bool(self._client.exists(key))
        except Exception as exc:
            logger.debug("Redis EXISTS failed for %s: %s", key, exc)
            return self._fallback.exists(key)

    def cache_set_json(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        """Serialize a Python value to JSON before storing it."""
        try:
            payload = json.dumps(value, default=str)
        except (TypeError, ValueError):
            return False
        return self.cache_set(key, payload, ttl=ttl)

    def cache_get_json(self, key: str) -> Optional[Any]:
        """Load a cached JSON value."""
        raw = self.cache_get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None

    def scan_keys(self, pattern: str) -> list:
        """Return all keys matching *pattern* (glob-style).

        Falls back to an in-memory prefix/suffix scan when Redis is unavailable.
        """
        if self._using_fallback:
            import fnmatch
            self._fallback._evict_expired()
            with self._fallback._lock:
                return [k for k in self._fallback._data if fnmatch.fnmatch(k, pattern)]
        try:
            keys = []
            cursor = 0
            while True:
                cursor, batch = self._client.scan(cursor, match=pattern, count=100)
                keys.extend(k.decode() if isinstance(k, bytes) else k for k in batch)
                if cursor == 0:
                    break
            return keys
        except Exception as exc:
            logger.debug("Redis SCAN failed for %s: %s", pattern, exc)
            return []

    @property
    def is_redis(self) -> bool:
        """Compatibility flag for callers that need durable Redis semantics."""
        return self._connected and not self._using_fallback

    def list_right_push(self, key: str, value: str) -> bool:
        """Append a value to the tail of a Redis list."""
        if self._using_fallback:
            try:
                current = self.cache_get_json(key) or []
                if not isinstance(current, list):
                    current = []
                current.append(value)
                self.cache_set_json(key, current, ttl=DEFAULT_CACHE_TTL)
                self._record_metric("fallback_writes")
                return True
            except Exception:
                return False

        try:
            self._client.rpush(key, value)
            return True
        except Exception as exc:
            logger.debug("Redis RPUSH failed for %s: %s", key, exc)
            self._record_error(exc)
            return False

    def list_left_pop(self, key: str) -> Optional[str]:
        """Pop a value from the head of a Redis list."""
        if self._using_fallback:
            current = self.cache_get_json(key) or []
            if not isinstance(current, list) or not current:
                return None
            value = current.pop(0)
            self.cache_set_json(key, current, ttl=DEFAULT_CACHE_TTL)
            self._record_metric("fallback_reads")
            return str(value)

        try:
            value = self._client.lpop(key)
            if value is None:
                return None
            return str(value)
        except Exception as exc:
            logger.debug("Redis LPOP failed for %s: %s", key, exc)
            self._record_error(exc)
            return None

    def list_remove(self, key: str, value: str, count: int = 0) -> int:
        """Remove matching values from a Redis list."""
        if self._using_fallback:
            current = self.cache_get_json(key) or []
            if not isinstance(current, list):
                return 0
            removed = 0
            remaining = []
            for item in current:
                if (count == 0 or removed < abs(count)) and str(item) == value:
                    removed += 1
                    continue
                remaining.append(item)
            self.cache_set_json(key, remaining, ttl=DEFAULT_CACHE_TTL)
            return removed

        try:
            return int(self._client.lrem(key, count, value))
        except Exception as exc:
            logger.debug("Redis LREM failed for %s: %s", key, exc)
            self._record_error(exc)
            return 0

    def list_length(self, key: str) -> int:
        """Return the current length of a Redis list."""
        if self._using_fallback:
            current = self.cache_get_json(key) or []
            if isinstance(current, list):
                return len(current)
            return 0

        try:
            return int(self._client.llen(key))
        except Exception as exc:
            logger.debug("Redis LLEN failed for %s: %s", key, exc)
            self._record_error(exc)
            return 0

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> Dict[str, Any]:
        """Sliding-window counter rate limiting.

        Returns a dict::

            {
                "allowed": True/False,
                "current": <int>,
                "limit": <int>,
                "remaining": <int>,
                "retry_after": <int or None>,
            }
        """
        full_key = f"{RATE_LIMIT_PREFIX}{key}"

        if self._using_fallback:
            return self._rate_limit_fallback(full_key, max_requests, window_seconds)

        try:
            return self._rate_limit_redis(full_key, max_requests, window_seconds)
        except Exception as exc:
            logger.debug("Redis rate limit check failed: %s", exc)
            return self._rate_limit_fallback(full_key, max_requests, window_seconds)

    def _rate_limit_redis(
        self, key: str, max_requests: int, window_seconds: int
    ) -> Dict[str, Any]:
        """Atomic rate limit check using Redis INCR + EXPIRE."""
        current = self._client.incr(key)
        if current == 1:
            # First request in this window — set expiry
            self._client.expire(key, window_seconds)

        ttl = self._client.ttl(key)
        if ttl < 0:
            # Key exists without expiry (edge case) — set it now
            self._client.expire(key, window_seconds)
            ttl = window_seconds

        allowed = current <= max_requests
        remaining = max(0, max_requests - current)
        retry_after = ttl if not allowed else None

        return {
            "allowed": allowed,
            "current": current,
            "limit": max_requests,
            "remaining": remaining,
            "retry_after": retry_after,
        }

    def _rate_limit_fallback(
        self, key: str, max_requests: int, window_seconds: int
    ) -> Dict[str, Any]:
        """In-memory rate limit check."""
        current = self._fallback.incr(key)
        if current == 1:
            self._fallback.expire(key, window_seconds)

        ttl = self._fallback.ttl(key)

        allowed = current <= max_requests
        remaining = max(0, max_requests - current)
        retry_after = ttl if not allowed else None

        return {
            "allowed": allowed,
            "current": current,
            "limit": max_requests,
            "remaining": remaining,
            "retry_after": retry_after,
        }

    # ------------------------------------------------------------------
    # Visitor embedding cache
    # ------------------------------------------------------------------

    def cache_visitor_embedding(
        self, visitor_id: str, embedding_json: str, ttl: Optional[int] = None
    ) -> bool:
        """Cache a visitor's face embedding JSON."""
        key = f"{EMBEDDING_PREFIX}{visitor_id}"
        return self.cache_set(key, embedding_json, ttl or EMBEDDING_CACHE_TTL)

    def get_visitor_embedding(self, visitor_id: str) -> Optional[str]:
        """Retrieve a cached visitor embedding."""
        key = f"{EMBEDDING_PREFIX}{visitor_id}"
        return self.cache_get(key)

    def invalidate_visitor_embedding(self, visitor_id: str) -> bool:
        """Remove a cached visitor embedding."""
        key = f"{EMBEDDING_PREFIX}{visitor_id}"
        return self.cache_delete(key)

    # ------------------------------------------------------------------
    # Session data cache
    # ------------------------------------------------------------------

    def cache_session(
        self, session_id: str, data: Dict[str, Any], ttl: Optional[int] = None
    ) -> bool:
        """Store session data as JSON."""
        key = f"{SESSION_PREFIX}{session_id}"
        return self.cache_set(key, json.dumps(data), ttl or SESSION_CACHE_TTL)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached session data."""
        key = f"{SESSION_PREFIX}{session_id}"
        raw = self.cache_get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def invalidate_session(self, session_id: str) -> bool:
        """Remove a cached session."""
        key = f"{SESSION_PREFIX}{session_id}"
        return self.cache_delete(key)

    def cleanup_sessions(self, max_keys: int = 500) -> Dict[str, Any]:
        """Attempt to remove expired sessions and report results.

        Redis manages expirations automatically; this method provides a
        bounded scan for cleanup and visibility, especially when fallback
        storage is active.
        """
        if self._using_fallback:
            cleaned = self._fallback.cleanup()
            return {
                "mode": "fallback",
                "scanned": 0,
                "cleaned": cleaned,
            }

        if not self._client:
            return {
                "mode": "redis",
                "scanned": 0,
                "cleaned": 0,
            }

        scanned = 0
        cleaned = 0
        cursor = 0
        pattern = f"{SESSION_PREFIX}*"

        try:
            while True:
                cursor, keys = self._client.scan(
                    cursor=cursor,
                    match=pattern,
                    count=min(100, max(1, max_keys - scanned)),
                )
                for key in keys:
                    scanned += 1
                    ttl = self._client.ttl(key)
                    if ttl is not None and ttl <= 0:
                        if self._client.delete(key):
                            cleaned += 1
                    if scanned >= max_keys:
                        break
                if cursor == 0 or scanned >= max_keys:
                    break
        except Exception as exc:
            self._record_error(exc)

        return {
            "mode": "redis",
            "scanned": scanned,
            "cleaned": cleaned,
        }

    # ------------------------------------------------------------------
    # Visitor search result cache
    # ------------------------------------------------------------------

    def cache_search_results(
        self,
        query_hash: str,
        results: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        """Cache visitor search results (serialized as JSON)."""
        key = f"{SEARCH_PREFIX}{query_hash}"
        try:
            payload = json.dumps(results, default=str)
        except (TypeError, ValueError):
            return False
        return self.cache_set(key, payload, ttl or SEARCH_RESULT_TTL)

    def get_search_results(self, query_hash: str) -> Optional[Any]:
        """Retrieve cached search results."""
        key = f"{SEARCH_PREFIX}{query_hash}"
        raw = self.cache_get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def invalidate_search_results(self, query_hash: str) -> bool:
        """Remove cached search results."""
        key = f"{SEARCH_PREFIX}{query_hash}"
        return self.cache_delete(key)

    def get_metrics(self) -> Dict[str, Any]:
        """Return cache metrics for monitoring endpoints."""
        with self._metrics_lock:
            metrics = dict(self._metrics)

        hits = metrics.get("cache_hits", 0)
        misses = metrics.get("cache_misses", 0)
        total = hits + misses
        hit_ratio = round(hits / total, 4) if total else 0.0

        next_reconnect_in: Optional[float] = None
        if self._using_fallback and self._next_reconnect_at > 0:
            remaining = self._next_reconnect_at - time.time()
            next_reconnect_in = max(round(remaining, 1), 0.0)

        return {
            "connected": self._connected,
            "using_fallback": self._using_fallback,
            "cache_hits": hits,
            "cache_misses": misses,
            "cache_sets": metrics.get("cache_sets", 0),
            "cache_deletes": metrics.get("cache_deletes", 0),
            "cache_errors": metrics.get("cache_errors", 0),
            "fallback_reads": metrics.get("fallback_reads", 0),
            "fallback_writes": metrics.get("fallback_writes", 0),
            "reconnect_attempts": metrics.get("reconnect_attempts", 0),
            "reconnect_successes": metrics.get("reconnect_successes", 0),
            "next_reconnect_in_seconds": next_reconnect_in,
            "cache_hit_ratio": hit_ratio,
            "last_error": self._last_error,
            "last_error_at": self._last_error_at,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[RedisService] = None
_instance_lock = threading.Lock()


def get_redis_service() -> RedisService:
    """Return the module-level RedisService singleton (lazy init)."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = RedisService()
                _instance.connect()
    return _instance


def init_redis_service() -> RedisService:
    """Explicitly initialize the singleton (idempotent). Call at startup."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = RedisService()
        if not _instance.is_connected:
            _instance.connect()
    return _instance


def shutdown_redis_service() -> None:
    """Tear down the singleton connection (call at shutdown)."""
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.disconnect()
            _instance = None
